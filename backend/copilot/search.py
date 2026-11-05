"""
Search by meaning. `manage.py copilot_index` turns CRM records into embeddings;
a question is embedded the same way and compared by cosine similarity, with a
boost for exact words such as "INV-3602", which embeddings match poorly.

Access is enforced after matching, not by the index: every candidate is opened
through the CRM's own API as the person asking, so a record outside their role
or store is simply dropped. They and the AI only ever see live data.

Comparison runs in Python, which is fine for thousands of records. Move to
pgvector if the table reaches hundreds of thousands of rows.
"""
import hashlib
import math
import re

from catalog.models import Product
from parties.models import Party
from repairs.models import RepairTicket
from sales.models import Invoice

from . import dispatch, llm, redact
from .models import DocChunk

TOP_RESULTS = 6
CANDIDATES = 24
BATCH = 50
EXACT_BOOST = 1.0
WORD = re.compile(r"[a-z0-9][a-z0-9-]*", re.I)
DETAIL = {"party": "/parties/{}/", "invoice": "/invoices/{}/", "ticket": "/tickets/{}/", "product": "/products/{}/"}


def _party(row):
    return f"Customer {row.name}. Type {row.type}. City {row.city}."


def _invoice(row):
    items = ", ".join(item.label for item in row.items.all())
    return (f"Invoice {row.code} for {row.party.name}. {row.get_source_display()}. Status {row.status}. "
            f"Date {row.date}. Items: {items}.")


def _ticket(row):
    return (f"Repair {row.code} for {row.party.name}. Device {row.brand} {row.model_name}. "
            f"Problem: {row.issue}. Stage {row.status}.")


def _product(row):
    specs = ", ".join(f"{v.spec} {v.colour}".strip() for v in row.variants.all())
    return f"Product {row.brand} {row.model_name} {row.processor}. {row.category}, {row.condition}. Options: {specs}."


SOURCES = {
    "party": (Party.objects.all, _party),
    "invoice": (lambda: Invoice.objects.select_related("party").prefetch_related("items__variant__product"), _invoice),
    "ticket": (lambda: RepairTicket.objects.select_related("party"), _ticket),
    "product": (lambda: Product.objects.prefetch_related("variants"), _product),
}


def records():
    for kind, (queryset, describe) in SOURCES.items():
        for row in queryset().iterator(chunk_size=500):
            yield kind, row.pk, describe(row)


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rebuild(report=None):
    """Embed new or changed records and drop deleted ones. Safe to run again
    after a stopped run: finished records are skipped. Returns the counts."""
    model = llm.embed_model()
    existing = {(c["source_type"], c["source_id"]): c for c in DocChunk.objects.values("source_type", "source_id", "content_hash", "model")}
    seen, pending, written = set(), [], 0

    def flush():
        nonlocal written
        vectors = llm.embed([row[2] for row in pending])
        for (kind, pk, text), vector in zip(pending, vectors):
            DocChunk.objects.update_or_create(source_type=kind, source_id=pk, defaults={
                "content": text, "content_hash": _hash(text), "model": model, "embedding": vector})
        written += len(pending)
        pending.clear()
        if report:
            report(f"Indexed {written} records...")

    for kind, pk, text in records():
        seen.add((kind, pk))
        old = existing.get((kind, pk))
        if old and old["content_hash"] == _hash(text) and old["model"] == model:
            continue
        pending.append((kind, pk, text))
        if len(pending) >= BATCH:
            flush()
    if pending:
        flush()
    removed = 0
    for kind, pk in set(existing) - seen:
        DocChunk.objects.filter(source_type=kind, source_id=pk).delete()
        removed += 1
    return {"indexed": written, "removed": removed, "total": len(seen)}


def available():
    return llm.embeddings_configured() and DocChunk.objects.filter(model=llm.embed_model()).exists()


def _cosine(a, b):
    top = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return top / size if size else 0.0


def _exact_words(query):
    """Words worth matching literally: codes and numbers, not ordinary language."""
    return {word.lower() for word in WORD.findall(query) if any(ch.isdigit() for ch in word)}


def rank(query, query_vector, chunks):
    words = _exact_words(query)
    scored = []
    for chunk in chunks:
        score = _cosine(query_vector, chunk.embedding)
        content = chunk.content.lower()
        if any(word in content for word in words):
            score += EXACT_BOOST
        scored.append((score, chunk))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored


def search(request, query, kinds=None):
    """Records matching `query` that this person may open, as the CRM shows them now."""
    query = str(query or "").strip()[:500]
    if not query:
        return {"error": "Nothing to search for."}
    if not available():
        return {"error": "Search isn't set up yet. Use crm_read instead."}
    chunks = DocChunk.objects.filter(model=llm.embed_model())
    if kinds:
        chunks = chunks.filter(source_type__in=[kind for kind in kinds if kind in DETAIL])
    vector = llm.embed([query])[0]
    results = []
    for score, chunk in rank(query, vector, chunks)[:CANDIDATES]:
        opened = dispatch.call(request, "GET", DETAIL[chunk.source_type].format(chunk.source_id))
        if not opened.ok:
            continue  # outside this person's role or store, or since deleted
        results.append({"type": chunk.source_type, "score": round(score, 3), "record": _summary(opened.data)})
        if len(results) >= TOP_RESULTS:
            break
    return {"results": results}


def _summary(data):
    data = redact.clean(data)
    if isinstance(data, dict):
        data.pop("messages", None)  # a thread can be long; read the party directly for it
    return data
