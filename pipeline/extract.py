# extract.py
import base64
import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from markitdown import MarkItDown
import anthropic

from .retry import with_retry

# ────────────────────────────── Config ──────────────────────────────

USE_LLM_FALLBACK = os.getenv("EXTRACT_USE_LLM_FALLBACK", "1") == "1"
USE_LLM_VISION = os.getenv("EXTRACT_USE_LLM_VISION", "1") == "1"

LLM_MODEL = os.getenv("EXTRACT_LLM_MODEL", "claude-sonnet-5")
LLM_VISION_MODEL = os.getenv("EXTRACT_LLM_VISION_MODEL", "claude-sonnet-5")
LLM_MAX_TOKENS = 800
LLM_MAX_INPUT_CHARS = 20000

MIN_ALPHA_WORDS = 5
MIN_TEXT_FIELD_LEN = 2
MAX_TEXT_FIELD_LEN = 300
MAX_CONTAINER_COUNT = 1000
MAX_GROSS_WEIGHT_KG = 2_000_000.0
MAX_LEGAL_SUFFIX_SEARCH = 200


# ────────────────────────────── Field spec ──────────────────────────

FIELDS = [
    "shipper", "consignee", "notify_party",
    "port_of_loading", "port_of_discharge",
    "container_count", "gross_weight_kg",
]

# Fields whose value is a party name, not a name+address block.
NAME_FIELDS = {"shipper", "consignee", "notify_party"}
NUMERIC_FIELDS = {"container_count", "gross_weight_kg"}

FIELD_ALIASES = {
    "shipper": [
        "shipper", "shipper name", "shipper name/address",
        "shipper/exporter", "shipper principal or seller",
        "shipper principal", "shipper (principal or seller)",
        "exporter", "exporter name", "consignor", "consignor name",
        "seller", "principal", "principal or seller",
    ],
    "consignee": [
        "consignee", "consignee name", "consignee name/address",
        "consignee (non-negotiable)", "consignee non negotiable",
        "consignee address",
        "to the order of", "consignee to the order of",
        "buyer", "buyer name", "receiver", "receiver name",
    ],
    "notify_party": [
        "notify party", "notify party name", "notify party address",
        "notify party name/address",
        "notify party/intermediate consignee",
        "intermediate consignee",
        "notify", "notify address",
        "also notify", "also notify party",
        "notify 1", "notify 2",
        "first notify party", "second notify party",
    ],
    "port_of_loading": [
        "port of loading", "port of loading (pol)", "port of loading pol",
        "load port", "loading port", "port of load",
        "pol", "port of departure", "departure port",
        "place of loading", "place of receipt",
        "origin port", "origin",
    ],
    "port_of_discharge": [
        "port of discharge", "port of discharge (pod)", "port of discharge pod",
        "discharge port", "port of unloading", "unloading port",
        "pod", "port of destination", "destination port",
        "final destination", "port of delivery", "delivery port",
        "place of delivery", "destination",
    ],
    "container_count": [
        "container count", "container count (total)",
        "no of containers", "no. of containers",
        "no of containers or packages", "no. of containers or packages",
        "no of containers packages", "no of containers/packages",
        "number of containers", "total containers", "total count",
        "container qty", "container quantity",
        "cntr count", "cntr qty",
        "containers", "packages",
        "no of packages", "no. of packages", "total packages",
        "quantity", "qty",
    ],
    "gross_weight_kg": [
        "gross weight", "gross weight (kg)", "gross weight kg",
        "gross weight kgs", "gross weight (kgs)",
        "gross wt", "gross wt (kgs)", "gross wt (kg)", "gross wt kg",
        "total gross weight", "total gross weight kgs",
        "total gross weight (kgs)",
        "total weight", "total weight (kg)", "total weight kg",
        "weight", "weight (kg)", "weight (kgs)",
        "g.w.", "gw", "kgs", "kg",
    ],
}

# Legal-form suffixes used to trim "NAME + ADDRESS" down to just NAME.
# Sorted longest-first so e.g. "SDN. BHD." matches before "BHD".
LEGAL_SUFFIXES = sorted([
    "SDN. BHD.", "SDN.BHD.", "SDN BHD", "SDN.BHD",
    "PTE. LTD.", "PTE.LTD.", "PTE LTD", "PTE.LTD",
    "PTY. LTD.", "PTY.LTD.", "PTY LTD", "PTY.LTD",
    "PVT. LTD.", "PVT.LTD.", "PVT LTD", "PVT.LTD",
    "CO., LTD.", "CO.,LTD.", "CO., LTD", "CO.,LTD",
    "CO. LTD.", "CO.LTD.", "CO. LTD", "CO.LTD", "CO LTD",
    "L.L.C.", "L.L.C", "LLC",
    "P.L.C.", "P.L.C", "PLC",
    "FZ-LLC", "FZ L.L.C.", "FZ LLC", "FZCO", "FZE",
    "GMBH", "AG", "SA", "S.A.", "S.A",
    "LIMITED", "LTD.", "LTD",
    "CORPORATION", "CORP.", "CORP",
    "INCORPORATED", "INC.", "INC",
], key=len, reverse=True)


