from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .groq_client import extract_receipt_json
from .image_tools import make_rotation_variants
from .pdf_tools import page_count, render_page
from .rekap_filler import normalize_plate


REQUIRED_FIELDS = ("tanggal", "produk", "volume_liter", "total_rupiah")


@dataclass
class OcrPipeline:
    input_dir: Path
    output_dir: Path
    dpi: int = 220
    force: bool = False
    pdf_paths: list[Path] | None = None
    rotations: list[int] | None = None

    @property
    def cache_dir(self) -> Path:
        return self.output_dir / "cache"

    @property
    def rendered_dir(self) -> Path:
        return self.output_dir / "rendered"

    def run(self, limit_pages: int | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        processed = 0

        for pdf_path in self.iter_pdf_paths():
            total_pages = page_count(pdf_path)
            for page_number in range(1, total_pages + 1):
                if limit_pages is not None and processed >= limit_pages:
                    return rows

                print(f"OCR {pdf_path} halaman {page_number}/{total_pages}")
                row = self.process_page(pdf_path, page_number)
                rows.append(row)
                processed += 1

        return rows

    def process_page(self, pdf_path: Path, page_number: int) -> dict[str, Any]:
        cache_path = self.cache_path(pdf_path, page_number)
        if cache_path.exists() and not self.force:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            data = self.ocr_page(pdf_path, page_number)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        row = flatten_result(data)
        row.update(
            {
                "source_pdf": str(pdf_path),
                "source_folder": str(pdf_path.parent),
                "page": page_number,
                "cache_json": str(cache_path),
            }
        )
        return row

    def ocr_page(self, pdf_path: Path, page_number: int) -> dict[str, Any]:
        safe_stem = slugify(f"{pdf_path.parent.name}_{pdf_path.stem}_p{page_number}")
        rendered = render_page(
            pdf_path=pdf_path,
            page_number=page_number,
            output_prefix=self.rendered_dir / safe_stem,
            dpi=self.dpi,
        )
        variants = make_rotation_variants(rendered, self.rendered_dir, safe_stem, self.rotations)
        return extract_receipt_json(variants)

    def cache_path(self, pdf_path: Path, page_number: int) -> Path:
        safe_stem = slugify(f"{pdf_path.parent.name}_{pdf_path.stem}_p{page_number}")
        return self.cache_dir / f"{safe_stem}.json"

    def iter_pdf_paths(self) -> list[Path]:
        if self.pdf_paths:
            return sorted(self.pdf_paths)
        return sorted(self.input_dir.rglob("*.pdf"))


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def flatten_result(data: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "selected_rotation": data.get("selected_rotation"),
        "needs_review": bool(data.get("needs_review", True)),
        "review_reason": data.get("review_reason"),
        "full_text": data.get("full_text"),
    }

    for field in (
        "spbu",
        "tanggal",
        "jam",
        "no_nota",
        "produk",
        "harga_per_liter",
        "volume_liter",
        "total_rupiah",
        "rfid",
        "nopol",
        "operator",
    ):
        item = data.get(field) if isinstance(data.get(field), dict) else {}
        row[field] = item.get("value")
        row[f"{field}_confidence"] = item.get("confidence")
        row[f"{field}_raw_text"] = item.get("raw_text") or item.get("value")
        row[f"{field}_notes"] = item.get("notes")

    row["nopol"] = normalize_plate(row.get("nopol"))

    if not row["needs_review"]:
        row["needs_review"] = any(_is_low_confidence(data.get(field)) for field in REQUIRED_FIELDS)
        if row["needs_review"] and not row["review_reason"]:
            row["review_reason"] = "field penting kosong atau confidence rendah"

    return row


def _is_low_confidence(item: Any) -> bool:
    if not isinstance(item, dict):
        return True
    if item.get("value") in (None, ""):
        return True
    confidence = item.get("confidence")
    try:
        return float(confidence) < 0.75
    except (TypeError, ValueError):
        return True
