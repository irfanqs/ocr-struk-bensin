from __future__ import annotations

import re
import subprocess
from pathlib import Path


def page_count(pdf_path: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"^Pages:\s+(\d+)\s*$", result.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Tidak bisa membaca jumlah halaman: {pdf_path}")
    return int(match.group(1))


def render_page(pdf_path: Path, page_number: int, output_prefix: Path, dpi: int) -> Path:
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-jpeg",
            "-r",
            str(dpi),
            str(pdf_path),
            str(output_prefix),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = output_prefix.with_name(f"{output_prefix.name}-{page_number}.jpg")
    if not rendered.exists():
        alt = output_prefix.with_name(f"{output_prefix.name}-{page_number:02d}.jpg")
        if alt.exists():
            return alt
        raise RuntimeError(f"Render gagal, file tidak ditemukan untuk {pdf_path} halaman {page_number}")
    return rendered
