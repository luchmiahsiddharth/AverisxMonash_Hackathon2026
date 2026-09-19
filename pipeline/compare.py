"""Shipping instruction and bill of lading comparison stage."""

FIELDS = (
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
)


def compare_documents(si, bl):
    """Compare normalized document dictionaries by the seven scoring fields."""
    mismatches = [field for field in FIELDS if si.get(field) != bl.get(field)]
    return {
        "status": "OK" if not mismatches else "MISMATCH",
        "has_defect": bool(mismatches),
        "defect_fields": mismatches,
    }