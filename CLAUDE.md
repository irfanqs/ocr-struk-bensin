# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python CLI that reads scanned Indonesian fuel receipt PDFs (struk BBM), performs OCR via Groq Vision API, and fills a monthly Excel report (rekap) template. Receipts are often blurry, rotated, or hand-annotated.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

System dependencies (Poppler) must be installed separately:
```bash
brew install poppler   # macOS
```

Copy `.env.example` to `.env` and set `GROQ_API_KEY` and optionally `GROQ_MODEL`.

## Running

```bash
# Process all PDFs in input/
python -m receipt_ocr

# Test with a few pages only
python -m receipt_ocr --limit-pages 5

# Process specific PDF and fill rekap
python -m receipt_ocr --pdf "input/STRUK BBM NOV 2025/BBM CS NOV BAGUS.pdf" --fill-rekap

# Skip rotation variants if orientation is known
python -m receipt_ocr --pdf "..." --rotations 0 --fill-rekap

# Force re-OCR (ignore JSON cache)
python -m receipt_ocr --force

# Filter by glob pattern
python -m receipt_ocr --glob "*NOV*BAGUS.pdf" --fill-rekap

# Fill rekap from cached OCR results with custom template/output
python -m receipt_ocr --fill-rekap \
  --rekap-template "REKAP PENGGUNAAN_BBM_PERIODE_BULAN_NOVEMBER 2025-2.xlsx" \
  --rekap-output output/rekap_terisi.xlsx
```

## Architecture

```
cli.py          → argument parsing, orchestrates pipeline + export + rekap
pipeline.py     → per-page OCR loop; manages JSON cache and rendered image files
pdf_tools.py    → subprocess calls to pdfinfo/pdftoppm (Poppler)
image_tools.py  → PIL image enhancement (contrast, sharpness) + rotation variants
groq_client.py  → Groq Vision API call with Indonesian OCR prompt; rate-limit retry
export_excel.py → writes standalone hasil_ocr_struk.xlsx from OCR rows
rekap_filler.py → fills monthly rekap Excel template; writes OCR LOG / DATA OCR / PERLU REVIEW sheets
```

### Data flow

1. `OcrPipeline.run()` iterates PDFs → `render_page()` (Poppler) → `make_rotation_variants()` (PIL) → `extract_receipt_json()` (Groq) → JSON cache written to `output/cache/`
2. `flatten_result()` in `pipeline.py` converts nested Groq JSON into a flat dict per page, with `_confidence`, `_raw_text`, `_notes` suffixes for every field
3. `export_rows()` writes all flat rows to `output/hasil_ocr_struk.xlsx`
4. `fill_rekap()` maps each row to a cell in the monthly Excel workbook by matching plate number + fuel type (column pair) and transaction date (row range); writes three extra sheets

### Key domain rules

- Valid plate numbers start with `L` (e.g. `L 1941 OL`) or the exception `AE 8719 SQ`; `normalize_plate()` in `rekap_filler.py` enforces this pattern
- Sheet names in the rekap workbook are `"NOVEMBER 2025"`, `"OKTOBER 2025"`, etc.; `fill_rekap()` derives the sheet name from the parsed date
- When Groq returns a year-less date, `apply_source_period()` infers the period from the PDF folder/filename (e.g. `STRUK BBM NOV 2025`)
- Each page is cached as a JSON file under `output/cache/`; re-run is skipped unless `--force`
- Rows flagged `needs_review=True` are highlighted yellow in Excel; fill statuses are `filled`, `partial_fill`, `already_filled`, `skipped`

### Groq Vision prompt

The OCR prompt lives as the module-level `PROMPT` constant in `groq_client.py`. It instructs the model to output a strict JSON schema with per-field confidence scores, return `null` for unreadable fields, and pick the best rotation from the supplied image variants.
