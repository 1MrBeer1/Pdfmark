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

## Развёртывание в локальной сети (Ubuntu / Debian)

На сервере должны быть установлены Docker Engine и Docker Compose (команда
`docker compose`). Скопируйте проект на сервер, например в `/opt/pdf2md`,
и выполните из каталога проекта:

```bash
cd /opt/pdf2md
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100
curl -f http://127.0.0.1:8000/
hostname -I
```

С другого компьютера откройте `http://<IP-сервера-в-локальной-сети>:8000`.
Контейнер автоматически запускается после перезагрузки сервера, если служба
Docker включена (`sudo systemctl enable --now docker`). Образ включает Tesseract
и русские данные OCR.

При необходимости задайте локальный IP сервера и порт в файле `.env` рядом
с `compose.yaml` (без файла сервис слушает все интерфейсы на порту 8000):

```dotenv
PDF2MD_BIND_IP=192.168.1.10
PDF2MD_PORT=8000
```

Подставьте настоящий IP сервера. После изменения `.env` выполните
`sudo docker compose up -d`. Доступ к опубликованному Docker-порту ограничивайте
доверенной локальной сетью на сетевом экране: Docker может обходить обычные
правила UFW для опубликованных портов. Веб-интерфейс не требует авторизации.

Обновление после копирования новой версии проекта:

```bash
sudo docker compose up -d --build
```

Остановка:

```bash
sudo docker compose down
```

Результаты хранятся во временных файлах, а ссылки скачивания — в памяти процесса.
После перезапуска прежние ссылки недоступны; используйте один worker.
Временные файлы накапливаются до удаления контейнера, поэтому следите за местом
на диске; `docker compose down` удаляет контейнер вместе с его результатами.

### Запуск без Docker

```bash
sudo apt-get update
sudo apt-get install -y python3-venv tesseract-ocr tesseract-ocr-rus
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn pdf2md.webapp:app --host 0.0.0.0 --port 8000 --workers 1
```

Для этого варианта разрешите TCP-порт 8000 от вашей локальной подсети в firewall.
Например, при использовании UFW и подсети `192.168.1.0/24`:
`sudo ufw allow from 192.168.1.0/24 to any port 8000 proto tcp`.
Запуск в терминале работает до завершения процесса; для постоянной работы
используйте Docker-вариант выше или службу systemd.

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
