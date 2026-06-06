from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from .export_excel import export_rows
from .pipeline import OcrPipeline
from .rekap_filler import fill_rekap


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OCR struk BBM PDF dengan Groq Vision.")
    parser.add_argument("--input-dir", default="input", help="Folder berisi PDF struk.")
    parser.add_argument("--output-dir", default="output", help="Folder output cache/render/excel.")
    parser.add_argument("--excel", default="output/hasil_ocr_struk.xlsx", help="Path Excel hasil OCR.")
    parser.add_argument("--limit-pages", type=int, default=None, help="Batasi jumlah halaman untuk testing.")
    parser.add_argument("--pdf", action="append", default=[], help="Path PDF spesifik. Bisa dipakai berkali-kali.")
    parser.add_argument("--glob", default=None, help="Filter nama/path PDF di input-dir, contoh '*NOV*BAGUS.pdf'.")
    parser.add_argument("--force", action="store_true", help="OCR ulang walaupun cache JSON sudah ada.")
    parser.add_argument("--dpi", type=int, default=220, help="Resolusi render PDF.")
    parser.add_argument("--rotations", default="0,90,180,270", help="Rotasi yang dikirim ke Groq, contoh '0' atau '0,180'.")
    parser.add_argument("--fill-rekap", action="store_true", help="Isi workbook rekap berdasarkan hasil OCR.")
    parser.add_argument(
        "--rekap-template",
        default="REKAP PENGGUNAAN_BBM_PERIODE_BULAN_NOVEMBER 2025-2.xlsx",
        help="Workbook rekap template yang akan disalin dan diisi.",
    )
    parser.add_argument("--rekap-output", default="output/rekap_terisi.xlsx", help="Path workbook rekap hasil.")
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    rotations = parse_rotations(args.rotations)
    pdf_paths = resolve_pdf_paths(Path(args.input_dir), args.pdf, args.glob)

    pipeline = OcrPipeline(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        dpi=args.dpi,
        force=args.force,
        pdf_paths=pdf_paths,
        rotations=rotations,
    )
    rows = pipeline.run(limit_pages=args.limit_pages)
    export_rows(rows, Path(args.excel))

    print(f"Selesai. {len(rows)} halaman diproses.")
    print(f"Excel: {args.excel}")

    if args.fill_rekap:
        logs = fill_rekap(rows, Path(args.rekap_template), Path(args.rekap_output))
        _print_rekap_summary(logs, args.rekap_output)


def _print_rekap_summary(logs: list, output_path: str) -> None:
    counts: dict[str, int] = {}
    for log in logs:
        s = log.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1

    print(f"\nRekap disimpan ke: {output_path}")
    print("=" * 48)
    print(f"  Terisi              : {counts.get('filled', 0)}")
    print(f"  Terisi sebagian     : {counts.get('partial_fill', 0)}  ← lihat sheet PERLU REVIEW")
    print(f"  Sudah ada isinya    : {counts.get('already_filled', 0)}  ← lihat sheet PERLU REVIEW")
    print(f"  Dilewati (OCR miss) : {counts.get('skipped', 0)}  ← lihat sheet PERLU REVIEW")
    print("=" * 48)

    already_filled = [l for l in logs if l.get("status") == "already_filled"]
    if already_filled:
        print(f"\nKolom sudah terisi ({len(already_filled)} transaksi) — tidak ditimpa:")
        for l in already_filled:
            print(f"  {l.get('tanggal') or '?'} | {l.get('nopol') or '?'} | {l.get('produk') or '?'} — {l.get('reason')}")

    partial = [l for l in logs if l.get("status") == "partial_fill"]
    if partial:
        print(f"\nTerisi sebagian ({len(partial)} transaksi) — isi manual volume/jumlah di Excel:")
        for l in partial:
            print(f"  Baris {l.get('excel_row')} sheet {l.get('sheet')} | {l.get('nopol')} | {l.get('produk')}")

    skipped = [l for l in logs if l.get("status") == "skipped"]
    if skipped:
        print(f"\nDilewati ({len(skipped)} transaksi) — data tidak cukup untuk otomatis:")
        for l in skipped:
            from .rekap_filler import _STATUS_LABELS
            reason_label = _STATUS_LABELS.get(l.get("reason", ""), l.get("reason", ""))
            print(f"  {l.get('tanggal') or '?'} | {l.get('nopol') or '?'} | {reason_label}")


def resolve_pdf_paths(input_dir: Path, explicit_paths: list[str], pattern: str | None) -> list[Path] | None:
    if explicit_paths:
        return [Path(path) for path in explicit_paths]
    if pattern:
        return sorted(input_dir.rglob(pattern))
    return None


def parse_rotations(value: str) -> list[int]:
    rotations = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        rotation = int(item)
        if rotation not in {0, 90, 180, 270}:
            raise ValueError("--rotations hanya boleh berisi 0, 90, 180, 270")
        rotations.append(rotation)
    return rotations or [0]
