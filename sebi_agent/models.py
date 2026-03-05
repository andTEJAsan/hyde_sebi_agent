from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class ReferenceItem:
    name: str
    date: Optional[str]
    ref_type: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = data.pop("ref_type")
        return data


@dataclass
class ResolvedReference:
    reference: ReferenceItem
    resolved_link: Optional[str]
    search_result_count: int
    status: str
    pages: Optional[list[int]] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference.to_dict(),
            "resolved_link": self.resolved_link,
            "search_result_count": self.search_result_count,
            "status": self.status,
            "pages": self.pages,
            "reason": self.reason,
        }
