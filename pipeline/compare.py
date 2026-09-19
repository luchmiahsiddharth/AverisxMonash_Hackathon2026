FIELDS = ["shipper", "consignee", "notify_party", "port_of_loading",
          "port_of_discharge", "container_count", "gross_weight_kg"]

def normalize(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().upper()
    return value

def compare_documents(si: dict, bl: dict) -> list:
    mismatches = []
    for field in FIELDS:
        if normalize(si.get(field)) != normalize(bl.get(field)):
            mismatches.append(field)
    return mismatches