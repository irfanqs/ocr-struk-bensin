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
from openai import RateLimitError

from receipt_ocr.image_tools import make_rotation_variants
from receipt_ocr.openrouter_client import DEFAULT_MODEL, extract_receipt_json as _openrouter_ocr
from receipt_ocr.groq_client import extract_receipt_json as _groq_ocr
from receipt_ocr.pdf_tools import page_count, render_page
from receipt_ocr.rekap_filler import normalize_plate


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    rotations = parse_rotations(args.rotations)
    pdf_paths = resolve_pdf_paths(Path(args.input_dir), args.pdf, args.glob)

    cache_dir = Path(args.output_dir) / "cache"
    rendered_dir = Path(args.output_dir) / "rendered"

    use_groq_fallback = False  # aktif setelah OpenRouter limit

    # Kumpulkan semua halaman yang perlu diproses
    all_pages: list[tuple[Path, int, Path]] = []
    for pdf_path in pdf_paths:
        total = page_count(pdf_path)
        for page_number in range(1, total + 1):
            cache_path = cache_dir / f"{slugify(pdf_path.parent.name)}_{slugify(pdf_path.stem)}_p{page_number}.json"
            all_pages.append((pdf_path, page_number, cache_path))
        if args.limit_pages is not None and len(all_pages) >= args.limit_pages:
            all_pages = all_pages[: args.limit_pages]
            break

    # Hasil per halaman: dict dengan status dan data
    results: list[dict] = []
    rate_limited_from: int | None = None  # index mulai rate limit

    for idx, (pdf_path, page_number, cache_path) in enumerate(all_pages):
        total_pages = page_count(pdf_path)

        if cache_path.exists() and not args.force:
            print(f"[skip] {pdf_path.name} hal {page_number} (cache ada)")
            results.append({"status": "selesai", "pdf": pdf_path, "page": page_number, "cache_path": cache_path})
            continue

        try:
            safe_stem = f"{slugify(pdf_path.parent.name)}_{slugify(pdf_path.stem)}_p{page_number}"
            rendered = render_page(pdf_path, page_number, rendered_dir / safe_stem, args.dpi)
            variants = make_rotation_variants(rendered, rendered_dir, safe_stem, rotations)
        except Exception as exc:
            print(f"ERROR render: {exc}")
            results.append({"status": "error", "pdf": pdf_path, "page": page_number, "cache_path": None})
            continue

        provider = "groq" if use_groq_fallback else "openrouter"
        print(f"[ocr/{provider}]  {pdf_path.name} hal {page_number}/{total_pages} ...", end=" ", flush=True)
        try:
            if use_groq_fallback:
                data = _groq_ocr(variants)
            else:
                data = _openrouter_ocr(variants, model=args.model)

            data["_meta"] = {
                "source_pdf": str(pdf_path),
                "source_folder": str(pdf_path.parent),
                "page": page_number,
                "cache_json": str(cache_path),
            }
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print("OK")
            results.append({"status": "selesai", "pdf": pdf_path, "page": page_number, "cache_path": cache_path})

        except RateLimitError as exc:
            if not use_groq_fallback:
                print(f"RATE LIMIT OpenRouter. Beralih ke Groq ...")
                use_groq_fallback = True
                # Coba ulang halaman ini dengan Groq
                try:
                    data = _groq_ocr(variants)
                    data["_meta"] = {
                        "source_pdf": str(pdf_path),
                        "source_folder": str(pdf_path.parent),
                        "page": page_number,
                        "cache_json": str(cache_path),
                    }
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    print("OK (groq)")
                    results.append({"status": "selesai", "pdf": pdf_path, "page": page_number, "cache_path": cache_path})
                except RateLimitError as exc2:
                    print(f"RATE LIMIT Groq juga: {exc2}")
                    print("Semua provider habis quota. Program berhenti.")
                    results.append({"status": "rate_limit", "pdf": pdf_path, "page": page_number, "cache_path": None})
                    rate_limited_from = idx + 1
                    break
                except Exception as exc2:
                    print(f"ERROR (groq): {exc2}")
                    results.append({"status": "error", "pdf": pdf_path, "page": page_number, "cache_path": None})
            else:
                print(f"RATE LIMIT Groq: {exc}")
                print("Semua provider habis quota. Program berhenti.")
                results.append({"status": "rate_limit", "pdf": pdf_path, "page": page_number, "cache_path": None})
                rate_limited_from = idx + 1
                break

        except Exception as exc:
            print(f"ERROR: {exc}")
            results.append({"status": "error", "pdf": pdf_path, "page": page_number, "cache_path": None})

    # Halaman yang belum sempat diproses karena rate limit
    if rate_limited_from is not None:
        for pdf_path, page_number, _ in all_pages[rate_limited_from:]:
            results.append({"status": "rate_limit", "pdf": pdf_path, "page": page_number, "cache_path": None})

    selesai = sum(1 for r in results if r["status"] == "selesai")
    error = sum(1 for r in results if r["status"] == "error")
    belum = sum(1 for r in results if r["status"] == "rate_limit")

    print(f"\nSelesai: {selesai} | Error: {error} | Belum (rate limit): {belum}")
    print(f"Cache JSON tersimpan di: {cache_dir}")

    csv_path = Path(args.output_dir) / "hasil_ocr.csv"
    _write_csv(results, cache_dir, csv_path)
    print(f"CSV hasil OCR disimpan: {csv_path}")

    if rate_limited_from is not None or error:
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
        paths = sorted(Path(p) for p in explicit_paths)
    elif pattern:
        paths = sorted(input_dir.rglob(pattern))
    else:
        paths = sorted(input_dir.rglob("*.pdf"))

    filtered = [p for p in paths if "ORI" not in p.name]
    skipped = len(paths) - len(filtered)
    if skipped:
        print(f"[skip] {skipped} file dilewati karena mengandung 'ORI' di nama file.")
    return filtered


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


