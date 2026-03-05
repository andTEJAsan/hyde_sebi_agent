from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .pipeline import run_agent



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Given a SEBI circular page URL OR local PDF file, extract referenced legal docs "
            "and resolve first matching SEBI links."
        )
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--circular-url", help="SEBI circular detail page URL")
    src.add_argument("--pdf-path", help="Local path to source PDF")
    p.add_argument(
        "--out",
        default="output.json",
        help="Output JSON file path (default: output.json)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default: INFO)",
    )
    return p



def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger(__name__).info(
        "Starting agent source circular_url=%s pdf_path=%s",
        args.circular_url,
        args.pdf_path,
    )

    result = run_agent(circular_page_url=args.circular_url, input_pdf_path=args.pdf_path)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logging.getLogger(__name__).info("Wrote results to %s", out_path)


if __name__ == "__main__":
    main()
