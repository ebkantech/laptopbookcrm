"""
Import the real Tally/Flobiz export (Laptop_Rental_dataset.xlsx) into the
live CRM database.

Source: 92 real customers (Sundry Debtors), 250 real sales invoices
(mostly "LAPTOP ON RENT" / "Desktop On Rent" charges, Apr 2025 - Mar
2026), pre-extracted into tally_data.json (bundled next to this file)
so this command has no dependency on openpyxl or the original
spreadsheet at runtime.

What it creates, per the confirmed plan:
  1. parties.Party -- one per real customer, type="Rental" (so every
     one of them is eligible for the customer portal / OTP link
     feature), customer_classification="individual".
  2. catalog.Product / Variant -- one per distinct item that actually
     appears on an invoice line (from the Tally Item Master + the
     structured line-item descriptions), plus one catch-all
     "Rental Charges (Tally import)" variant for the ~85% of invoices
     that only recorded a total with no structured line-item
     breakdown in Tally.
  3. sales.Invoice / InvoiceItem -- one Invoice per Tally voucher
     (250 total), with real line items where Tally recorded them,
     and a single catch-all line (qty=1, price=invoice total) where
     it didn't. status is set to "Paid" for all of them, since this
     is closed historical billing history, not open receivables --
     change that in bulk from the Invoices screen if that assumption
     is wrong for your books.
  4. rentals.Rental -- one agreement per customer who has invoice
     history (33 of them), summarizing their billing into a
     monthly_fee (total billed / months active) and a tenure --
     Tally has no explicit "agreement" concept, so these two numbers
     are ESTIMATES from the invoice history, not real contract
     terms. Flagged in each Rental's `terms` field so it's obvious in
     the UI which records are estimated.

Idempotent: safe to re-run. Every create uses update_or_create keyed on
a stable natural key (Party name+phone, Invoice code, Rental
agreement_code), so re-running after fixing a mapping just updates the
same rows instead of duplicating them.

Usage:
    python manage.py import_tally_data
    python manage.py import_tally_data --dry-run   # report counts only, write nothing
"""
import json
import os
from collections import defaultdict
from datetime import datetime, date

from django.core.management.base import BaseCommand
from django.db import transaction

from parties.models import Party
from catalog.models import Product, Variant, StockPoint
from sales.models import Invoice, InvoiceItem
from rentals.models import Rental

DATA_FILE = os.path.join(os.path.dirname(__file__), "tally_data", "tally_data.json")

DEFAULT_STOCK_POINT_SLUG = "kb"
DEFAULT_STOCK_POINT_NAME = "Karol Bagh Store"


def parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


