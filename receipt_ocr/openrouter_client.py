from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from openai import OpenAI, RateLimitError


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemma-4-26b-a4b-it:free"

PROMPT = """
Anda adalah OCR dan data extractor untuk struk bensin Indonesia.

Tugas:
- Baca struk dari gambar.
- Gambar dapat buram, pucat, miring, terbalik, atau berisi coretan tangan.
- Saya memberi beberapa varian rotasi dari halaman yang sama. Pilih varian yang paling terbaca.
- Jangan mengarang. Jika field tidak jelas, isi value null, confidence rendah, raw_text potongan yang terlihat, dan notes alasan singkat.
- Angka rupiah dan liter harus dinormalisasi ke number jika yakin.
- Produk biasanya Pertalite, Pertamax, Solar, Dexlite, atau Bio Solar.
- No plat kendaraan adalah field penting. No plat bisa tercetak di struk atau ditulis tangan di area kosong/coretan.
- No plat yang valid untuk pekerjaan ini adalah plat berawalan L, contoh L 1941 OL atau L 9662 NK, dan satu pengecualian AE 8719 SQ.
- Jika ada beberapa kode seperti RFID, ID card, no nota, dan no plat, bedakan no plat dari pola kendaraan tersebut. Jangan isi nopol dengan kode lain.

Keluarkan hanya JSON object valid dengan struktur:
{
  "selected_rotation": 0,
  "spbu": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "tanggal": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "jam": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "no_nota": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "produk": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "harga_per_liter": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "volume_liter": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "total_rupiah": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "rfid": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "nopol": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "operator": {"value": null, "confidence": 0.0, "raw_text": null, "notes": null},
  "needs_review": true,
  "review_reason": "field penting tidak terbaca",
  "full_text": "transkripsi pendek teks yang terbaca"
}

Format tanggal value adalah YYYY-MM-DD jika bisa dipastikan. Jika tahun tidak ada dan tidak bisa dipastikan dari struk, pakai null.
""".strip()


def _encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def extract_receipt_json(image_paths: list[Path], model: str | None = None) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY belum diisi. Isi di file .env.")

    model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    client = OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
    )

    content: list[dict[str, Any]] = [{"type": "text", "text": PROMPT}]
    for image_path in image_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(image_path)}"},
            }
        )

    completion = _create_with_retry(client, model, content)
    raw = completion.choices[0].message.content or "{}"

    # Strip markdown code fences jika model membungkus respons
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    return json.loads(raw)


def _create_with_retry(client: OpenAI, model: str, content: list[dict[str, Any]]) -> Any:
    for attempt in range(1, 4):
        try:
            return client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=0,
                max_tokens=2048,
            )
        except RateLimitError as exc:
            wait = _parse_retry_wait(str(exc))
            if attempt >= 3:
                raise
            print(f"Rate limit. Menunggu {wait:.0f}s lalu mencoba lagi (percobaan {attempt}/3)...")
            time.sleep(wait)
    raise RuntimeError("Gagal memanggil OpenRouter setelah 3 percobaan.")


def _parse_retry_wait(message: str) -> float:
    match = re.search(r"try again in (?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", message, re.IGNORECASE)
    if not match:
        return 60.0
    minutes = float(match.group(1) or 0)
    seconds = float(match.group(2) or 0)
    return max(5.0, minutes * 60 + seconds + 2)
