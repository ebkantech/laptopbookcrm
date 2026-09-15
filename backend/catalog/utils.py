import re


def next_code(prefix: str, model, field: str = "code") -> str:
    """
    Auto-generate the next sequential internal code for a model that
    has no barcode/HSN of its own -- e.g. VC-LAP-0013, VC-SKU-0042.
    Scans existing codes with this prefix and picks one past the
    highest number found, so it's safe even if rows were deleted.
    """
    max_num = 0
    qs = model.objects.filter(**{f"{field}__startswith": f"{prefix}-"}).values_list(field, flat=True)
    for value in qs:
        m = re.search(r"(\d+)$", value or "")
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"{prefix}-{max_num + 1:04d}"
