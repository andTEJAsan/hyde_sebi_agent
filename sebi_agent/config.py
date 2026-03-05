from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv() -> None:
        return None


@dataclass
class Settings:
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    search_context: str = "-1"
    type_search: str = "5"



def load_settings() -> Settings:
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing GEMINI_API_KEY in environment or .env file")
    return Settings(gemini_api_key=key)
