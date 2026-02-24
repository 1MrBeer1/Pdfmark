"""PDF conversion orchestration."""

from __future__ import annotations

from pathlib import Path
import logging
import os
import tempfile
import itertools
from typing import Optional

from PIL import Image

from .config import ConversionConfig, ConversionError, DependencyError, SUPPORTED_FORMATS, SUPPORTED_OCR, resolve_output_paths
from .extract_text import extract_text_blocks, estimate_image_area_ratio, TextBlock
from .extract_images import extract_images
from .extract_tables import extract_tables
from .postprocess import assemble_page_markdown
from .report import ConversionReport, PageReport


def convert_pdf(
    input_path: Path | str,
    out_path: Optional[Path | str] = None,
    assets_dir: Optional[Path | str] = None,
    md_format: str = "github",
    dpi: int = 200,
    ocr: str = "auto",
    max_pages: Optional[int] = None,
    keep_temp: bool = False,
    verbose: bool = False,
    logger: Optional[logging.Logger] = None,
    progress=None,
) -> ConversionReport:
    input_path = Path(input_path)
    out_path, assets_dir = resolve_output_paths(input_path, Path(out_path) if out_path else None, Path(assets_dir) if assets_dir else None)
    config = ConversionConfig(
        out_path=out_path,
        assets_dir=assets_dir,
        md_format=md_format,
        dpi=dpi,
        ocr=ocr,
        max_pages=max_pages,
        keep_temp=keep_temp,
        verbose=verbose,
    )
    return _convert_with_config(input_path, config, logger=logger, progress=progress)


def _convert_with_config(
    input_path: Path,
    config: ConversionConfig,
    logger: Optional[logging.Logger] = None,
    progress=None,
) -> ConversionReport:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise DependencyError("PyMuPDF (fitz) is required. Install with: pip install pymupdf") from exc

    try:
        import pdfplumber  # type: ignore
    except Exception as exc:
        raise DependencyError("pdfplumber is required. Install with: pip install pdfplumber") from exc

    if not input_path.exists():
        raise ConversionError(f"Input file not found: {input_path}")
    if config.md_format not in SUPPORTED_FORMATS:
        raise ConversionError(f"Unsupported format: {config.md_format}")
    if config.ocr not in SUPPORTED_OCR:
        raise ConversionError(f"Unsupported OCR mode: {config.ocr}")

    logger = logger or logging.getLogger("pdf2md")

    config.out_path.parent.mkdir(parents=True, exist_ok=True)
    config.assets_dir.mkdir(parents=True, exist_ok=True)

    report = ConversionReport()
    logger.info("Converting %s -> %s", input_path, config.out_path)

    temp_dir = None
    if config.keep_temp:
        temp_dir = Path(tempfile.mkdtemp(prefix="pdf2md_"))
        logger.info("Keeping temp files in %s", temp_dir)

    try:
        doc = fitz.open(input_path)
    except Exception as exc:
        raise ConversionError(f"Failed to open PDF: {input_path}") from exc

    try:
        plumber = pdfplumber.open(str(input_path))
    except Exception as exc:
        doc.close()
        raise ConversionError(f"Failed to open PDF with pdfplumber: {input_path}") from exc

    try:
        total_pages = doc.page_count
        if config.max_pages:
            total_pages = min(total_pages, config.max_pages)

        assets_rel_dir = _relative_assets_dir(config.out_path, config.assets_dir)
        page_markdown: list[str] = []
        image_counter = itertools.count(1)
        table_counter = itertools.count(1)

        for page_index in range(total_pages):
            page_num = page_index + 1
            page = doc.load_page(page_index)
            page_plumber = plumber.pages[page_index]

            page_dict = page.get_text("dict")
            text_blocks = extract_text_blocks(page_dict)
            raw_text_chars = sum(len(block.text) for block in text_blocks)

            page_area = page.rect.width * page.rect.height
            image_ratio, image_blocks = estimate_image_area_ratio(page_dict, page_area)

            ocr_used = _should_use_ocr(config.ocr, raw_text_chars, image_ratio, image_blocks, config)
            if ocr_used:
                ocr_text = _run_ocr(page, config, logger)
                if ocr_text:
                    text_blocks.insert(0, TextBlock(text=ocr_text.strip(), bbox=(0, 0, 0, 0), heading_level=None))

            text_chars = sum(len(block.text) for block in text_blocks)

            images = extract_images(
                doc,
                page,
                config.assets_dir,
                page_num,
                text_blocks,
                assets_rel_dir,
                logger=logger,
                counter=image_counter,
            )
            tables = extract_tables(
                page_plumber,
                page,
                config.assets_dir,
                page_num,
                assets_rel_dir,
                config.dpi,
                config.md_format,
                temp_dir=temp_dir,
                logger=logger,
                counter=table_counter,
            )

            page_md = assemble_page_markdown(
                page_num=page_num,
                text_blocks=text_blocks,
                images=images,
                tables=tables,
                md_format=config.md_format,
                ocr_used=ocr_used,
            )
            page_markdown.append(page_md)

            tables_md = sum(1 for table in tables if table.kind == "markdown")
            tables_img = sum(1 for table in tables if table.kind == "image")

            report.add_page(
                PageReport(
                    page_number=page_num,
                    text_chars=text_chars,
                    images=len(images),
                    tables_markdown=tables_md,
                    tables_images=tables_img,
                    ocr_used=ocr_used,
                )
            )

            logger.info(
                "Page %d: chars=%d images=%d tables_md=%d tables_img=%d ocr=%s",
                page_num,
                text_chars,
                len(images),
                tables_md,
                tables_img,
                "yes" if ocr_used else "no",
            )

            if progress is not None:
                progress.update(1)

        config.out_path.write_text("\n".join(page_markdown), encoding="utf-8")
        logger.info("Saved markdown to %s", config.out_path)

    finally:
        plumber.close()
        doc.close()
        # No temp cleanup needed unless files were created.

    return report


def _relative_assets_dir(out_path: Path, assets_dir: Path) -> str:
    try:
        rel = os.path.relpath(assets_dir, out_path.parent)
    except ValueError:
        rel = str(assets_dir)
    return rel.replace("\\", "/")


def _should_use_ocr(ocr_mode: str, text_chars: int, image_ratio: float, image_blocks: int, config: ConversionConfig) -> bool:
    if ocr_mode == "off":
        return False
    if ocr_mode == "always":
        return True
    if text_chars < config.ocr_min_chars and (image_ratio >= config.ocr_image_area_ratio or image_blocks > 0):
        return True
    return False


def _run_ocr(page, config: ConversionConfig, logger: logging.Logger) -> str:
    try:
        import pytesseract  # type: ignore
    except Exception as exc:
        raise DependencyError("pytesseract is required for OCR. Install with: pip install pytesseract") from exc

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise DependencyError("Tesseract OCR binary not found. Install tesseract and ensure it is in PATH.") from exc

    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise DependencyError("PyMuPDF (fitz) is required for OCR rendering.") from exc

    zoom = config.dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    try:
        text = pytesseract.image_to_string(image, timeout=config.ocr_timeout_seconds)
    except TypeError:
        text = pytesseract.image_to_string(image)
    except Exception as exc:
        logger.warning("OCR failed: %s", exc)
        return ""

    return text
