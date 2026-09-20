# extract.py
import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from markitdown import MarkItDown
import anthropic

from .retry import with_retry

# ────────────────────────────── Config ──────────────────────────────

# Master switch — set EXTRACT_USE_LLM_FALLBACK=0 to disable the LLM path.
USE_LLM_FALLBACK = os.getenv("EXTRACT_USE_LLM_FALLBACK", "1") == "1"

LLM_MODEL = "claude-sonnet-5"
LLM_MAX_TOKENS = 500

# Minimum number of real alphabetic words before we consider text "readable".
# Below this, we treat the document as garbage (scan noise, empty, etc.) and
# skip the LLM — sending garbage just wastes tokens.
MIN_ALPHA_WORDS = 5

# Text fields shorter than this are treated as suspicious.
MIN_TEXT_FIELD_LEN = 2


# ────────────────────────────── Field spec ──────────────────────────

FIELDS = [
    "shipper", "consignee", "notify_party",
    "port_of_loading", "port_of_discharge",
    "container_count", "gross_weight_kg",
]

FIELD_ALIASES = {
    "shipper": [
        "shipper", "shipper name", "exporter", "consignor",
        "shipper/exporter", "shipper principal or seller",
        "shipper name/address",
    ],
    "consignee": [
        "consignee", "consignee name", "buyer", "receiver",
        "consignee non negotiable", "consignee name/address",
    ],
    "notify_party": [
        "notify party", "notify", "notify address",
        "notify party name", "notify party address",
    ],
    "port_of_loading": [
        "port of loading", "load port", "pol", "port of departure",
        "departure port", "loading port", "port of load",
        "port of loading pol",
    ],
    "port_of_discharge": [
        "port of discharge", "discharge port", "pod",
        "port of destination", "destination port", "final destination",
        "delivery port", "port of delivery",
    ],
    "container_count": [
        "container count", "containers", "no of containers",
        "number of containers", "total containers", "container qty",
        "cntr count", "quantity", "qty", "container quantity",
        "no of containers or packages", "no of containers packages",
        "no of containers/packages",
    ],
    "gross_weight_kg": [
        "gross weight", "gross wt", "gross weight kg",
        "gross weight kgs", "gross weight (kg)", "gross wt (kgs)",
        "total gross weight", "total gross weight kgs",
        "total weight", "weight", "g.w.", "gw", "kgs", "kg",
    ],
}

NUMERIC_FIELDS = {"container_count", "gross_weight_kg"}


# ──────────────────────────── Normalization ─────────────────────────

