# pdf2md

Production-ready utility to convert PDF and Word `.docx` files into Markdown with extracted images and tables.

## Install

```bash
pip install -r requirements.txt
```

## CLI usage

```bash
python pdf_to_md.py input.pdf --out output.md --assets output_assets --format github --verbose
python pdf_to_md.py input.docx --out output.md --assets output_assets --format github
```

Options:
- --out PATH (default: input.md next to input)
- --assets DIR (default: media next to the output)
- --format {github,gfm,obsidian}
- --dpi INT (default: 200, PDF only)
- --ocr {auto,off,always} (PDF only)
- --max-pages INT (PDF only)
- --keep-temp
- --split (split output Markdown by H1 headings)
- --verbose

## Web UI

```bash
python -m pdf2md.webapp
```

Then open http://127.0.0.1:8000 and upload a PDF or Word `.docx` file.

## OCR notes

OCR uses pytesseract and requires the Tesseract binary installed on your system.
If OCR is set to auto, it runs only on pages with low text density and large image areas.

## Output

- output.md: markdown with page separators for PDF files and inline image/table references
- media/: extracted images and table snapshots

## Limitations and quality tips

- Complex layouts may still require manual cleanup.
- Table extraction uses heuristics; low-quality tables are saved as images.
- Scanned PDFs often benefit from --ocr always and higher --dpi.
- Word conversion supports OpenXML Word files (`.docx`, `.docm`, `.dotx`, `.dotm`). Legacy binary `.doc` files should be saved as `.docx` first.
