"""FastAPI web app for pdf2md."""

from __future__ import annotations

import html
import io
from pathlib import Path
from string import Template
import tempfile
import uuid
import zipfile

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .config import ConversionError, DependencyError, setup_logger
from .converter import convert_pdf

app = FastAPI(title="pdf2md")

JOB_STORE: dict[str, dict[str, Path | str]] = {}

INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>pdf2md</title>
  <style>
    :root {
      --bg-a: #f4efe7;
      --bg-b: #e6f2ef;
      --card: #ffffff;
      --ink: #1f2a2e;
      --muted: #5a6a72;
      --accent: #1d6b5b;
      --accent-dark: #154c42;
      --shadow: 0 18px 40px rgba(25, 45, 55, 0.12);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(800px 400px at 10% 10%, #fff4d6 0%, transparent 60%),
        radial-gradient(700px 500px at 90% 20%, #d8f0ff 0%, transparent 65%),
        linear-gradient(140deg, var(--bg-a), var(--bg-b));
      color: var(--ink);
      font-family: "Gill Sans", "Trebuchet MS", "Lucida Sans", sans-serif;
    }
    .wrap {
      max-width: 760px;
      margin: 48px auto;
      padding: 0 20px 40px;
      animation: rise 0.6s ease-out;
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    header h1 {
      letter-spacing: 0.06em;
      text-transform: uppercase;
      font-size: 26px;
      margin-bottom: 8px;
    }
    header p {
      color: var(--muted);
      margin-top: 0;
    }
    .card {
      background: var(--card);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 28px;
    }
    label {
      display: block;
      margin-top: 16px;
      font-weight: 600;
    }
    input, select {
      width: 100%;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid #d6dde2;
      margin-top: 6px;
      font-size: 14px;
    }
    button {
      margin-top: 20px;
      padding: 12px 18px;
      background: var(--accent);
      color: #fff;
      border: none;
      border-radius: 12px;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.03em;
      cursor: pointer;
      transition: transform 0.2s ease, background 0.2s ease;
    }
    button:hover {
      background: var(--accent-dark);
      transform: translateY(-1px);
    }
    .note {
      font-size: 12px;
      color: var(--muted);
      margin-top: 10px;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>pdf2md</h1>
      <p>Convert PDFs to Markdown with inline images and tables.</p>
    </header>
    <div class="card">
      <form action="/convert" method="post" enctype="multipart/form-data">
        <label>PDF file
          <input type="file" name="file" accept="application/pdf" required />
        </label>
        <label>Markdown format
          <select name="md_format">
            <option value="github">github</option>
            <option value="gfm">gfm</option>
            <option value="obsidian">obsidian</option>
          </select>
        </label>
        <label>OCR mode
          <select name="ocr">
            <option value="auto">auto</option>
            <option value="off">off</option>
            <option value="always">always</option>
          </select>
        </label>
        <label>DPI
          <input type="number" name="dpi" value="200" min="72" max="600" />
        </label>
        <button type="submit">Convert</button>
        <div class="note">Large PDFs may take a while. Logs appear after conversion.</div>
      </form>
    </div>
  </div>
</body>
</html>
"""

RESULT_TEMPLATE = Template("""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>pdf2md result</title>
  <style>
    :root {
      --bg-a: #f4efe7;
      --bg-b: #e6f2ef;
      --card: #ffffff;
      --ink: #1f2a2e;
      --muted: #5a6a72;
      --accent: #1d6b5b;
      --shadow: 0 18px 40px rgba(25, 45, 55, 0.12);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(800px 400px at 10% 10%, #fff4d6 0%, transparent 60%),
        radial-gradient(700px 500px at 90% 20%, #d8f0ff 0%, transparent 65%),
        linear-gradient(140deg, var(--bg-a), var(--bg-b));
      color: var(--ink);
      font-family: "Gill Sans", "Trebuchet MS", "Lucida Sans", sans-serif;
    }
    .wrap {
      max-width: 980px;
      margin: 48px auto;
      padding: 0 20px 40px;
      animation: rise 0.6s ease-out;
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .card {
      background: var(--card);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 28px;
      margin-top: 16px;
    }
    a { color: var(--accent); font-weight: 700; }
    pre {
      background: #f5f5f5;
      padding: 12px;
      border-radius: 12px;
      overflow-x: auto;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Conversion complete</h1>
    <div class="card">
      <p><a href="$download_url">Download ZIP</a></p>
      <h2>Report</h2>
      <pre>$report</pre>
      <h2>Log</h2>
      <pre>$log</pre>
      <p><a href="/">Convert another file</a></p>
    </div>
  </div>
</body>
</html>
""")

ERROR_TEMPLATE = Template("""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>pdf2md error</title>
  <style>
    :root {
      --bg-a: #f4efe7;
      --bg-b: #e6f2ef;
      --card: #ffffff;
      --ink: #1f2a2e;
      --accent: #1d6b5b;
      --shadow: 0 18px 40px rgba(25, 45, 55, 0.12);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(800px 400px at 10% 10%, #fff4d6 0%, transparent 60%),
        radial-gradient(700px 500px at 90% 20%, #d8f0ff 0%, transparent 65%),
        linear-gradient(140deg, var(--bg-a), var(--bg-b));
      color: var(--ink);
      font-family: "Gill Sans", "Trebuchet MS", "Lucida Sans", sans-serif;
    }
    .wrap {
      max-width: 980px;
      margin: 48px auto;
      padding: 0 20px 40px;
      animation: rise 0.6s ease-out;
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .card {
      background: var(--card);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 28px;
      margin-top: 16px;
    }
    pre {
      background: #f5f5f5;
      padding: 12px;
      border-radius: 12px;
      overflow-x: auto;
    }
    a { color: var(--accent); font-weight: 700; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Conversion failed</h1>
    <div class="card">
      <pre>$error</pre>
      <h2>Log</h2>
      <pre>$log</pre>
      <p><a href="/">Try again</a></p>
    </div>
  </div>
</body>
</html>
""")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.post("/convert", response_class=HTMLResponse)
def convert(
    file: UploadFile = File(...),
    md_format: str = Form("github"),
    ocr: str = Form("auto"),
    dpi: int = Form(200),
) -> str:
    job_id = uuid.uuid4().hex
    work_dir = Path(tempfile.mkdtemp(prefix=f"pdf2md_{job_id}_"))
    pdf_path = work_dir / "input.pdf"
    out_path = work_dir / "output.md"
    assets_dir = work_dir / "output_assets"

    with pdf_path.open("wb") as f:
        f.write(file.file.read())

    log_stream = io.StringIO()
    logger = setup_logger(name=f"pdf2md.web.{job_id}", verbose=True, stream=log_stream)

    try:
        report = convert_pdf(
            input_path=pdf_path,
            out_path=out_path,
            assets_dir=assets_dir,
            md_format=md_format,
            dpi=int(dpi),
            ocr=ocr,
            keep_temp=False,
            verbose=True,
            logger=logger,
            progress=None,
        )
    except (DependencyError, ConversionError) as exc:
        log_text = html.escape(log_stream.getvalue())
        error_text = html.escape(str(exc))
        return ERROR_TEMPLATE.safe_substitute(error=error_text, log=log_text)
    except Exception as exc:
        log_text = html.escape(log_stream.getvalue())
        error_text = html.escape(f"Unexpected error: {exc}")
        return ERROR_TEMPLATE.safe_substitute(error=error_text, log=log_text)

    zip_path = work_dir / "result.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(out_path, out_path.name)
        if assets_dir.exists():
            for asset in assets_dir.iterdir():
                if asset.is_file():
                    zipf.write(asset, f"{assets_dir.name}/{asset.name}")

    JOB_STORE[job_id] = {"zip_path": zip_path}

    log_text = html.escape(log_stream.getvalue())
    report_text = html.escape(report.summary_text())
    download_url = f"/download/{job_id}"
    return RESULT_TEMPLATE.safe_substitute(download_url=download_url, log=log_text, report=report_text)


@app.get("/download/{job_id}")
def download(job_id: str):
    entry = JOB_STORE.get(job_id)
    if not entry:
        return HTMLResponse("Not found", status_code=404)
    zip_path = entry["zip_path"]
    return FileResponse(path=zip_path, filename="pdf2md_result.zip")


def run() -> None:
    import uvicorn

    uvicorn.run("pdf2md.webapp:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