# ──────────────────────────── Normalization ─────────────────────────

def _norm_label(s: str) -> str:
    # Strip any parenthetical that contains a non-ASCII character, e.g.
    # "Gross Wt (kgs) (毛重 KGS)" → "Gross Wt (kgs) ".
    s = re.sub(r"\([^)]*[^\x00-\x7f][^)]*\)", " ", s)
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


ALIASES = {f: {_norm_label(a) for a in als} for f, als in FIELD_ALIASES.items()}
ALL_ALIASES = set().union(*ALIASES.values())


def _label_matches(label: str, normalized_aliases: set) -> bool:
    if label in normalized_aliases:
        return True
    for alias in normalized_aliases:
        if not alias:
            continue
        if label.startswith(alias + " ") or alias.startswith(label + " "):
            return True
    return False


# ─────────────────────────── Rule-based parsing ─────────────────────

def _is_known_label(line: str) -> bool:
    if line.strip().startswith("|"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and _label_matches(_norm_label(cells[0]), ALL_ALIASES):
            return True
    m = re.match(r"^\s*([^:]+?)\s*[:\-\u2013]\s*", line)
    if m and _label_matches(_norm_label(m.group(1)), ALL_ALIASES):
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
    normalized_aliases = ALIASES[field]
    raw_aliases = sorted(FIELD_ALIASES[field], key=len, reverse=True)

    for i, line in enumerate(lines):
        # Markdown pipe table row
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2:
                label = _norm_label(cells[0])
                if _label_matches(label, normalized_aliases):
                    value = " | ".join([c for c in cells[1:] if c])
                    if value:
                        return value

                # "Label: value" — colon is unambiguous
        m = re.match(r"^\s*([^:]+?)\s*:\s*(.*)$", line)
        if m:
            label = _norm_label(m.group(1))
            if _label_matches(label, normalized_aliases):
                value = m.group(2).strip()
                if value:
                    return value
                return _collect_multiline(lines, i)

        # "Label - value" or "Label – value" — dash must be surrounded by
        # whitespace, so hyphens inside labels ("Non-Negotiable") aren't
        # mistaken for separators.
        m = re.match(r"^\s*(.+?)\s+[-\u2013]\s+(.*)$", line)
        if m:
            label = _norm_label(m.group(1))
            if _label_matches(label, normalized_aliases):
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
                rest = rest.lstrip(":-\u2013 ").strip()
                if rest:
                    return rest
                return _collect_multiline(lines, i)

    return None


def _clean_text(value):
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.upper() if value else None


# ──────────────────── Party-name trimming (name, not address) ───────

def _legal_suffix_end(s: str) -> Optional[int]:
    """Return index right after the LATEST legal-suffix match within the
    first MAX_LEGAL_SUFFIX_SEARCH chars, or None."""
    search = s[:MAX_LEGAL_SUFFIX_SEARCH].upper()
    best = None
    for suffix in LEGAL_SUFFIXES:
        up = suffix.upper()
        start = 0
        while True:
            idx = search.find(up, start)
            if idx == -1:
                break
            end = idx + len(up)
            if end == len(search) or not search[end].isalpha():
                if best is None or end > best:
                    best = end
            start = end
    return best


def _clean_name(raw: Optional[str]) -> Optional[str]:
    """Return just the party name, not name + address."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # Pass "same as consignee" through unchanged; caller maps it later.
    if re.search(r"\b(SAME AS|SAME TO)\s+CONSIGNEE\b", s, re.I):
        return _clean_text(s)

    # XLSX-style: "NAME | ADDRESS | …" → NAME
    if "|" in s:
        s = s.split("|", 1)[0].strip()

    # Cut at latest legal suffix within the window: "… PTE LTD 80 RAFFLES…"
    end = _legal_suffix_end(s)
    if end is not None:
        s = s[:end].rstrip(" ,.;:-\u2013")

    # Comma followed by digit → address starts: "ABC LTD, 123 MAIN ST"
    m = re.match(r"^(.+?),\s*\d", s)
    if m:
        s = m.group(1).strip()

    # Fallback: whitespace-digit boundary if at least 8 chars of name precede
    # it and no legal suffix was found: "ABC TRADING 123 MAIN ST" → ABC TRADING
    if end is None:
        m2 = re.search(r"\s(\d{1,5})(?=\s)", s)
        if m2 and m2.start() >= 8:
            s = s[:m2.start()].strip()

    return _clean_text(s)


# ─────────────────────── Numeric parsing ───────────────────────────

def _parse_number(s):
    if not s:
        return None
    s = s.strip()
    s = re.sub(r"(?<=\d)\s*(KGS?|MTS?|TONS?|LBS?)\b", "", s, flags=re.I)
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
    x_nums = re.findall(r"(\d+)\s*(?:[X×]|\\TIMES)\s*(?:20|40|45)", s, re.I)
    if x_nums:
        return str(sum(int(n) for n in x_nums))
    m = re.search(r"\b(\d+)\b", s)
    if not m:
        return None
    n = int(m.group(1))
    if n > MAX_CONTAINER_COUNT:
        return None
    return str(n)


def _parse_gross_weight_kg(value):
    if not value:
        return None
    s = value.upper()
    num = _parse_number(s)
    if num is None:
        return None
    if "TON" in s or re.search(r"\bMT\b", s):
        num *= 1000
    if num > MAX_GROSS_WEIGHT_KG:
        return None
    return str(int(num)) if num.is_integer() else str(num)


def _value_from_raw(field: str, raw) -> Optional[str]:
    """Canonicalize a raw value for the given field.
    Accepts non-string inputs (LLM JSON sometimes returns numbers)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    if field == "container_count":
        return _parse_container_count(raw)
    if field == "gross_weight_kg":
        return _parse_gross_weight_kg(raw)
    if field in NAME_FIELDS:
        return _clean_name(raw)
    return _clean_text(raw)


# ─────────────────── Rule-based extraction + confidence ─────────────

def _classify_confidence(field: str, raw: Optional[str], parsed: Optional[str]) -> str:
    if raw is None:
        return "missing"
    if parsed is None:
        return "ambiguous"
    if field not in NUMERIC_FIELDS:
        if len(parsed) < MIN_TEXT_FIELD_LEN:
            return "ambiguous"
        if len(parsed) > MAX_TEXT_FIELD_LEN:
            return "ambiguous"
        if _norm_label(parsed) in ALL_ALIASES:
            return "ambiguous"
    return "ok"


def extract_fields_from_text_rules(text: str) -> Tuple[Dict[str, Optional[str]], Dict[str, str]]:
    lines = text.splitlines()
    fields: Dict[str, Optional[str]] = {}
    confidence: Dict[str, str] = {}

    for field in FIELDS:
        raw = _extract_field_raw(lines, field)
        parsed = _value_from_raw(field, raw)
        fields[field] = parsed
        confidence[field] = _classify_confidence(field, raw, parsed)

    notify = fields.get("notify_party")
    if notify and re.search(r"\b(SAME AS|SAME TO|AS)\s+CONSIGNEE\b", notify, re.I):
        fields["notify_party"] = fields.get("consignee")
        if fields["notify_party"] is not None:
            confidence["notify_party"] = "ok"

    return fields, confidence


# ──────────────────────────── Readability check ─────────────────────

def _looks_like_garbage(text: str) -> bool:
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
- For shipper, consignee, and notify_party, return the company/person NAME
  only — do NOT include the street address, postal code, phone, or email.
- For container_count, return the total number of containers as digits only
  (e.g. "3"). This must be a JSON string, not a number.
- For gross_weight_kg, return a plain number in kilograms, digits only, no
  commas or units (e.g. "21577"). This must be a JSON string, not a number.
- For port_of_loading and port_of_discharge, return the port name as written.
- Do NOT invent values. Only extract what is present in the document.
- If a field appears in multiple places, prefer the main header block.
- If a value is spread across multiple lines, join it into one string.

Document:
{document}
"""


def _build_llm_prompt(text: str, fields_to_find: List[str]) -> str:
    field_lines = ",\n".join(f'  "{f}": "..."' for f in fields_to_find)
    return _LLM_PROMPT.format(field_lines=field_lines, document=text)


def _extract_json_object(text: str) -> Optional[str]:
    """Return the first balanced {...} substring from text, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _parse_llm_response(raw: str, fields_to_find: List[str]) -> Optional[Dict[str, Optional[str]]]:
    """Strip fences, find the outermost JSON object, parse, coerce to str-or-None."""
    raw = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).strip()

    parsed = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        snippet = _extract_json_object(raw)
        if snippet:
            try:
                parsed = json.loads(snippet)
            except json.JSONDecodeError:
                return None

    if not isinstance(parsed, dict):
        return None

    out: Dict[str, Optional[str]] = {}
    for f in fields_to_find:
        v = parsed.get(f)
        out[f] = _value_from_raw(f, None if v is None else str(v))
    return out


