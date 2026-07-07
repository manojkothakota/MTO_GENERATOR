"""
AI pipeline: preprocess -> extract (Gemini or Groq vision) -> validate -> derive -> summarize.

Design (see README for full discussion):
1. Pre-process: if the upload is a PDF, render its first page to a PNG
   (multi-page PDFs -> first sheet only, documented limitation).
2. Extract: send the image to the configured vision provider (Gemini or
   Groq) with a strict JSON-schema prompt describing the MTO structure
   from Section 2.2/3.4 of the brief.
3. Validate: parse the provider's JSON through Pydantic MTOItem/DrawingMeta
   models; malformed output is treated as an extraction failure and
   we fall back to the mock MTO (never crash).
4. Derive: if the model didn't already output GASKET/BOLT rows, add
   one gasket + one bolt set per flanged joint (flange count), per
   the domain convention.
5. Serve: compute summary totals and return.

Provider selection (env-driven, see .env.example):
- AI_PROVIDER=gemini | groq | mock  (explicit override)
- If unset: GROQ_API_KEY present -> groq; else GEMINI_API_KEY present -> gemini; else mock.
"""
import io
import json
import os
import re
from typing import Optional

from app.models import MTOResult, MTOItem, DrawingMeta, Summary, Category, Unit
from app.mock_data import build_mock_mto

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# meta-llama/llama-4-scout-17b-16e-instruct supports vision + JSON mode on Groq
# (see https://console.groq.com/docs/vision). qwen/qwen3.6-27b is the alternative.
GROQ_MODEL = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_MAX_B64_BYTES = 4 * 1024 * 1024  # Groq's hard limit for base64-encoded images

EXTRACTION_PROMPT = """You are an expert piping engineer reading a piping ISOMETRIC drawing
(a 2-D fabrication drawing on isometric axes, not to scale; see standard industry conventions:
ASME B31.3, B16.9, B16.5, B16.11, B16.20).

Extract a complete Material Take-Off (MTO) from the attached drawing image.

Rules:
- PIPE is quantified by total cut length in metres (unit="M"). All other categories are
  quantified by count (unit="EA"), except bolts which are counted in sets (unit="SET").
- Categories allowed: PIPE, FITTING, FLANGE, VALVE, GASKET, BOLT, SUPPORT.
- If gaskets/stud-bolt sets are not explicitly drawn as symbols, DERIVE them: emit one
  GASKET row and one BOLT row with quantity equal to the number of flanged joints you
  detect (each flange-to-flange or flange-to-valve connection = one joint).
- Use real ASME/ASTM vocabulary in descriptions and material_spec where the drawing implies it
  (e.g. ASTM A106 Gr.B for CS seamless pipe, A234 WPB for CS BW fittings, A105 for CS flanges,
  A312 TP316L / A182 F316L for stainless).
- Read the title block / line number / BOM table if present for drawing_meta.
- If you cannot confidently read a field, leave it null rather than guessing wildly, and give
  each item a confidence score between 0 and 1 reflecting how sure you are.
- Return ONLY valid JSON matching exactly this schema, no markdown fences, no prose:

{
  "drawing_meta": {
    "drawing_no": string|null, "revision": string|null, "line_number": string|null,
    "nps": string|null, "material_class": string|null, "service": string|null
  },
  "items": [
    {
      "item_no": integer, "category": "PIPE|FITTING|FLANGE|VALVE|GASKET|BOLT|SUPPORT",
      "description": string, "size_nps": string, "schedule_rating": string|null,
      "material_spec": string|null, "end_type": "BW|SW|THD|FLGD"|null,
      "quantity": number, "unit": "M|EA|SET", "length_m": number|null,
      "confidence": number, "remarks": string|null
    }
  ]
}
"""