def _write_csv(results: list[dict], cache_dir: Path, csv_path: Path) -> None:
    fieldnames = ["status", "needs_review", "cache_json", "source_pdf", "page",
                  "nopol", "tipe_bensin", "harga_per_liter", "total_rupiah",
                  "tanggal", "review_reason"]

    rows = []
    for r in results:
        if r["status"] == "selesai" and r.get("cache_path") and Path(r["cache_path"]).exists():
            row = _csv_row_from_json(Path(r["cache_path"]))
            row["status"] = "selesai"
        else:
            row = {k: "" for k in fieldnames}
            row["status"] = r["status"]  # "rate_limit" atau "error"
            row["source_pdf"] = str(r["pdf"])
            row["page"] = str(r["page"])
            row["needs_review"] = "-"
        rows.append(row)

    # Struk selesai + bagus (needs_review=tidak) di atas, lalu perlu review, lalu rate_limit/error
    order = {"tidak": 0, "ya": 1, "-": 2}
    rows.sort(key=lambda r: (order.get(r.get("needs_review", "-"), 2), r.get("source_pdf", ""), r.get("page", "")))

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _csv_row_from_json(json_path: Path) -> dict:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "error", "needs_review": "-", "cache_json": str(json_path),
                "source_pdf": "", "page": "", "nopol": "", "tipe_bensin": "",
                "harga_per_liter": "", "total_rupiah": "", "tanggal": "", "review_reason": ""}

    meta = data.get("_meta", {})
    needs_review = bool(data.get("needs_review", True))

    def val(field: str) -> str:
        item = data.get(field)
        if isinstance(item, dict):
            return str(item.get("value") or "")
        return ""

    return {
        "status": "selesai",
        "needs_review": "ya" if needs_review else "tidak",
        "cache_json": str(json_path),
        "source_pdf": meta.get("source_pdf", ""),
        "page": meta.get("page", ""),
        "nopol": normalize_plate(val("nopol")) or "",
        "tipe_bensin": val("produk"),
        "harga_per_liter": val("harga_per_liter"),
        "total_rupiah": val("total_rupiah"),
        "tanggal": val("tanggal"),
        "review_reason": data.get("review_reason") or "",
    }


if __name__ == "__main__":
    main()