@with_retry(max_attempts=5, base_delay=1.5, max_delay=30.0)
def _call_llm(text: str, fields_to_find: List[str]) -> Optional[Dict[str, Optional[str]]]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — check .env or environment variables"
        )
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        messages=[{"role": "user",
                   "content": _build_llm_prompt(text, fields_to_find)}],
    )
    raw = ""
    for block in response.content:
        if hasattr(block, "text") and block.text:
            raw = block.text.strip()
            break
    return _parse_llm_response(raw, fields_to_find)


def _llm_fallback(text: str, needed_fields: List[str]) -> Dict[str, Optional[str]]:
    if not needed_fields:
        return {}
    if len(text) > LLM_MAX_INPUT_CHARS:
        text = text[:LLM_MAX_INPUT_CHARS]
    try:
        result = _call_llm(text, needed_fields)
    except Exception:
        return {}
    return result or {}


# ──────────────────────────── Vision fallback ───────────────────────

@with_retry(max_attempts=3, base_delay=2.0, max_delay=30.0)
def _call_llm_vision(pdf_bytes: bytes,
                     fields_to_find: List[str]) -> Optional[Dict[str, Optional[str]]]:
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        return None
    try:
        pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=200)
    except Exception:
        return None
    if not pages:
        return None

    buf = BytesIO()
    pages[0].save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    field_lines = ",\n".join(f'  "{f}": "..."' for f in fields_to_find)
    prompt = _LLM_PROMPT.format(field_lines=field_lines,
                                document="(the document is the attached image)")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — check .env or environment variables"
        )
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=LLM_VISION_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64",
                            "media_type": "image/png",
                            "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    raw = ""
    for block in response.content:
        if hasattr(block, "text") and block.text:
            raw = block.text.strip()
            break
    return _parse_llm_response(raw, fields_to_find)


