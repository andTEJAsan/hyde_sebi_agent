from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import requests

from .config import load_settings
from .sebi_fetch import (
    download_pdf_bytes,
    make_session,
    resolve_pdf_url_from_circular_page,
)

logger = logging.getLogger(__name__)


JUDGE_PROMPT = """
You are evaluating whether a claim is valid.

Inputs:
1) Original circular PDF
2) Referenced document PDF
3) Reference metadata (name/type/date)

Task:
- Check whether the referenced document is actually mentioned/cited anywhere in the ORIGINAL PDF.
- Be strict. If evidence is weak/ambiguous, prefer `uncertain` or `false`.

Return ONLY JSON object with this schema:
{
  "verdict": "true" | "false" | "uncertain",
  "confidence": <0 to 1 float>,
  "reason": "short explanation"
}
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


def judge_claim_with_gemini(
    original_pdf_bytes: bytes,
    referenced_pdf_bytes: bytes,
    reference_meta: dict[str, Any],
    api_key: str,
    model: str,
) -> dict[str, Any]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    context = {"reference": reference_meta}

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": JUDGE_PROMPT},
                    {"text": json.dumps(context)},
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": base64.b64encode(original_pdf_bytes).decode("ascii"),
                        }
                    },
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": base64.b64encode(referenced_pdf_bytes).decode("ascii"),
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

    text = _extract_text_from_gemini_response(resp.json())
    data = _extract_json_object(text)

    verdict = str(data.get("verdict", "uncertain")).strip().lower()
    if verdict not in {"true", "false", "uncertain"}:
        verdict = "uncertain"

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))
    reason = str(data.get("reason", "No reason provided")).strip() or "No reason provided"

    return {
        "verdict": verdict,
        "confidence": confidence,
        "reason": reason,
    }


def _read_original_pdf(output_data: dict[str, Any], session: requests.Session) -> tuple[bytes, str]:
    input_pdf_path = output_data.get("input_pdf_path")
    source_pdf_url = output_data.get("source_pdf_url")

    if input_pdf_path:
        path = Path(str(input_pdf_path))
        data = path.read_bytes()
        if not data.startswith(b"%PDF"):
            raise RuntimeError(f"Original input file is not a valid PDF: {path}")
        return data, f"file:{path}"

    if source_pdf_url:
        data = download_pdf_bytes(session, str(source_pdf_url))
        return data, str(source_pdf_url)

    raise RuntimeError("Neither input_pdf_path nor source_pdf_url present in output.json")


def run_evaluator(output_json_path: str) -> dict[str, Any]:
    settings = load_settings()
    session = make_session()

    output_data = json.loads(Path(output_json_path).read_text(encoding="utf-8"))
    original_pdf_bytes, original_source = _read_original_pdf(output_data, session)

    resolved_links = output_data.get("resolved_links", [])
    evaluations: list[dict[str, Any]] = []

    for item in resolved_links:
        reference = item.get("reference", {})
        resolved_link = item.get("resolved_link")
        pages = item.get("pages") or []

        row = {
            "reference": reference,
            "resolved_link": resolved_link,
            "claimed_pages": pages,
            "status": "skipped",
            "judge": None,
            "reason": None,
        }

        if not resolved_link:
            row["reason"] = "No resolved link to evaluate"
            evaluations.append(row)
            continue

        try:
            logger.info("Evaluator: resolving referenced PDF from %s", resolved_link)
            referenced_pdf_url = resolve_pdf_url_from_circular_page(session, str(resolved_link))
            referenced_pdf_bytes = download_pdf_bytes(session, referenced_pdf_url)

            judge = judge_claim_with_gemini(
                original_pdf_bytes=original_pdf_bytes,
                referenced_pdf_bytes=referenced_pdf_bytes,
                reference_meta=reference,
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
            )
            row["status"] = "evaluated"
            row["judge"] = judge
            row["referenced_pdf_url"] = referenced_pdf_url
        except Exception as exc:  # noqa: BLE001
            row["status"] = "error"
            row["reason"] = str(exc)

        evaluations.append(row)

    true_count = sum(1 for e in evaluations if (e.get("judge") or {}).get("verdict") == "true")
    false_count = sum(1 for e in evaluations if (e.get("judge") or {}).get("verdict") == "false")
    uncertain_count = sum(1 for e in evaluations if (e.get("judge") or {}).get("verdict") == "uncertain")

    return {
        "evaluated_from": output_json_path,
        "original_pdf_source": original_source,
        "total_items": len(evaluations),
        "evaluated_items": sum(1 for e in evaluations if e.get("status") == "evaluated"),
        "verdict_summary": {
            "true": true_count,
            "false": false_count,
            "uncertain": uncertain_count,
        },
        "items": evaluations,
    }
