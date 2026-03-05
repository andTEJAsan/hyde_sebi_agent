from __future__ import annotations

import base64
import json
import logging
from typing import Any

import requests

from .models import ReferenceItem
from .utils import extract_json_array, normalize_date, normalize_type

logger = logging.getLogger(__name__)


PROMPT = """
You are an expert compliance analyst.
Read the given SEBI circular PDF and extract references made to other legal documents.
Return ONLY a JSON array (no markdown, no prose).

Each array item must have exactly these keys:
- name: string (official title if available)
- date: string or null (format DD-MM-YYYY; if unavailable use null)
- type: one of "circular", "master-circular", "order", "regulation"

Extraction rules:
- Include references to circulars, master circulars, orders, and regulations.
- Prefer explicit mentions in the document.
- If the date appears in another format, convert to DD-MM-YYYY.
- If uncertain about date, set it to null.
- Do not include duplicates.
""".strip()

PAGES_PROMPT = """
You are given two PDF documents:
1) Original circular PDF
2) Candidate referenced-document PDF

Task:
- Identify page numbers in the ORIGINAL circular where the candidate document is referenced.
- Return ONLY JSON object with this exact schema:
  {"pages": [<int>, ...]}

Rules:
- Page numbers are 1-based.
- Include unique integers only, sorted ascending.
- If no clear reference is found, return {"pages": []}
""".strip()


def _extract_text_from_gemini_response(resp_json: dict[str, Any]) -> str:
    candidates = resp_json.get("candidates") or []
    if not candidates:
        return ""

    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
    return "\n".join(t for t in text_parts if t)


def _extract_json_object(text: str) -> dict[str, Any]:
    if not text:
        return {}

    start = text.find("{")
    if start == -1:
        return {}

    depth = 0
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        return {}

    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def extract_references_with_gemini(
    pdf_bytes: bytes,
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> list[ReferenceItem]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    logger.info("Calling Gemini model=%s for reference extraction", model)
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": base64.b64encode(pdf_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    logger.debug("Gemini response status=%s", resp.status_code)

    body = resp.json()
    text = _extract_text_from_gemini_response(body)
    logger.debug("Gemini text response length=%d", len(text))
    data = extract_json_array(text)
    logger.info("Parsed %d raw reference items from Gemini JSON", len(data))

    cleaned: list[ReferenceItem] = []
    seen = set()
    for item in data:
        name = str(item.get("name", "")).strip()
        if not name:
            continue

        ref_type = normalize_type(str(item.get("type", "circular")))
        date = normalize_date(item.get("date"))

        key = (name.casefold(), ref_type, date or "")
        if key in seen:
            continue
        seen.add(key)

        cleaned.append(ReferenceItem(name=name, date=date, ref_type=ref_type))

    logger.info("Cleaned references count=%d", len(cleaned))
    return cleaned


def extract_reference_pages_with_gemini(
    original_pdf_bytes: bytes,
    candidate_pdf_bytes: bytes,
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> list[int]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    logger.info("Calling Gemini model=%s for page-level reference mapping", model)

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PAGES_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": base64.b64encode(original_pdf_bytes).decode("ascii"),
                        }
                    },
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": base64.b64encode(candidate_pdf_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    body = resp.json()
    text = _extract_text_from_gemini_response(body)
    data = _extract_json_object(text)
    raw_pages = data.get("pages", [])

    pages: list[int] = []
    for item in raw_pages if isinstance(raw_pages, list) else []:
        try:
            n = int(item)
            if n > 0:
                pages.append(n)
        except (TypeError, ValueError):
            continue

    pages = sorted(set(pages))
    logger.info("Mapped reference pages count=%d pages=%s", len(pages), pages)
    return pages
