import anthropic
import json
import re
from .retry import with_retry

client = anthropic.Anthropic()

EXTRACT_PROMPT = """Extract these 7 fields from the shipping document below.
Different documents may label the same field differently (e.g. "Load Port" = port_of_loading).
Return ONLY valid JSON, no other text, in exactly this shape:

{
  "shipper": "...",
  "consignee": "...",
  "notify_party": "...",
  "port_of_loading": "...",
  "port_of_discharge": "...",
  "container_count": "...",
  "gross_weight_kg": <number, digits only, no commas or units>
}

If a field is genuinely missing from the document, use null for that field.

Document:
"""

@with_retry()
def extract_fields(document_text: str):
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=500,
        messages=[{"role": "user", "content": EXTRACT_PROMPT + document_text}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None