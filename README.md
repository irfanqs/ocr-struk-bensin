# OCR Struk BBM dengan Groq

Program ini membaca PDF struk BBM dari folder `input/`, melakukan OCR dengan Groq Vision, menyimpan hasil mentah JSON, lalu membuat Excel baru di folder `output/`.

## Persiapan

Install dependency Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pastikan Poppler tersedia karena program memakai `pdfinfo` dan `pdftoppm` untuk render PDF:

```bash
which pdfinfo
which pdftoppm
```

Isi API key:

```bash
cp .env.example .env
```

Lalu edit `.env` dan isi `GROQ_API_KEY`.

## Cara Pakai

Proses semua PDF:

```bash
python -m receipt_ocr
```

Tes hanya beberapa halaman dulu:

```bash
python -m receipt_ocr --limit-pages 5
```

Proses satu PDF tertentu:

```bash
python -m receipt_ocr --pdf "input/STRUK BBM NOV 2025/BBM CS NOV BAGUS.pdf" --fill-rekap
```

Proses beberapa PDF tertentu:

```bash
python -m receipt_ocr \
  --pdf "input/STRUK BBM NOV 2025/BBM CS NOV BAGUS.pdf" \
  --pdf "input/STRUK BBM NOV 2025/BBM CS NOV BURUK.pdf" \
  --fill-rekap
```

Proses PDF berdasarkan pola nama:

```bash
python -m receipt_ocr --glob "*NOV*BAGUS.pdf" --fill-rekap
```

Hemat token jika scan sudah tidak terbalik:

```bash
python -m receipt_ocr --pdf "input/STRUK BBM NOV 2025/BBM CS NOV BAGUS.pdf" --rotations 0 --fill-rekap
```

Proses ulang walaupun JSON cache sudah ada:

```bash
python -m receipt_ocr --force
```

Output utama:

- `output/hasil_ocr_struk.xlsx`
- `output/cache/*.json`
- `output/rendered/*.jpg`

Isi file rekap bulanan dari hasil OCR:

```bash
python -m receipt_ocr --fill-rekap
```

Program akan membuat salinan workbook baru:

- `output/rekap_terisi.xlsx`

Log pengisian masuk ke sheet `OCR LOG`. Baris yang tidak bisa diisi otomatis akan diberi status `skipped`, misalnya karena no plat tidak terbaca, kolom tidak ditemukan, atau slot tanggal sudah penuh.

Jika ingin memilih template/output sendiri:

```bash
python -m receipt_ocr \
  --fill-rekap \
  --rekap-template "REKAP PENGGUNAAN_BBM_PERIODE_BULAN_NOVEMBER 2025-2.xlsx" \
  --rekap-output output/rekap_terisi.xlsx
```

## Perilaku Untuk Teks Tidak Jelas

Field yang tidak terbaca akan ditulis sebagai `null`, dengan `confidence` rendah dan `raw_text` berisi potongan teks samar jika ada. Baris seperti ini otomatis ditandai `needs_review = TRUE` di Excel.
