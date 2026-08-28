# pdf2md

Production-ready utility to convert PDF, Word `.docx`, and HTML files into Markdown with extracted images and tables.

## Install

```bash
pip install -r requirements.txt
```

## CLI usage

```bash
python pdf_to_md.py input.pdf --out output.md --assets output_assets --format github --verbose
python pdf_to_md.py input.docx --out output.md --assets output_assets --format github
python pdf_to_md.py input.html --out output.md --format vitepress
```

Options:
- --out PATH (default: input.md next to input)
- --assets DIR (PDF/Word assets; HTML always writes images to `./image/` next to the output)
- --format {github,gfm,obsidian,vitepress}
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

Then open http://127.0.0.1:8000 and upload a PDF, Word `.docx`, or HTML file.

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
- Word headings from level two through six receive the same lowercase Latin custom anchors as HTML headings, including deterministic suffixes for duplicate titles.
- Consecutive Word paragraphs using a code style or an all-monospace font such as Consolas are preserved as fenced code blocks with indentation and automatic language labels.
- HTML conversion supports `.html`, `.htm`, and `.xhtml`. If the HTML references a sibling resource folder such as `name-web-resources/`, keep that folder next to the HTML when running the CLI so images can be copied to `./image/` by default.
- Adobe InDesign HTML exports are supported together with their generated CSS: paragraph styles, bold/italic text, super/subscripts, lists, captions, tables, and repeated image references are converted to Markdown where the format allows it.
- Consecutive InDesign `Код` paragraphs are combined into fenced blocks and labeled as `cpp`, `python`, `bash`, or `js` when the language can be identified. Level-two and deeper headings receive lowercase Latin custom anchors.
- Repeated InDesign page headers are removed without deleting the real chapter heading. Printed figure labels such as `Рис. 3.5.` are stripped while the descriptive caption text is preserved.
- `--split` creates `index.md` with VitePress navigation frontmatter, the manual title, a print-edition link, and `.html` links to every generated chapter.
- The `vitepress` format emits VitePress-compatible Markdown, including YAML frontmatter and `[[toc]]` when a source table of contents is detected.