def _llm_vision_fallback(pdf_bytes: bytes,
                         needed_fields: List[str]) -> Dict[str, Optional[str]]:
    if not needed_fields or not USE_LLM_VISION:
        return {}
    try:
        result = _call_llm_vision(pdf_bytes, needed_fields)
    except Exception:
        return {}
    return result or {}


# ──────────────────────────── Merge logic ───────────────────────────

def _merge(rules: Dict[str, Optional[str]],
           llm: Dict[str, Optional[str]],
           fields_from_llm: List[str],
           override_ambiguous: bool = True) -> Dict[str, Optional[str]]:
    """LLM fills missing fields, and (optionally) replaces ambiguous ones.
    Never overrides a rule field the extractor resolved with confidence ok."""
    merged = dict(rules)
    for f in fields_from_llm:
        llm_val = llm.get(f)
        if llm_val is None:
            continue
        if merged.get(f) is None:
            merged[f] = llm_val
        elif override_ambiguous:
            merged[f] = llm_val
    return merged


# ──────────────────────────── Attachment reading ────────────────────

def _read_xlsx_openpyxl(data: bytes) -> Optional[str]:
    """
    Read an Excel file directly with openpyxl.

    Emits one line per row in the format:
        Label: value1 | value2 | value3
    Single-cell rows become plain lines. The rule parser upstream already
    understands both `Label: value` and `Label | value | value` shapes,
    so nothing else in the pipeline needs to change.
    """
    try:
        from openpyxl import load_workbook
    except ImportError:
        return None
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception:
        return None

    lines: List[str] = []
    try:
        for ws in wb.worksheets:
            sheet_name = ws.title or "Sheet"
            lines.append(f"# Sheet: {sheet_name}")
            for row in ws.iter_rows(values_only=True):
                # Drop None and empty-string cells; keep whitespace inside values
                cells = []
                for c in row:
                    if c is None:
                        continue
                    s = str(c).strip()
                    if s:
                        cells.append(s)
                if not cells:
                    continue
                if len(cells) == 1:
                    lines.append(cells[0])
                else:
                    label = cells[0]
                    value = " | ".join(cells[1:])
                    lines.append(f"{label}: {value}")
    finally:
        try:
            wb.close()
        except Exception:
            pass

    return "\n".join(lines) if lines else None

