from __future__ import annotations

import logging
from pathlib import Path

from .config import load_settings
from .llm_extractor import extract_reference_pages_with_gemini, extract_references_with_gemini
from .models import ResolvedReference
from .sebi_fetch import (
    download_pdf_bytes,
    make_session,
    resolve_pdf_url_from_circular_page,
)
from .sebi_search import search_first_link

logger = logging.getLogger(__name__)


def run_agent(circular_page_url: str | None = None, input_pdf_path: str | None = None) -> dict:
    if not circular_page_url and not input_pdf_path:
        raise RuntimeError("Provide either circular_page_url or input_pdf_path")

    logger.info("Loading settings")
    settings = load_settings()
    logger.info("Creating HTTP session")
    session = make_session()

    source_pdf_url: str | None = None
    source_pdf_path: str | None = None

    if input_pdf_path:
        source_pdf_path = input_pdf_path
        logger.info("Reading source PDF from local file: %s", input_pdf_path)
        pdf_bytes = Path(input_pdf_path).read_bytes()
        if not pdf_bytes.startswith(b"%PDF"):
            raise RuntimeError(f"Input file is not a valid PDF: {input_pdf_path}")
    else:
        logger.info("Resolving source PDF from circular page")
        source_pdf_url = resolve_pdf_url_from_circular_page(session, circular_page_url or "")
        pdf_bytes = download_pdf_bytes(session, source_pdf_url)

    logger.info("Extracting references from source PDF using Gemini")
    references = extract_references_with_gemini(
        pdf_bytes=pdf_bytes,
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
    )
    logger.info("Total references extracted: %d", len(references))

    resolved: list[ResolvedReference] = []
    for ref in references:
        logger.info("Resolving reference: name=%r type=%s date=%r", ref.name, ref.ref_type, ref.date)
        link, count = search_first_link(
            session=session,
            query_title=ref.name,
            ref_type=ref.ref_type,
            exact_date=ref.date,
            search_context=settings.search_context,
            type_search=settings.type_search,
        )

        if not link:
            logger.warning("No link found for reference: name=%r type=%s", ref.name, ref.ref_type)
            resolved.append(
                ResolvedReference(
                    reference=ref,
                    resolved_link=None,
                    search_result_count=count,
                    status="not_found",
                    pages=[],
                    reason="No matching SEBI search result",
                )
            )
            continue

        logger.info("Resolved reference to link: %s", link)

        # Resolve linked page -> linked PDF and map page numbers in original PDF.
        pages: list[int] = []
        page_reason: str | None = None
        try:
            linked_pdf_url = resolve_pdf_url_from_circular_page(session, link)
            linked_pdf_bytes = download_pdf_bytes(session, linked_pdf_url)
            pages = extract_reference_pages_with_gemini(
                original_pdf_bytes=pdf_bytes,
                candidate_pdf_bytes=linked_pdf_bytes,
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
            )
        except Exception as exc:  # noqa: BLE001
            page_reason = f"Could not map pages: {exc}"
            logger.warning("Page mapping failed for link=%s error=%s", link, exc)

        resolved.append(
            ResolvedReference(
                reference=ref,
                resolved_link=link,
                search_result_count=count,
                status="resolved",
                pages=pages,
                reason=page_reason,
            )
        )

    logger.info(
        "Resolution complete: resolved=%d not_found=%d",
        sum(1 for r in resolved if r.status == "resolved"),
        sum(1 for r in resolved if r.status == "not_found"),
    )
    return {
        "input_circular_page_url": circular_page_url,
        "input_pdf_path": source_pdf_path,
        "source_pdf_url": source_pdf_url,
        "reference_count": len(references),
        "references": [r.to_dict() for r in references],
        "resolved_links": [r.to_dict() for r in resolved],
        "links_only": [r.resolved_link for r in resolved if r.resolved_link],
    }
