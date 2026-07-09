# OCR Struk BBM

Program ini membaca PDF struk BBM dari folder `input/`, melakukan OCR dengan AI vision (OpenRouter, fallback otomatis ke Groq), lalu mengisi Excel rekap bulanan.

Alurnya dua tahap, dijalankan sebagai dua program terpisah:

1. **`ocr.py`** — render tiap halaman PDF, kirim ke model vision, simpan hasil mentah sebagai JSON di `output/cache/`.
2. **`export_excel.py`** — baca semua JSON cache, susun jadi Excel hasil OCR, dan (opsional) isi workbook rekap bulanan.

## Persiapan

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pastikan Poppler tersedia karena program memakai `pdfinfo` dan `pdftoppm` untuk render PDF:

```bash
brew install poppler   # macOS
which pdfinfo
which pdftoppm
```

### Windows

Install Python 3 dari [python.org](https://www.python.org/downloads/windows/) (centang "Add python.exe to PATH" saat instalasi), lalu di **PowerShell** atau **Command Prompt**:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Kalau PowerShell menolak menjalankan script aktivasi (`running scripts is disabled on this system`), jalankan sekali sebagai admin:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Poppler tidak tersedia lewat installer resmi di Windows, jadi harus ambil build pihak ketiga:

1. Download build Windows dari [oschwartz10612/poppler-windows releases](https://github.com/oschwartz10612/poppler-windows/releases) (ambil file `Release-xx.xx.x-0.zip`).
2. Extract, misalnya ke `C:\poppler`. Di dalamnya ada folder `Library\bin` yang berisi `pdfinfo.exe` dan `pdftoppm.exe`.
3. Tambahkan folder `bin` tersebut (mis. `C:\poppler\Library\bin`) ke PATH:
   - Search "Edit the system environment variables" → **Environment Variables** → di **User variables**, pilih `Path` → **Edit** → **New** → isi path folder `bin` → OK di semua dialog.
4. Buka terminal baru (supaya PATH ter-refresh), lalu cek:

```powershell
pdfinfo -v
pdftoppm -v
```

Kalau `pip install` untuk Pillow/openpyxl gagal build dari source, pastikan pakai Python versi 64-bit terbaru (3.11/3.12) — semua dependency di `requirements.txt` sudah tersedia sebagai wheel prebuilt untuk Windows sehingga tidak perlu Visual C++ Build Tools.

### Isi API key (semua OS)

```bash
cp .env.example .env
```

Di Windows kalau `cp` tidak dikenali (Command Prompt), pakai:

```powershell
copy .env.example .env
```

Lalu edit `.env` dan isi minimal `OPENROUTER_API_KEY` (model utama). `GROQ_API_KEY` opsional tapi disarankan diisi juga — dipakai otomatis sebagai fallback kalau OpenRouter kena rate limit.

Taruh PDF struk yang mau diproses di dalam `input/`, boleh dikelompokkan per folder bulan (mis. `input/STRUK BBM NOV 2025/`).

> Catatan Windows: semua contoh perintah di README ini pakai `python`. Kalau perintah `python` tidak dikenal di terminal Windows Anda, ganti dengan `py` (mis. `py ocr.py`, `py export_excel.py`).

## Tahap 1 — OCR (`ocr.py`)

Proses semua PDF di `input/`:

```bash
python ocr.py
```

Tes hanya beberapa halaman dulu:

```bash
python ocr.py --limit-pages 5
```

Proses satu PDF tertentu:

```bash
python ocr.py --pdf "input/STRUK BBM NOV 2025/BBM CS NOV BAGUS.pdf"
```

Proses beberapa PDF tertentu (flag `--pdf` bisa dipakai berkali-kali):

```bash
python ocr.py \
  --pdf "input/STRUK BBM NOV 2025/BBM CS NOV BAGUS.pdf" \
  --pdf "input/STRUK BBM NOV 2025/BBM CS NOV BURUK.pdf"
```

Proses PDF berdasarkan pola nama:

```bash
python ocr.py --glob "*NOV*BAGUS.pdf"
```

Hemat token/kuota jika scan sudah tidak terbalik (default kirim 4 rotasi: `0,90,180,270`):

```bash
python ocr.py --pdf "input/STRUK BBM NOV 2025/BBM CS NOV BAGUS.pdf" --rotations 0
```

Proses ulang walaupun JSON cache sudah ada (default: halaman yang sudah punya cache dilewati):

```bash
python ocr.py --force
```

Pilih model OpenRouter tertentu:

```bash
python ocr.py --model google/gemini-2.0-flash-001
```

File dengan `ORI` di namanya otomatis dilewati (dianggap dokumen asli/referensi, bukan struk untuk diproses).

Kalau OpenRouter kena rate limit, `ocr.py` otomatis beralih ke Groq untuk sisa halaman. Kalau Groq juga kena rate limit, program berhenti dan halaman yang belum diproses tetap tercatat statusnya di CSV ringkasan.

Output tahap ini:

- `output/cache/*.json` — hasil OCR mentah per halaman (di-cache, dipakai ulang selama belum `--force`)
- `output/rendered/*.jpg` — gambar hasil render tiap halaman/rotasi
- `output/hasil_ocr.csv` — ringkasan status semua halaman yang diproses

## Tahap 2 — Export ke Excel (`export_excel.py`)

Setelah `ocr.py` selesai, baca cache dan buat Excel hasil OCR:

```bash
python export_excel.py
```

Output: `output/hasil_ocr_struk.xlsx` — satu baris per halaman, lengkap dengan skor `confidence` dan `raw_text` tiap field.

Sekaligus isi workbook rekap bulanan dari hasil OCR:

```bash
python export_excel.py --fill-rekap
```

Program akan menyalin template rekap dan membuat file baru: `output/rekap_terisi.xlsx`. Log pengisian masuk ke sheet `OCR LOG`; baris yang tidak bisa diisi otomatis akan diberi status `skipped` (mis. karena no plat tidak terbaca, kolom tidak ditemukan, atau slot tanggal sudah penuh) — lihat sheet `PERLU REVIEW`.

Kalau ingin memakai cache/template/output sendiri:

```bash
python export_excel.py \
  --cache-dir output/cache \
  --excel output/hasil_ocr_custom.xlsx \
  --fill-rekap \
  --rekap-template "REKAP PENGGUNAAN_BBM_PERIODE_BULAN_NOVEMBER 2025-2.xlsx" \
  --rekap-output output/rekap_terisi.xlsx
```

## Perilaku Untuk Teks Tidak Jelas

Field yang tidak terbaca akan ditulis sebagai `null`, dengan `confidence` rendah dan `raw_text` berisi potongan teks samar jika ada. Baris seperti ini otomatis ditandai `needs_review = TRUE` dan disorot kuning di `hasil_ocr_struk.xlsx`, serta dicatat di sheet `PERLU REVIEW` pada workbook rekap.
