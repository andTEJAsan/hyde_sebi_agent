from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


VALID_TYPES = {"circular", "master-circular", "order", "regulation"}



def normalize_type(value: str) -> str:
    s = value.strip().lower().replace("_", "-")
    s = s.replace("master circular", "master-circular")
    s = s.replace("master-circulars", "master-circular")
    s = s.replace("circulars", "circular")
    s = s.replace("orders", "order")
    s = s.replace("regulations", "regulation")
    if s not in VALID_TYPES:
        return "circular"
    return s



def normalize_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    # Handle formats like 1-4-2023 or 01/04/2023.
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            normalized = datetime(year, month, day).strftime("%d-%m-%Y")
            logger.debug("Normalized date %r -> %r", value, normalized)
            return normalized
        except ValueError:
            logger.debug("Could not normalize date with numeric pattern: %r", value)
            return None

    known_formats = [
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ]
    for fmt in known_formats:
        try:
            normalized = datetime.strptime(raw, fmt).strftime("%d-%m-%Y")
            logger.debug("Normalized date %r (%s) -> %r", value, fmt, normalized)
            return normalized
        except ValueError:
            continue
    logger.debug("Date normalization failed for %r", value)
    return None



def extract_json_array(text: str) -> list[dict[str, Any]]:
    """Extract first JSON array from a text response."""
    if not text:
        return []

    start = text.find("[")
    if start == -1:
        return []

    depth = 0
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        return []

    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    return []
