# pdf2md

Production-ready utility to convert PDF into Markdown with extracted images and tables.

## Install

```bash
pip install -r requirements.txt
```

## CLI usage

```bash
python pdf_to_md.py input.pdf --out output.md --assets output_assets --format github --verbose
```

Options:
- --out PATH (default: input.md next to input)
- --assets DIR (default: <out>_assets)
- --format {github,gfm,obsidian}
- --dpi INT (default: 200)
- --ocr {auto,off,always}
- --max-pages INT
- --keep-temp
- --verbose

## Web UI

```bash
python -m pdf2md.webapp
```

Then open http://127.0.0.1:8000

## OCR notes

OCR uses pytesseract and requires the Tesseract binary installed on your system.
If OCR is set to auto, it runs only on pages with low text density and large image areas.

## Output

- output.md: markdown with page separators and inline image/table references
- output_assets/: extracted images and table snapshots

## Limitations and quality tips

- Complex layouts may still require manual cleanup.
- Table extraction uses heuristics; low-quality tables are saved as images.
- Scanned PDFs often benefit from --ocr always and higher --dpi.
