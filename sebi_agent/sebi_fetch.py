from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)



def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.sebi.gov.in",
        }
    )
    return session



def fetch_html(session: requests.Session, url: str, timeout: int = 25) -> tuple[int, str, str]:
    logger.info("Fetching HTML: %s", url)
    resp = session.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    logger.debug("Fetched HTML status=%s final_url=%s", resp.status_code, resp.url)
    return resp.status_code, str(resp.url), resp.text



def normalize_pdf_candidate_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "file" in query and query["file"]:
        return unquote(query["file"][0])
    return url



def extract_pdf_url_from_circular_page(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if ".pdf" in href.lower() or "?file=" in href.lower():
            return normalize_pdf_candidate_url(urljoin(base_url, href))

    for tag, attr in (("iframe", "src"), ("embed", "src"), ("object", "data")):
        for node in soup.find_all(tag):
            value = (node.get(attr) or "").strip()
            if ".pdf" in value.lower() or "?file=" in value.lower():
                return normalize_pdf_candidate_url(urljoin(base_url, value))

    absolute = re.search(r"https?://[^\"'\s>]+\.pdf(?:\?[^\"'\s>]*)?", html, re.IGNORECASE)
    if absolute:
        return normalize_pdf_candidate_url(absolute.group(0))

    quoted = re.search(r"([\"'])([^\"']+\.pdf(?:\?[^\"']*)?)\1", html, re.IGNORECASE)
    if quoted:
        return normalize_pdf_candidate_url(urljoin(base_url, quoted.group(2)))

    return None



def resolve_pdf_url_from_circular_page(session: requests.Session, circular_page_url: str) -> str:
    logger.info("Resolving PDF URL from circular page: %s", circular_page_url)
    _, final_url, html = fetch_html(session, circular_page_url)
    pdf_url = extract_pdf_url_from_circular_page(html, final_url)
    if not pdf_url:
        raise RuntimeError(f"Could not resolve PDF URL from circular page: {circular_page_url}")
    logger.info("Resolved PDF URL: %s", pdf_url)
    return pdf_url



def download_pdf_bytes(session: requests.Session, pdf_url: str, timeout: int = 40) -> bytes:
    logger.info("Downloading source PDF bytes from: %s", pdf_url)
    resp = session.get(pdf_url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    content = resp.content
    if not content.startswith(b"%PDF"):
        raise RuntimeError(
            f"Fetched content is not a valid PDF from URL={pdf_url}; "
            f"Content-Type={resp.headers.get('Content-Type', '')}"
        )
    logger.info("Downloaded PDF bytes: %d bytes", len(content))
    return content
