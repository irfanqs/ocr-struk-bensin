from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from groq import Groq, RateLimitError


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


def extract_receipt_json(image_paths: list[Path]) -> dict[str, Any]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY belum diisi. Buat .env dari .env.example lalu isi API key.")

    model = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    client = Groq(api_key=api_key)

    content: list[dict[str, Any]] = [{"type": "text", "text": PROMPT}]
    for image_path in image_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(image_path)}"},
            }
        )

    completion = create_with_rate_limit_retry(client, model, content)
    text = completion.choices[0].message.content or "{}"
    return json.loads(text)


def create_with_rate_limit_retry(client: Groq, model: str, content: list[dict[str, Any]]) -> Any:
    for attempt in range(1, 4):
        try:
            return client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                response_format={"type": "json_object"},
                temperature=0,
                max_completion_tokens=2048,
            )
        except RateLimitError as exc:
            wait_seconds = retry_wait_seconds(str(exc))
            if attempt >= 3:
                raise
            print(f"Rate limit Groq. Menunggu {wait_seconds:.0f} detik lalu mencoba lagi...")
            time.sleep(wait_seconds)
    raise RuntimeError("Gagal memanggil Groq setelah retry.")


def retry_wait_seconds(message: str) -> float:
    match = re.search(r"try again in (?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", message, re.IGNORECASE)
    if not match:
        return 60
    minutes = float(match.group(1) or 0)
    seconds = float(match.group(2) or 0)
    return max(5, minutes * 60 + seconds + 2)
