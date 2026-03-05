from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .evaluator import run_evaluator


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Evaluate output.json claims using Gemini-as-judge by comparing original PDF "
            "against each resolved referenced PDF and claimed pages."
        )
    )
    p.add_argument("--output-json", required=True, help="Path to agent output.json")
    p.add_argument("--out", default="eval_output.json", help="Evaluation result output path")
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

    result = run_evaluator(args.output_json)
    out_path = Path(args.out)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logging.getLogger(__name__).info("Wrote evaluation to %s", out_path)


if __name__ == "__main__":
    main()