def pdf_first_page_to_png(file_bytes: bytes) -> bytes:
    """Render page 1 of a PDF to PNG bytes using PyMuPDF."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=200)
    return pix.tobytes("png")


def preprocess(file_bytes: bytes, content_type: str) -> bytes:
    """Return a PNG/JPEG-ready image byte string for vision input."""
    if content_type == "application/pdf":
        return pdf_first_page_to_png(file_bytes)
    return file_bytes  # already an image


def compress_for_groq(image_bytes: bytes) -> bytes:
    """
    Downscale/recompress an image so its base64 form stays under Groq's
    4MB request limit. No-op if already small enough.
    """
    if len(image_bytes) * 4 / 3 < GROQ_MAX_B64_BYTES:  # rough base64 overhead
        return image_bytes

    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    quality = 85
    max_dim = 2200
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)))

    while quality >= 40:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if len(buf.getvalue()) * 4 / 3 < GROQ_MAX_B64_BYTES:
            return buf.getvalue()
        quality -= 15
    return buf.getvalue()  # best effort even if still slightly over


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def _derive_joint_consumables(items: list[MTOItem]) -> list[MTOItem]:
    """Add gasket/bolt rows if the model omitted them, per domain convention."""
    has_gasket = any(i.category == Category.GASKET for i in items)
    has_bolt = any(i.category == Category.BOLT for i in items)
    if has_gasket and has_bolt:
        return items

    flange_joints = sum(i.quantity for i in items if i.category == Category.FLANGE)
    valve_joints = sum(i.quantity for i in items if i.category == Category.VALVE)
    joints = int(flange_joints)  # conservative: count flange faces only
    if joints <= 0:
        return items

    next_no = max((i.item_no for i in items), default=0) + 1
    nps = items[0].size_nps if items else '""'
    if not has_gasket:
        items.append(MTOItem(
            item_no=next_no, category=Category.GASKET,
            description="Gasket, Spiral Wound, ASME B16.20 (derived)",
            size_nps=nps, quantity=joints, unit=Unit.EA,
            remarks="Derived: 1 per flanged joint",
        ))
        next_no += 1
    if not has_bolt:
        items.append(MTOItem(
            item_no=next_no, category=Category.BOLT,
            description="Stud Bolt with Nuts, ASTM A193 B7 / A194 2H (derived)",
            size_nps=nps, quantity=joints, unit=Unit.SET,
            remarks="Derived: 1 set per flanged joint",
        ))
    return items


def _compute_summary(items: list[MTOItem]) -> Summary:
    def count(cat: Category) -> int:
        return int(sum(i.quantity for i in items if i.category == cat))

    return Summary(
        total_pipe_length_m=round(
            sum((i.length_m or 0) for i in items if i.category == Category.PIPE), 2
        ),
        fittings=count(Category.FITTING),
        flanges=count(Category.FLANGE),
        valves=count(Category.VALVE),
        gaskets=count(Category.GASKET),
        bolt_sets=count(Category.BOLT),
        field_welds=0,  # bonus: not extracted in this version
        supports=count(Category.SUPPORT),
    )


def _parse_and_finalize(raw_json_text: str, provider_name: str) -> MTOResult:
    """Shared step: parse JSON text -> validate -> derive -> summarize."""
    raw = _strip_json_fences(raw_json_text)
    data = json.loads(raw)

    meta = DrawingMeta(**(data.get("drawing_meta") or {}))
    items = [MTOItem(**item) for item in data.get("items", [])]
    items = _derive_joint_consumables(items)
    summary = _compute_summary(items)

    return MTOResult(
        drawing_meta=meta, items=items, summary=summary,
        mode=provider_name, warnings=[],
    )


def extract_with_gemini(image_bytes: bytes, filename: str) -> MTOResult:
    """Call Gemini vision with the strict-schema prompt and validate the result."""
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    response = model.generate_content(
        [
            EXTRACTION_PROMPT,
            {"mime_type": "image/png", "data": image_bytes},
        ],
        generation_config={"response_mime_type": "application/json"},
        request_options={"timeout": 45},  # fail into mock instead of hanging forever
    )
    return _parse_and_finalize(response.text, "gemini")


def extract_with_groq(image_bytes: bytes, filename: str) -> MTOResult:
    """Call Groq vision (Llama 4 Scout) with the strict-schema prompt and validate the result."""
    import base64
    from groq import Groq

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    compressed = compress_for_groq(image_bytes)
    b64 = base64.b64encode(compressed).decode("utf-8")

    client = Groq(api_key=api_key, timeout=45)
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
        temperature=0.2,
        max_completion_tokens=4096,
        response_format={"type": "json_object"},
    )
    return _parse_and_finalize(completion.choices[0].message.content, "groq")


def run_pipeline(file_bytes: bytes, content_type: str, filename: str) -> MTOResult:
    """
    Top-level entry point used by the API layer.
    Never raises: falls back to a clearly-labelled mock MTO on any failure
    (missing key, bad JSON, API error, unreadable file), per the brief's
    'graceful degradation' requirement.
    """
    try:
        image_bytes = preprocess(file_bytes, content_type)
    except Exception as exc:
        result = build_mock_mto(filename)
        result.warnings.append(f"Preprocessing failed ({exc}); showing mock MTO.")
        return result

    provider = os.getenv("AI_PROVIDER", "").strip().lower()
    if not provider:
        if os.getenv("GROQ_API_KEY"):
            provider = "groq"
        elif os.getenv("GEMINI_API_KEY"):
            provider = "gemini"
        else:
            provider = "mock"

    if provider == "mock":
        return build_mock_mto(filename)

    try:
        if provider == "groq":
            return extract_with_groq(image_bytes, filename)
        elif provider == "gemini":
            return extract_with_gemini(image_bytes, filename)
        else:
            raise ValueError(f"Unknown AI_PROVIDER '{provider}'")
    except Exception as exc:
        result = build_mock_mto(filename)
        result.warnings.append(
            f"{provider.capitalize()} extraction failed ({exc}); showing mock MTO."
        )
        return result
