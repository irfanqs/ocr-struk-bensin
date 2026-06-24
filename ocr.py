#!/usr/bin/env python3
"""
Program 1: OCR struk BBM PDF → simpan hasil ke JSON cache.

Cara pakai:
  python ocr.py                                         # semua PDF di input/
  python ocr.py --limit-pages 5                         # test beberapa halaman
  python ocr.py --pdf "input/.../BBM CS NOV BAGUS.pdf" # PDF tertentu
  python ocr.py --glob "*NOV*BAGUS.pdf"                 # filter pola nama
  python ocr.py --rotations 0                           # skip rotasi
  python ocr.py --force                                 # paksa OCR ulang
  python ocr.py --model google/gemini-2.0-flash-001     # pilih model
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from receipt_ocr.image_tools import make_rotation_variants
from receipt_ocr.openrouter_client import DEFAULT_MODEL, extract_receipt_json
from receipt_ocr.pdf_tools import page_count, render_page
from receipt_ocr.rekap_filler import normalize_plate


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    rotations = parse_rotations(args.rotations)
    pdf_paths = resolve_pdf_paths(Path(args.input_dir), args.pdf, args.glob)

    cache_dir = Path(args.output_dir) / "cache"
    rendered_dir = Path(args.output_dir) / "rendered"

    processed = 0
    failed = 0

    for pdf_path in pdf_paths:
        total_pages = page_count(pdf_path)
        for page_number in range(1, total_pages + 1):
            if args.limit_pages is not None and processed >= args.limit_pages:
                break

            cache_path = cache_dir / f"{slugify(pdf_path.parent.name)}_{slugify(pdf_path.stem)}_p{page_number}.json"

            if cache_path.exists() and not args.force:
                print(f"[skip] {pdf_path.name} hal {page_number} (cache ada)")
                processed += 1
                continue

            print(f"[ocr]  {pdf_path.name} hal {page_number}/{total_pages} ...", end=" ", flush=True)
            try:
                safe_stem = f"{slugify(pdf_path.parent.name)}_{slugify(pdf_path.stem)}_p{page_number}"
                rendered = render_page(pdf_path, page_number, rendered_dir / safe_stem, args.dpi)
                variants = make_rotation_variants(rendered, rendered_dir, safe_stem, rotations)
                data = extract_receipt_json(variants, model=args.model)
                data["_meta"] = {
                    "source_pdf": str(pdf_path),
                    "source_folder": str(pdf_path.parent),
                    "page": page_number,
                    "cache_json": str(cache_path),
                }
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                print("OK")
            except Exception as exc:
                print(f"ERROR: {exc}")
                failed += 1

            processed += 1

        if args.limit_pages is not None and processed >= args.limit_pages:
            break

    print(f"\nSelesai. {processed} halaman diproses, {failed} gagal.")
    print(f"Cache JSON tersimpan di: {cache_dir}")

    csv_path = Path(args.output_dir) / "hasil_ocr.csv"
    _write_csv(cache_dir, csv_path)
    print(f"CSV hasil OCR disimpan: {csv_path}")

    if failed:
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OCR struk BBM PDF dengan OpenRouter Vision → simpan ke JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input-dir", default="input", help="Folder berisi PDF struk. (default: input)")
    parser.add_argument("--output-dir", default="output", help="Folder output cache/rendered. (default: output)")
    parser.add_argument("--pdf", action="append", default=[], metavar="PATH",
                        help="Path PDF spesifik. Bisa dipakai berkali-kali.")
    parser.add_argument("--glob", default=None, metavar="PATTERN",
                        help="Filter nama PDF di input-dir, contoh '*NOV*BAGUS.pdf'.")
    parser.add_argument("--limit-pages", type=int, default=None, metavar="N",
                        help="Batasi jumlah halaman (untuk testing).")
    parser.add_argument("--dpi", type=int, default=220, help="Resolusi render PDF. (default: 220)")
    parser.add_argument("--rotations", default="0,90,180,270",
                        help="Rotasi yang dikirim ke model, contoh '0' atau '0,180'. (default: 0,90,180,270)")
    parser.add_argument("--force", action="store_true",
                        help="OCR ulang meskipun cache JSON sudah ada.")
    parser.add_argument("--model", default=None, metavar="MODEL_ID",
                        help=f"Model OpenRouter yang dipakai. (default: {DEFAULT_MODEL})")
    return parser


def resolve_pdf_paths(input_dir: Path, explicit_paths: list[str], pattern: str | None) -> list[Path]:
    if explicit_paths:
        return sorted(Path(p) for p in explicit_paths)
    if pattern:
        return sorted(input_dir.rglob(pattern))
    return sorted(input_dir.rglob("*.pdf"))


def parse_rotations(value: str) -> list[int]:
    rotations = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        rotation = int(item)
        if rotation not in {0, 90, 180, 270}:
            raise ValueError(f"Rotasi tidak valid: {rotation}. Pilihan: 0, 90, 180, 270.")
        rotations.append(rotation)
    return rotations or [0]


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def _write_csv(cache_dir: Path, csv_path: Path) -> None:
    json_files = sorted(cache_dir.glob("*.json"))
    if not json_files:
        return

    rows = [_csv_row_from_json(f) for f in json_files]
    # Struk bagus (needs_review=False) diletakkan di atas
    rows.sort(key=lambda r: (r["needs_review"] == "ya", r["source_pdf"], r["page"]))

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["ocr_bagus", "cache_json", "source_pdf", "page",
                  "nopol", "tipe_bensin", "harga_per_liter", "total_rupiah",
                  "tanggal", "needs_review", "review_reason"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _csv_row_from_json(json_path: Path) -> dict:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return {k: "" for k in ["ocr_bagus", "cache_json", "source_pdf", "page",
                                 "nopol", "tipe_bensin", "harga_per_liter", "total_rupiah",
                                 "tanggal", "needs_review", "review_reason"]}

    meta = data.get("_meta", {})
    needs_review = bool(data.get("needs_review", True))

    def val(field: str) -> str:
        item = data.get(field)
        if isinstance(item, dict):
            return str(item.get("value") or "")
        return ""

    return {
        "ocr_bagus": "tidak" if needs_review else "ya",
        "cache_json": str(json_path),
        "source_pdf": meta.get("source_pdf", ""),
        "page": meta.get("page", ""),
        "nopol": normalize_plate(val("nopol")) or "",
        "tipe_bensin": val("produk"),
        "harga_per_liter": val("harga_per_liter"),
        "total_rupiah": val("total_rupiah"),
        "tanggal": val("tanggal"),
        "needs_review": "ya" if needs_review else "tidak",
        "review_reason": data.get("review_reason") or "",
    }


if __name__ == "__main__":
    main()