class Command(BaseCommand):
    help = "Import the real Tally export (parties, invoices, rental agreements) into the live CRM."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what would be created without writing anything.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]

        if not os.path.exists(DATA_FILE):
            self.stderr.write(self.style.ERROR(f"Data file not found: {DATA_FILE}"))
            return

        with open(DATA_FILE) as f:
            data = json.load(f)

        parties_data = data["parties"]
        invoices_data = data["invoices"]
        items_master = data["items_master"]
        rental_summary = data["rental_summary"]

        self.stdout.write(f"Loaded: {len(parties_data)} parties, {len(invoices_data)} invoices, "
                           f"{len(items_master)} catalogue items, {len(rental_summary)} rental summaries.")

        if dry:
            self.stdout.write(self.style.WARNING("--dry-run: no changes will be written."))

        with transaction.atomic():
            sp = self._get_stock_point(dry)
            party_lookup = self._import_parties(parties_data, dry)
            variant_lookup, catch_all_variant = self._import_catalogue(items_master, invoices_data, dry)
            invoice_count, item_count = self._import_invoices(
                invoices_data, party_lookup, variant_lookup, catch_all_variant, sp, dry
            )
            rental_count = self._import_rentals(rental_summary, party_lookup, invoices_data, dry)

            if dry:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f"Done{' (dry run, nothing written)' if dry else ''}: "
            f"{len(party_lookup)} parties, {invoice_count} invoices ({item_count} line items), "
            f"{rental_count} rental agreements."
        ))

    # ------------------------------------------------------------------

    def _get_stock_point(self, dry):
        sp, created = StockPoint.objects.update_or_create(
            slug=DEFAULT_STOCK_POINT_SLUG,
            defaults={"name": DEFAULT_STOCK_POINT_NAME, "kind": StockPoint.SHOP},
        )
        if created:
            self.stdout.write(f"Created stock point '{sp.name}' for imported invoices.")
        return sp

    def _import_parties(self, parties_data, dry):
        lookup = {}
        for p in parties_data:
            party, _ = Party.objects.update_or_create(
                name=p["name"],
                defaults={
                    "type": Party.RENTAL,
                    "phone": p["phone"] or "0000000000",
                    "email": p["email"],
                    "gstin": p["gstin"],
                    "city": p["city"],
                    "joined": parse_date(p["joined"]),
                    "customer_classification": Party.INDIVIDUAL,
                },
            )
            lookup[p["name"]] = party
        self.stdout.write(f"Parties: {len(lookup)} (type=Rental).")
        return lookup

    def _import_catalogue(self, items_master, invoices_data, dry):
        """One Product+Variant per distinct (item, description) pair that
        actually appears on a structured invoice line, plus every Item
        Master row not otherwise covered, plus a single catch-all variant
        for invoices with no structured breakdown."""
        variant_lookup = {}
        seq = 9000

        def make_variant(brand, model_name, sell_price):
            nonlocal seq
            seq += 1
            product, _ = Product.objects.update_or_create(
                product_code=f"VC-TLY-{seq:04d}",
                defaults={"brand": brand, "model_name": model_name, "processor": "", "hsn": "", "condition": "Used"},
            )
            variant, _ = Variant.objects.update_or_create(
                code=f"TLY-SKU-{seq:04d}",
                defaults={"product": product, "spec": "Imported", "mrp": max(sell_price, 1) + 1000,
                          "sell_price": max(sell_price, 1), "cost": round(max(sell_price, 1) * 0.7)},
            )
            return variant

        # distinct structured line-item descriptions
        seen = set()
        for inv in invoices_data:
            for li in inv["items"]:
                key = (li["item"], li["description"])
                if key in seen or not li["item"]:
                    continue
                seen.add(key)
                label = li["description"] or li["item"]
                brand = label.split()[0] if label else "Generic"
                variant_lookup[key] = make_variant(brand, label, li["rate"] or 1)

        # item master rows not already covered by a structured description
        covered_items = {k[0] for k in variant_lookup}
        for im in items_master:
            if im["name"] in covered_items:
                continue
            key = (im["name"], "")
            if key in variant_lookup:
                continue
            variant_lookup[key] = make_variant("Generic", im["name"], im["price"] or 1)

        # catch-all for the ~200 invoices with only a total, no line items
        catch_all = make_variant("Tally Import", "Rental Charges (unitemized)", 1)

        self.stdout.write(f"Catalogue: {len(variant_lookup)} imported SKUs + 1 catch-all SKU.")
        return variant_lookup, catch_all

    def _import_invoices(self, invoices_data, party_lookup, variant_lookup, catch_all_variant, sp, dry):
        n_inv = 0
        n_items = 0
        for inv in invoices_data:
            party = party_lookup.get(inv["party"])
            if not party:
                continue
            code = f"TLY-{inv['voucher_no']}"
            invoice, _ = Invoice.objects.update_or_create(
                code=code,
                defaults={
                    "party": party,
                    "stock_point": sp,
                    "date": parse_date(inv["date"]),
                    "status": Invoice.PAID,
                },
            )
            invoice.items.all().delete()
            lines = inv["items"]
            if lines:
                for li in lines:
                    key = (li["item"], li["description"])
                    variant = variant_lookup.get(key) or variant_lookup.get((li["item"], "")) or catch_all_variant
                    InvoiceItem.objects.create(invoice=invoice, variant=variant, qty=li["qty"] or 1, price=li["rate"] or li["amount"] or 1)
                    n_items += 1
            else:
                InvoiceItem.objects.create(invoice=invoice, variant=catch_all_variant, qty=1, price=max(inv["total"], 1))
                n_items += 1
            n_inv += 1
        self.stdout.write(f"Invoices: {n_inv} ({n_items} line items).")
        return n_inv, n_items

    def _import_rentals(self, rental_summary, party_lookup, invoices_data, dry):
        DATASET_END = date(2026, 3, 28)
        n = 0
        for rs in rental_summary:
            party = party_lookup.get(rs["party"])
            if not party:
                continue
            first = parse_date(rs["first_invoice"])
            last = parse_date(rs["last_invoice"])
            months_span = max(1, (last.year - first.year) * 12 + (last.month - first.month) + 1) if first and last else 1
            monthly_fee = max(1, round(rs["total_sales"] / months_span))
            tenure_months = max(months_span, rs["invoices"])
            is_active = last and (DATASET_END - last).days <= 60
            agreement_code = f"TLY-RENT-{n + 1:04d}"
            Rental.objects.update_or_create(
                agreement_code=agreement_code,
                defaults={
                    "party": party,
                    "product_label": "Laptop on rent (imported)",
                    "monthly_fee": monthly_fee,
                    "start": first,
                    "tenure_months": tenure_months,
                    "months_paid": rs["invoices"],
                    "last_payment": last,
                    "status": Rental.ACTIVE if is_active else Rental.CLOSED,
                    "terms": (
                        "Imported from Tally billing history on "
                        f"{date.today().isoformat()}. monthly_fee and tenure_months are "
                        "ESTIMATES derived from real invoice totals/dates -- Tally had no "
                        "explicit agreement record for this customer."
                    ),
                },
            )
            n += 1
        self.stdout.write(f"Rental agreements: {n} (estimated monthly_fee/tenure -- see each record's terms).")
        return n
