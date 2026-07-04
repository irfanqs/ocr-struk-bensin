from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from openai import OpenAI, RateLimitError

from receipt_ocr.openrouter_client import PROMPT

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def _encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def extract_receipt_json(image_paths: list[Path], model: str | None = None) -> dict[str, Any]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY belum diisi di file .env.")

    model = model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)

    content: list[dict[str, Any]] = [{"type": "text", "text": PROMPT}]
    for image_path in image_paths:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(image_path)}"},
        })

    completion = _create_with_retry(client, model, content)
    raw = completion.choices[0].message.content or "{}"
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
        except RateLimitError:
            if attempt >= 3:
                raise
            wait = 60.0
            print(f"Groq rate limit. Menunggu {wait:.0f}s (percobaan {attempt}/3)...")
            time.sleep(wait)
    raise RuntimeError("Gagal memanggil Groq setelah 3 percobaan.")
