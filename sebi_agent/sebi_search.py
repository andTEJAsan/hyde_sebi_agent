from __future__ import annotations

import base64
import logging
import re
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

SECTION_SEARCH_BASE = "https://www.sebi.gov.in/section-search.html"
AJAX_SEARCH_ENDPOINT = "https://www.sebi.gov.in/sebiweb/ajax/search/section-search.jsp"

logger = logging.getLogger(__name__)



def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()





def to_sebi_type_label(ref_type: str) -> str:
    t = normalize_text(ref_type).replace("_", "-")
    if t in {"master circular", "master-circular", "master-circulars"}:
        return "Master-Circulars"
    if t in {"order", "orders"}:
        return "Orders"
    if t in {"regulation", "regulations"}:
        return "Regulations"
    return "Circulars"

def encode_searchval_for_ajax(query_title: str) -> str:
    # Match observed SEBI request behavior: base64 over raw text.
    return base64.b64encode(query_title.encode("utf-8")).decode("utf-8")



def build_section_search_url(
    query_title: str,
    search_context: str,
    from_date: str | None,
    to_date: str | None,
) -> str:
    params = {
        "searchval": query_title,
        "searchcontext": search_context,
        "searchfromdate": from_date or "",
        "searchtodate": to_date or "",
    }
    return f"{SECTION_SEARCH_BASE}?{urlencode(params)}"



def build_ajax_payload(
    query_title: str,
    from_date: str | None,
    to_date: str | None,
    fval: str,
    type_search: str,
) -> dict[str, str]:
    return {
        "next_value": "1",
        "searchval": encode_searchval_for_ajax(query_title),
        "fromDate": from_date or "",
        "toDate": to_date or "",
        "fval": fval,
        "typeSearch": str(type_search),
        "next": "s",
        "doDirect": "-1",
        "sortby": "1",
    }



def fetch_search_results_ajax(
    session: requests.Session,
    query_title: str,
    from_date: str | None,
    to_date: str | None,
    search_context: str,
    fval: str,
    type_search: str,
) -> tuple[str, dict[str, str]]:
    payload = build_ajax_payload(
        query_title=query_title,
        from_date=from_date,
        to_date=to_date,
        fval=fval,
        type_search=type_search,
    )
    referer_url = build_section_search_url(
        query_title=query_title,
        search_context=search_context,
        from_date=from_date,
        to_date=to_date,
    )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": referer_url,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }

    logger.info(
        "SEBI AJAX search: title=%r date=%r context=%s type_search=%s",
        query_title,
        {"from": from_date, "to": to_date},
        search_context,
        type_search,
    )
    logger.debug("SEBI AJAX payload: %s", payload)
    resp = session.post(
        AJAX_SEARCH_ENDPOINT,
        data=payload,
        headers=headers,
        timeout=30,
        allow_redirects=True,
    )
    resp.raise_for_status()
    logger.debug("SEBI AJAX response status=%s bytes=%d", resp.status_code, len(resp.text))
    return resp.text, payload



def infer_reference_type(text: str) -> str:
    t = normalize_text(text)
    if "master circular" in t or "master-circular" in t:
        return "master-circular"
    if "regulation" in t:
        return "regulation"
    if "order" in t:
        return "order"
    if "circular" in t:
        return "circular"
    return "unknown"



def rerank_results_by_title(results: list[dict], query_title: str) -> list[dict]:
    """
    Rerank raw SEBI results by title relevance to query_title.
    Uses RapidFuzz token_set_ratio when available; otherwise falls back to lexical overlap.
    """
    query = normalize_text(query_title)
    if not results or not query:
        return results

    try:
        from rapidfuzz import fuzz  # type: ignore

        scored = []
        for row in results:
            title = normalize_text(str(row.get("title", "")))
            score = float(fuzz.token_set_ratio(query, title))
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        logger.debug("Reranked with RapidFuzz; top_scores=%s", [round(sc, 2) for sc, _ in scored[:5]])
        return [row for _, row in scored]
    except Exception:
        q_tokens = set(re.findall(r"[a-z0-9]+", query))
        scored = []
        for row in results:
            title = normalize_text(str(row.get("title", "")))
            t_tokens = set(re.findall(r"[a-z0-9]+", title))
            score = float(len(q_tokens & t_tokens))
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        logger.debug("Reranked with lexical overlap; top_scores=%s", [sc for sc, _ in scored[:5]])
        return [row for _, row in scored]


def extract_section_search_results(html: str, base_url: str = "https://www.sebi.gov.in/") -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id="result_ajax") or soup
    rows: list[dict] = []
    seen = set()

    for a in container.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        href = urljoin(base_url, a["href"].strip())
        href_l = href.lower()

        if not title or len(title) < 4:
            continue
        if href in seen:
            continue
        if "sebi.gov.in" not in href_l:
            continue
        if "javascript:" in href_l:
            continue
        if not any(k in href_l for k in ["/legal/", "/circulars/", "/orders/", "/regulations/"]):
            continue

        context_text = " ".join([title, a.parent.get_text(" ", strip=True) if a.parent else "", href])
        rows.append(
            {
                "title": title,
                "detail_url": href,
                "reference_type": infer_reference_type(context_text),
            }
        )
        seen.add(href)

    logger.info("Extracted %d SEBI search result links", len(rows))
    return rows



def search_first_link(
    session: requests.Session,
    query_title: str,
    ref_type: str,
    exact_date: str | None,
    search_context: str,
    type_search: str,
) -> tuple[str | None, int]:
    logger.info("Resolving first link for reference: title=%r type=%s date=%r", query_title, ref_type, exact_date)
    sebi_type_label = to_sebi_type_label(ref_type)
    effective_search_context = sebi_type_label if (search_context or "").strip() == "-1" else search_context
    # Pass 1: exact date (if available). Pass 2 fallback: no date restriction.
    attempts: list[tuple[str | None, str | None]] = [(exact_date, exact_date)]
    if exact_date:
        attempts.append((None, None))

    results: list[dict] = []
    for from_date, to_date in attempts:
        html, _payload = fetch_search_results_ajax(
            session=session,
            query_title=query_title,
            from_date=from_date,
            to_date=to_date,
            search_context=effective_search_context,
            fval=sebi_type_label,
            type_search=type_search,
        )
        results = extract_section_search_results(html)
        if results:
            break

    if not results:
        logger.warning("No SEBI search results found for title=%r", query_title)
        return None, 0

    results = rerank_results_by_title(results, query_title)
    candidate = results[0]
    logger.info(
        "Picked first reranked SEBI result link=%s (total_count=%d)",
        candidate.get("detail_url"),
        len(results),
    )
    return candidate.get("detail_url"), len(results)