def _read_docx_direct(data: bytes) -> Optional[str]:
    """
    Read a .docx directly with python-docx. Emits paragraphs and table rows
    in the same `Label: value` shape the rule parser expects.
    """
    try:
        from docx import Document
    except ImportError:
        return None
    try:
        doc = Document(BytesIO(data))
    except Exception:
        return None

    lines: List[str] = []

    # Paragraphs first — top-of-document info often lives here.
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            lines.append(t)

    # Tables: each row becomes "cell0: cell1 | cell2 | ..."
    for table in doc.tables:
        for row in table.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            cells = [c for c in cells if c]
            if not cells:
                continue
            if len(cells) == 1:
                lines.append(cells[0])
            else:
                lines.append(f"{cells[0]}: {' | '.join(cells[1:])}")

    return "\n".join(lines) if lines else None
    
def _read_attachment_text(data: bytes, ext: str) -> Optional[str]:
    """
    Convert an attachment to plain text.

    - .txt              → UTF-8 decode
    - .xlsx / .xlsm     → openpyxl (no markitdown)
    - .docx             → markitdown
    - .pdf              → markitdown
    - anything else     → best-effort UTF-8 decode
    """
    if not data:
        return None

    try:
        # ── Plain text ─────────────────────────────────────────────
        if ext == ".txt":
            return data.decode("utf-8", errors="replace")

        # ── Excel: openpyxl only ───────────────────────────────────
        if ext in (".xlsx", ".xlsm"):
            # A real xlsx/xlsm is a ZIP container (magic bytes PK\x03\x04).
            # If the file isn't a zip, it's misnamed — fall back to text.
            if not data.startswith(b"PK\x03\x04"):
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    return None
            return _read_xlsx_openpyxl(data)

        # ── DOCX: python-docx directly, markitdown as fallback ─────
        if ext == ".docx":
            if not data.startswith(b"PK\x03\x04"):
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    return None
            text = _read_docx_direct(data)
            if text and text.strip():
                return text
            try:
                md = MarkItDown()
                return md.convert_stream(BytesIO(data), file_extension=".docx").markdown
            except Exception:
                return None

        # ── PDF: markitdown ────────────────────────────────────────
        if ext == ".pdf":
            if not data.startswith(b"%PDF-"):
                return None
            md = MarkItDown()
            return md.convert_stream(BytesIO(data), file_extension=".pdf").markdown

        # ── Unknown: best-effort text ──────────────────────────────
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    except BaseException:
        return None


# ──────────────────────────── Public API ────────────────────────────

def extract_fields(document_text: str,
                   use_llm: Optional[bool] = None
                   ) -> Optional[Dict[str, Optional[str]]]:
    if use_llm is None:
        use_llm = USE_LLM_FALLBACK
    if not document_text or not document_text.strip():
        return None

    fields, confidence = extract_fields_from_text_rules(document_text)

    if all(v is None for v in fields.values()):
        if use_llm and not _looks_like_garbage(document_text):
            llm_result = _llm_fallback(document_text, FIELDS)
            fields = _merge(fields, llm_result, FIELDS)
        if all(v is None for v in fields.values()):
            return None
        return fields

    # Partial result: text is readable, always ask the LLM for the gaps.
    if use_llm:
        needed = [f for f in FIELDS if confidence[f] != "ok"]
        if needed:
            llm_result = _llm_fallback(document_text, needed)
            fields = _merge(fields, llm_result, needed, override_ambiguous=True)

    return fields


def extract_fields_from_attachment(inbox, att_path: str,
                                   use_llm: Optional[bool] = None
                                   ) -> Optional[Dict[str, Optional[str]]]:
    data = inbox.read_bytes(att_path)
    if not data:
        return None

    ext = Path(att_path).suffix.lower()
    text = _read_attachment_text(data, ext)

    text_readable = bool(text and text.strip() and not _looks_like_garbage(text))
    result: Optional[Dict[str, Optional[str]]] = None

    if text_readable:
        result = extract_fields(text, use_llm=use_llm)

    # PDF whose text layer failed or was incomplete → try vision on page 1.
    needs_vision = (
        ext == ".pdf"
        and USE_LLM_VISION
        and data.startswith(b"%PDF-")
        and (result is None or any(v is None for v in result.values()))
    )
    if needs_vision:
        needed = FIELDS if result is None else [f for f in FIELDS if result.get(f) is None]
        vision_result = _llm_vision_fallback(data, needed)
        if vision_result:
            if result is None:
                result = vision_result
            else:
                result = _merge(result, vision_result, needed)

    return result