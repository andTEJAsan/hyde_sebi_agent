# SEBI Reference Link Agent

This agent takes either a **SEBI circular page URL** or a **local PDF file** as input, extracts referenced legal documents with **Gemini (`gemini-2.5-flash`)**, resolves a first SEBI link for each reference, and maps original-document page numbers where each resolved reference is cited.

Current scope intentionally matches your request:
- Input: one circular page URL
- Extract references from PDF via LLM
- Supported reference types: `circular`, `master-circular`, `order`, `regulation`
- Date normalization to `DD-MM-YYYY` where fixable
- Search and return **link only** (first match)
- No file downloads for resolved references

## Project Structure

```text
sebi_agent/
  __init__.py
  cli.py
  config.py
  llm_extractor.py
  models.py
  pipeline.py
  sebi_fetch.py
  sebi_search.py
  utils.py
requirements.txt
README.md
```

## Prerequisites

- Python 3.10+
- `GEMINI_API_KEY` set in `.env` (already present in your setup)

## Install

```bash
pip install -r requirements.txt
```

## Run

From circular URL:

```bash
python -m sebi_agent.cli \
  --circular-url "https://www.sebi.gov.in/legal/circulars/mar-2026/guidelines-for-custodians_100118.html" \
  --out output.json
```

From local PDF path:

```bash
python -m sebi_agent.cli \
  --pdf-path "/absolute/path/to/source.pdf" \
  --out output.json
```

## Evaluate Claims (LLM-as-Judge)

Given generated `output.json`, run evaluator:

```bash
python -m sebi_agent.eval_cli \
  --output-json output.json \
  --out eval_output.json \
  --log-level INFO
```

Evaluator behavior:
- loads original PDF (from `input_pdf_path` or `source_pdf_url`)
- for each resolved link, resolves referenced PDF
- asks Gemini judge whether the resolved referenced PDF is genuinely mentioned in the original PDF
- writes per-item verdict (`true`/`false`/`uncertain`) with confidence and reason

## Output Format

The agent writes JSON with:
- `input_circular_page_url`
- `source_pdf_url`
- `reference_count`
- `references`: extracted LLM references (`name`, `date`, `type`)
- `resolved_links`: each reference + resolved first link + `pages` in original PDF (or not found status)
- `links_only`: resolved URLs only

## Notes

- Search resolution uses the SEBI AJAX search endpoint and returns the **first candidate link**.
- If LLM date is malformed but fixable (e.g., `1-4-2023`), it is normalized to `01-04-2023`.
- If not fixable, date is set to `null`.
- If Gemini returns non-JSON text, the agent extracts the first JSON array block from the response.

## Known Limitations

- Link resolution is first-match based and heuristic filtered by type hints.
- Some SEBI pages may be session-sensitive.
- This version is optimized for the workflow discussed; ranking-based disambiguation can be added later.
# hyde_sebi_agent
