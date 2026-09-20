
import re
from difflib import SequenceMatcher
 
FIELDS = ["shipper", "consignee", "notify_party", "port_of_loading",
          "port_of_discharge", "container_count", "gross_weight_kg"]
 
NUMERIC_FIELDS = {"container_count", "gross_weight_kg"}
PORT_FIELDS = {"port_of_loading", "port_of_discharge"}
ENTITY_FIELDS = {"shipper", "consignee", "notify_party"}
 
GROSS_WEIGHT_TOLERANCE_PCT = 0.005  # 0.5% — absorbs rounding, not real discrepancies
PORT_FUZZY_THRESHOLD = 0.60         # loose: "PORT KLANG" vs "PORT KLANG (WESTPORT)"
ENTITY_FUZZY_THRESHOLD = 0.90       # strict: real different companies must NOT collapse together
 
# ---------------------------------------------------------------------------
# Entity pool from the provided synonym library. Adjust the import path/name
# to match wherever it actually lives in your project (e.g. `entities.py`,
# `synonyms.py`, `data.entity_pools`, etc).
# Falls back to a small built-in alias table if the pool isn't importable,
# so this module still works standalone.
# ---------------------------------------------------------------------------
try:
    from .pools import LOADING_PORTS, DISCHARGE_PORTS, SHIPPERS, CUSTOMERS
    _ALL_PORTS = LOADING_PORTS + DISCHARGE_PORTS  # (name, country, code) triples
    _ALL_ENTITY_NAMES = [s["name"] for s in SHIPPERS] + [c["name"] for c in CUSTOMERS]
    _HAS_ENTITY_POOL = True
except ImportError:
    _ALL_PORTS = []
    _ALL_ENTITY_NAMES = []
    _HAS_ENTITY_POOL = False
 
    # Minimal fallback so shipper/consignee comparisons don't regress to
    # pure exact-match if the pool isn't available in this environment.
    COMPANY_ALIASES = {
        "CO.,LTD": "COMPANY LIMITED", "CO., LTD.": "COMPANY LIMITED", "CO LTD": "COMPANY LIMITED",
        "CO.": "COMPANY", "LTD.": "LIMITED", "CORP.": "CORPORATION",
        "INC.": "INCORPORATED", "PTE.": "PRIVATE",
    }
    _ALIAS_LOOKUP = {
        a.replace(".", "").replace(",", ""): c.replace(".", "").replace(",", "")
        for a, c in COMPANY_ALIASES.items()
    }
 
 
# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
 
def normalize_text(value):
    if value is None:
        return None
    text = str(value).strip().upper()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[.,]", "", text)
    if not _HAS_ENTITY_POOL:
        tokens = [_ALIAS_LOOKUP.get(tok, tok) for tok in text.split(" ")]
        text = " ".join(tokens)
    return text
 
 
def normalize_number(value):
    """Handles '3', 3, '3 containers', '22,000', 22000.0, etc."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    return float(cleaned) if cleaned else None
 
 
def _best_fuzzy_match(text, candidates):
    """Returns (best_candidate, best_ratio) comparing normalized text to a list of raw candidate strings."""
    best_candidate, best_ratio = None, 0.0
    for candidate in candidates:
        ratio = SequenceMatcher(None, text, normalize_text(candidate)).ratio()
        if ratio > best_ratio:
            best_candidate, best_ratio = candidate, ratio
    return best_candidate, best_ratio
 
 
# ---------------------------------------------------------------------------
# Canonicalization using the entity pool
# ---------------------------------------------------------------------------
 
def canonical_port_code(value):
    """
    Maps a port value (full name, partial name, or UN/LOCODE) to its
    canonical code from the entity pool, e.g.
    'PORT KLANG (WESTPORT)' -> 'MYPKG', 'MYPKG' -> 'MYPKG'.
    Falls back to normalized text if no pool entry matches closely enough.
    """
    if value is None:
        return None
    text = normalize_text(value)
 
    if not _HAS_ENTITY_POOL:
        return text
 
    # Exact match on code
    for name, country, code in _ALL_PORTS:
        if text == code.upper():
            return code
 
    # Exact match on full display name
    for name, country, code in _ALL_PORTS:
        if text == normalize_text(name):
            return code
 
    # Fuzzy match on display name (handles partial names like "PORT KLANG")
    best_code, best_ratio = None, 0.0
    for name, country, code in _ALL_PORTS:
        ratio = SequenceMatcher(None, text, normalize_text(name)).ratio()
        if ratio > best_ratio:
            best_ratio, best_code = ratio, code
 
    return best_code if best_ratio >= PORT_FUZZY_THRESHOLD else text
 
 
def canonical_entity_name(value):
    """
    Maps a shipper/consignee/notify_party value to its canonical name from
    the entity pool (SHIPPERS + CUSTOMERS), if a close-enough match exists.
    Falls back to normalized text for entities outside the known pool
    (e.g. a genuinely new counterparty not in the synthetic dataset).
    """
    if value is None:
        return None
    text = normalize_text(value)
 
    if not _HAS_ENTITY_POOL:
        return text
 
    best_name, best_ratio = _best_fuzzy_match(text, _ALL_ENTITY_NAMES)
    if best_ratio >= ENTITY_FUZZY_THRESHOLD:
        return normalize_text(best_name)
    return text  # not a known entity — compare on normalized raw text
 
 
# ---------------------------------------------------------------------------
# Field comparison
# ---------------------------------------------------------------------------
 
def values_match(field, si_val, bl_val):
    if field in NUMERIC_FIELDS:
        a, b = normalize_number(si_val), normalize_number(bl_val)
        if a is None or b is None:
            return a == b
        if field == "gross_weight_kg":
            allowed = GROSS_WEIGHT_TOLERANCE_PCT * max(abs(a), abs(b))
            return abs(a - b) <= allowed
        return a == b  # container_count: exact, no tolerance
 
    if field in PORT_FIELDS:
        return canonical_port_code(si_val) == canonical_port_code(bl_val)
 
    if field in ENTITY_FIELDS:
        return canonical_entity_name(si_val) == canonical_entity_name(bl_val)
 
    return normalize_text(si_val) == normalize_text(bl_val)
 
 
def compare_documents(si: dict, bl: dict) -> dict:
    """
    Returns:
    {
      "mismatched_fields": [...],
      "differences": {field: {"si": value, "bl": value}, ...},
      "message": "No mismatch detected" | None
    }
    """
    differences = {}
    for field in FIELDS:
        si_val, bl_val = si.get(field), bl.get(field)
        if not values_match(field, si_val, bl_val):
            differences[field] = {"si": si_val, "bl": bl_val}
 
    mismatched_fields = list(differences.keys())
    message = "No mismatch detected" if not mismatched_fields else None
 
    return {
        "mismatched_fields": mismatched_fields,
        "differences": differences,
        "message": message,
    }
 


