def _norm_label(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


ALIASES = {f: {_norm_label(a) for a in als} for f, als in FIELD_ALIASES.items()}
ALL_ALIASES = set().union(*ALIASES.values())


# ─────────────────────────── Rule-based parsing ─────────────────────

def _is_known_label(line: str) -> bool:
    if line.strip().startswith("|"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and _norm_label(cells[0]) in ALL_ALIASES:
            return True
    m = re.match(r"^\s*([^:]+?)\s*[:\-]\s*", line)
    if m and _norm_label(m.group(1)) in ALL_ALIASES:
        return True
    for aliases in FIELD_ALIASES.values():
        for alias in aliases:
            if re.match(rf"^\s*{re.escape(alias)}\b", line, re.I):
                return True
    return False


def _collect_multiline(lines, start_idx):
    parts = []
    for line in lines[start_idx + 1:]:
        if not line.strip():
            break
        if _is_known_label(line):
            break
        parts.append(line.strip())
    return " ".join(parts) if parts else None


def _extract_field_raw(lines, field) -> Optional[str]:
    """Return the raw string value for a field, or None if not found."""
    normalized_aliases = ALIASES[field]
    raw_aliases = sorted(FIELD_ALIASES[field], key=len, reverse=True)

    for i, line in enumerate(lines):
        # Markdown pipe table row
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2:
                label = _norm_label(cells[0])
                if label in normalized_aliases:
                    value = " | ".join([c for c in cells[1:] if c])
                    if value:
                        return value

        # "Label: value" or "Label - value"
        m = re.match(r"^\s*([^:]+?)\s*[:\-]\s*(.*)$", line)
        if m:
            label = _norm_label(m.group(1))
            if label in normalized_aliases:
                value = m.group(2).strip()
                if value:
                    return value
                return _collect_multiline(lines, i)

        # "Label          value" or "Label\tvalue"
        for alias in raw_aliases:
            m2 = re.match(rf"^\s*{re.escape(alias)}\s{{2,}}(.*)$", line, re.I)
            if not m2:
                m2 = re.match(rf"^\s*{re.escape(alias)}\t+(.*)$", line, re.I)
            if m2:
                value = m2.group(1).strip()
                if value:
                    return value
                return _collect_multiline(lines, i)

        # PDF-style: "Shipper (Principal or Seller) APRIL FINE PAPER..."
        for alias in raw_aliases:
            m3 = re.match(rf"^\s*{re.escape(alias)}\b(.*)$", line, re.I)
            if m3:
                rest = m3.group(1).strip()
                rest = re.sub(r"^\([^)]*\)\s*", "", rest)
                rest = rest.lstrip(":- ").strip()
                if rest:
                    return rest
                # Value is on the next line(s)
                return _collect_multiline(lines, i)

    return None


def _clean_text(value):
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value.upper() if value else None


def _parse_number(s):
    if not s:
        return None
    s = s.strip()
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if re.search(r",\d{3}\b", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def _parse_container_count(value):
    if not value:
        return None
    s = value.upper().replace(",", "")
    # "1 x 40'HC", "15 x 20'GP", "4 \times 40^{\circ} HC"
    x_nums = re.findall(r"(\d+)\s*(?:[X×]|\\TIMES)\s*(?:20|40|45)", s, re.I)
    if x_nums:
        return str(sum(int(n) for n in x_nums))
    m = re.search(r"\b(\d+)\b", s)
    return str(int(m.group(1))) if m else None


def _parse_gross_weight_kg(value):
    if not value:
        return None
    s = value.upper()
    num = _parse_number(s)
    if num is None:
        return None
    if "TON" in s or "MT" in s:
        num *= 1000
    return str(int(num)) if num.is_integer() else str(num)


def _value_from_raw(field: str, raw: Optional[str]) -> Optional[str]:
    """Turn a raw string into a canonical value for the field."""
    if field == "container_count":
        return _parse_container_count(raw)
    if field == "gross_weight_kg":
        return _parse_gross_weight_kg(raw)
    return _clean_text(raw)


# ─────────────────── Rule-based extraction + confidence ─────────────

def _classify_confidence(field: str, raw: Optional[str], parsed: Optional[str]) -> str:
    """
    Returns one of:
      "ok"        — value found and cleanly parsed
      "ambiguous" — raw value present, but did not produce a valid parse
      "missing"   — no raw value found at all
    """
    if raw is None:
        return "missing"
    if parsed is None:
        return "ambiguous"
    if field not in NUMERIC_FIELDS and len(parsed) < MIN_TEXT_FIELD_LEN:
        return "ambiguous"
    if field not in NUMERIC_FIELDS and _norm_label(parsed) in ALL_ALIASES:
        return "ambiguous"
    return "ok"


def extract_fields_from_text_rules(text: str) -> Tuple[Dict[str, Optional[str]], Dict[str, str]]:
    """
    Pure rule-based pass.

    Returns:
      fields     — dict of the 7 fields (None where not resolved)
      confidence — dict of "ok" | "ambiguous" | "missing" per field
    """
    lines = text.splitlines()
    fields: Dict[str, Optional[str]] = {}
    confidence: Dict[str, str] = {}

    for field in FIELDS:
        raw = _extract_field_raw(lines, field)
        parsed = _value_from_raw(field, raw)
        fields[field] = parsed
        confidence[field] = _classify_confidence(field, raw, parsed)

    # Special case: "notify party: same as consignee"
    notify = fields.get("notify_party")
    if notify and re.search(r"\b(SAME AS|SAME TO|AS)\s+CONSIGNEE\b", notify, re.I):
        fields["notify_party"] = fields.get("consignee")
        if fields["notify_party"] is not None:
            confidence["notify_party"] = "ok"

    return fields, confidence


# ──────────────────────────── Readability check ─────────────────────

def _looks_like_garbage(text: str) -> bool:
    """
    Scan-noise detector. True if the text has almost no real words.
    Used to skip the LLM on scanned/image PDFs whose text layer is junk.
    """
    if not text or not text.strip():
        return True
    alpha_words = re.findall(r"[A-Za-z]{3,}", text)
    return len(alpha_words) < MIN_ALPHA_WORDS


# ──────────────────────────── LLM fallback ──────────────────────────

_LLM_PROMPT = """You are extracting shipment fields from a shipping document.

Return ONLY valid JSON, no other text, in exactly this shape:
{{
{field_lines}
}}

Rules:
- If a field is genuinely missing from the document, use null for that field.
- For container_count, return the total number of containers as digits only (e.g. "3").
- For gross_weight_kg, return a plain number in kilograms, digits only, no commas or units.
- For all other fields, return the value as a short string.
- Do NOT invent values. Only extract what is present in the document.

Document:
{document}
"""


def _build_llm_prompt(text: str, fields_to_find: List[str]) -> str:
    field_lines = ",\n".join(f'  "{f}": "..."' for f in fields_to_find)
    return _LLM_PROMPT.format(field_lines=field_lines, document=text)


@with_retry()
def _call_llm(text: str, fields_to_find: List[str]) -> Optional[Dict[str, Optional[str]]]:
    """Ask the LLM for only the specified fields. Returns dict or None."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        messages=[{"role": "user",
                   "content": _build_llm_prompt(text, fields_to_find)}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    # Keep only requested fields, and run values through the same canonical
    # parsers so the LLM output is format-identical to the rule-based output.
    out: Dict[str, Optional[str]] = {}
    for f in fields_to_find:
        out[f] = _value_from_raw(f, parsed.get(f))
    return out


def _llm_fallback(text: str, needed_fields: List[str]) -> Dict[str, Optional[str]]:
    """Safe wrapper around _call_llm. Never raises."""
    if not needed_fields:
        return {}
    try:
        result = _call_llm(text, needed_fields)
    except Exception:
        return {}
    return result or {}


# ──────────────────────────── Merge logic ───────────────────────────

def _merge(rules: Dict[str, Optional[str]],
           llm: Dict[str, Optional[str]],
           fields_from_llm: List[str]) -> Dict[str, Optional[str]]:
    """Only let the LLM fill fields it was asked about, and only if rules didn't."""
    merged = dict(rules)
    for f in fields_from_llm:
        if merged.get(f) is None and llm.get(f) is not None:
            merged[f] = llm[f]
    return merged


# ──────────────────────────── Attachment reading ────────────────────

def _read_attachment_text(data: bytes, ext: str) -> Optional[str]:
    """Get plain text out of an attachment, using the cheapest reliable path."""
    if not data:
        return None

    try:
        # ── Plain text: decode directly, no markitdown ─────────────
        if ext == ".txt":
            return data.decode("utf-8", errors="replace")

        # ── XLSX / DOCX are zips: verify and use markitdown ────────
        if ext in (".xlsx", ".xlsm", ".docx"):
            if not data.startswith(b"PK\x03\x04"):
                # mislabelled or corrupt → try decoding as text
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    return None
            md = MarkItDown()
            return md.convert_stream(BytesIO(data), file_extension=ext).markdown

        # ── PDF: verify magic bytes, use markitdown ────────────────
        if ext == ".pdf":
            if not data.startswith(b"%PDF-"):
                return None  # corrupt / fake PDF → escalate as unreadable
            md = MarkItDown()
            return md.convert_stream(BytesIO(data), file_extension=".pdf").markdown

        # ── Unknown extension: best-effort decode ──────────────────
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    except BaseException:
        # markitdown can raise a wide family of exceptions from
        # underlying libs (pdfminer, python-docx, openpyxl, …).
        # Any failure here means "could not read this attachment".
        return None


# ──────────────────────────── Public API ────────────────────────────

def extract_fields(document_text: str,
                   use_llm: Optional[bool] = None) -> Optional[Dict[str, Optional[str]]]:
    """
    Extract the 7 shipping fields from already-converted text.

    Runs rules first, then calls the LLM only for fields rules could not
    resolve cleanly, and only if the text is not garbage.

    Returns None if the document is completely unreadable.
    """
    if use_llm is None:
        use_llm = USE_LLM_FALLBACK

    if not document_text or not document_text.strip():
        return None

    # 1) Rules first
    fields, confidence = extract_fields_from_text_rules(document_text)

    # 2) Nothing resolved at all → unreadable
    if all(v is None for v in fields.values()):
        if use_llm and not _looks_like_garbage(document_text):
            llm_result = _llm_fallback(document_text, FIELDS)
            fields = _merge(fields, llm_result, FIELDS)
        if all(v is None for v in fields.values()):
            return None
        return fields

    # 3) Partial result → ask LLM only for the missing/ambiguous fields
    if use_llm and not _looks_like_garbage(document_text):
        needed = [f for f in FIELDS if confidence[f] != "ok"]
        if needed:
            llm_result = _llm_fallback(document_text, needed)
            fields = _merge(fields, llm_result, needed)

    return fields


def extract_fields_from_attachment(inbox, att_path: str,
                                   use_llm: Optional[bool] = None
                                   ) -> Optional[Dict[str, Optional[str]]]:
    """
    Read ANY supported attachment (TXT, PDF, XLSX, DOCX, …), convert to
    text, then run the hybrid extractor. Never raises — returns None for
    unreadable files so the caller can escalate to NEEDS_REVIEW.
    """
    data = inbox.read_bytes(att_path)
    if not data:
        return None

    ext = Path(att_path).suffix.lower()
    text = _read_attachment_text(data, ext)

    if not text or not text.strip():
        return None

    return extract_fields(text, use_llm=use_llm)