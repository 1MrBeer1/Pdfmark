"""Word document conversion utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import itertools
import logging
import posixpath
import re
import zipfile
from typing import Iterator, Optional
import xml.etree.ElementTree as ET

from .config import ConversionError, SUPPORTED_FORMATS, resolve_output_paths
from .postprocess import format_image_link
from .report import ConversionReport, PageReport

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

DOCUMENT_PART = "word/document.xml"
DOCUMENT_RELS_PART = "word/_rels/document.xml.rels"

ORDERED_NUMBER_FORMATS = {
    "decimal",
    "upperRoman",
    "lowerRoman",
    "upperLetter",
    "lowerLetter",
    "ordinal",
    "cardinalText",
}


@dataclass
class Relationship:
    rel_id: str
    rel_type: str
    target: str
    target_mode: str | None = None


@dataclass
class ParagraphStyle:
    style_id: str
    name: str = ""
    heading_level: int | None = None


@dataclass
class Numbering:
    num_to_abstract: dict[str, str] = field(default_factory=dict)
    abstract_level_formats: dict[tuple[str, str], str] = field(default_factory=dict)

    def format_for(self, num_id: str, ilvl: str) -> str | None:
        abstract_id = self.num_to_abstract.get(num_id)
        if abstract_id is None:
            return None
        return self.abstract_level_formats.get((abstract_id, ilvl))


class ImageExtractor:
    def __init__(
        self,
        archive: zipfile.ZipFile,
        relationships: dict[str, Relationship],
        assets_dir: Path,
        rel_assets_dir: str,
        counter: Iterator[int],
    ) -> None:
        self.archive = archive
        self.relationships = relationships
        self.assets_dir = assets_dir
        self.rel_assets_dir = rel_assets_dir
        self.counter = counter
        self._saved: dict[str, str] = {}

    @property
    def saved_count(self) -> int:
        return len(self._saved)

    def markdown_link(self, rel_id: str | None, md_format: str) -> str:
        if not rel_id:
            return ""
        rel = self.relationships.get(rel_id)
        if not rel or rel.target_mode == "External":
            return ""
        if "/image" not in rel.rel_type:
            return ""

        rel_path = self._saved.get(rel_id)
        if rel_path is None:
            try:
                data = self.archive.read(rel.target)
            except KeyError:
                return ""
            extension = _safe_image_extension(rel.target)
            filename = f"img_{next(self.counter):04d}{extension}"
            output_path = self.assets_dir / filename
            output_path.write_bytes(data)
            rel_path = _join_rel_path(self.rel_assets_dir, filename)
            self._saved[rel_id] = rel_path

        alt_text = Path(rel.target).stem or "image"
        return format_image_link(rel_path, alt_text, md_format)


def convert_docx(
    input_path: Path | str,
    out_path: Optional[Path | str] = None,
    assets_dir: Optional[Path | str] = None,
    md_format: str = "github",
    max_pages: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
    progress=None,
) -> ConversionReport:
    del max_pages

    input_path = Path(input_path)
    out_path, assets_dir = resolve_output_paths(
        input_path,
        Path(out_path) if out_path else None,
        Path(assets_dir) if assets_dir else None,
    )

    if md_format not in SUPPORTED_FORMATS:
        raise ConversionError(f"Unsupported format: {md_format}")
    if not input_path.exists():
        raise ConversionError(f"Input file not found: {input_path}")

    logger = logger or logging.getLogger("pdf2md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Converting %s -> %s", input_path, out_path)

    try:
        with zipfile.ZipFile(input_path) as archive:
            document = _read_xml(archive, DOCUMENT_PART)
            relationships = _read_relationships(archive, DOCUMENT_RELS_PART, DOCUMENT_PART)
            styles = _read_styles(archive)
            numbering = _read_numbering(archive)

            rel_assets_dir = _relative_assets_dir(out_path, assets_dir)
            image_extractor = ImageExtractor(
                archive=archive,
                relationships=relationships,
                assets_dir=assets_dir,
                rel_assets_dir=rel_assets_dir,
                counter=itertools.count(1),
            )

            markdown_parts: list[str] = []
            tables_count = 0
            body = document.find(f"{W}body")
            if body is not None:
                for child in body:
                    if child.tag == f"{W}p":
                        paragraph_md = _paragraph_to_markdown(
                            child,
                            relationships,
                            styles,
                            numbering,
                            image_extractor,
                            md_format,
                        )
                        if paragraph_md:
                            markdown_parts.append(paragraph_md)
                    elif child.tag == f"{W}tbl":
                        table_md = _table_to_markdown(child, md_format)
                        if table_md:
                            tables_count += 1
                            markdown_parts.append(table_md)

            markdown = "\n\n".join(markdown_parts).strip()
            out_path.write_text((markdown + "\n") if markdown else "", encoding="utf-8")
    except zipfile.BadZipFile as exc:
        raise ConversionError(f"Failed to open Word file: {input_path}") from exc
    except ET.ParseError as exc:
        raise ConversionError(f"Failed to parse Word document XML: {input_path}") from exc
    except KeyError as exc:
        raise ConversionError(f"Word document is missing required part: {exc}") from exc

    report = ConversionReport(processed_label="documents")
    report.add_page(
        PageReport(
            page_number=1,
            text_chars=len(markdown),
            images=image_extractor.saved_count,
            tables_markdown=tables_count,
            tables_images=0,
            ocr_used=False,
        )
    )
    if progress is not None:
        progress.update(1)

    logger.info(
        "Document: chars=%d images=%d tables_md=%d",
        len(markdown),
        image_extractor.saved_count,
        tables_count,
    )
    logger.info("Saved markdown to %s", out_path)
    return report


def _paragraph_to_markdown(
    paragraph: ET.Element,
    relationships: dict[str, Relationship],
    styles: dict[str, ParagraphStyle],
    numbering: Numbering,
    image_extractor: ImageExtractor,
    md_format: str,
) -> str:
    parts: list[str] = []
    for child in paragraph:
        if child.tag == f"{W}r":
            parts.append(_run_to_markdown(child, image_extractor, md_format))
        elif child.tag == f"{W}hyperlink":
            parts.append(_hyperlink_to_markdown(child, relationships, image_extractor, md_format))

    content = _normalize_inline_text("".join(parts))
    if not content:
        return ""

    p_pr = paragraph.find(f"{W}pPr")
    heading_level = _paragraph_heading_level(p_pr, styles)
    if heading_level:
        return f"{'#' * heading_level} {_strip_outer_emphasis(content)}"

    numbering_info = _paragraph_numbering(p_pr)
    if numbering_info:
        num_id, ilvl = numbering_info
        num_format = numbering.format_for(num_id, ilvl) or "bullet"
        level = max(0, int(ilvl)) if ilvl.isdigit() else 0
        marker = "1." if num_format in ORDERED_NUMBER_FORMATS else "-"
        return f"{'  ' * level}{marker} {content}"

    style_id = _paragraph_style_id(p_pr)
    if style_id and "list" in style_id.lower():
        return f"- {content}"

    return content


def _run_to_markdown(run: ET.Element, image_extractor: ImageExtractor, md_format: str) -> str:
    text = _run_text(run)
    parts: list[str] = []
    if text:
        bold, italic = _run_style(run)
        parts.append(_wrap_text(text, bold, italic))

    for blip in run.iter(f"{A}blip"):
        rel_id = blip.get(f"{R}embed") or blip.get(f"{R}link")
        image_link = image_extractor.markdown_link(rel_id, md_format)
        if image_link:
            parts.append(image_link)

    if len(parts) > 1 and any(part.startswith("![") or part.startswith("![[") for part in parts[1:]):
        return "\n".join(parts)
    return "".join(parts)


def _hyperlink_to_markdown(
    hyperlink: ET.Element,
    relationships: dict[str, Relationship],
    image_extractor: ImageExtractor,
    md_format: str,
) -> str:
    content = "".join(_run_to_markdown(run, image_extractor, md_format) for run in hyperlink.findall(f"{W}r"))
    content = _normalize_inline_text(content)
    if not content:
        return ""

    rel_id = hyperlink.get(f"{R}id")
    anchor = hyperlink.get(f"{W}anchor")
    rel = relationships.get(rel_id or "")
    if rel and rel.target:
        return f"[{_escape_link_text(content)}]({rel.target})"
    if anchor:
        return f"[{_escape_link_text(content)}](#{anchor})"
    return content


def _table_to_markdown(table: ET.Element, md_format: str) -> str:
    rows: list[list[str]] = []
    for tr in table.findall(f"{W}tr"):
        row: list[str] = []
        for tc in tr.findall(f"{W}tc"):
            text = _cell_text(tc)
            row.append(_clean_table_cell(text, md_format))
        if row:
            rows.append(row)

    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    if max_cols == 0:
        return ""

    normalized: list[list[str]] = []
    for row in rows:
        padded = row + [""] * (max_cols - len(row))
        normalized.append(padded)

    header = normalized[0]
    separator = ["---"] * max_cols
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _cell_text(cell: ET.Element) -> str:
    paragraphs: list[str] = []
    for paragraph in cell.findall(f"{W}p"):
        text = _plain_text(paragraph)
        if text:
            paragraphs.append(text)
    return " ".join(paragraphs)


def _plain_text(element: ET.Element) -> str:
    parts: list[str] = []
    for item in element.iter():
        if item.tag == f"{W}t":
            parts.append(item.text or "")
        elif item.tag == f"{W}tab":
            parts.append("\t")
        elif item.tag == f"{W}br":
            parts.append(" ")
    return _normalize_inline_text("".join(parts))


def _run_text(run: ET.Element) -> str:
    parts: list[str] = []
    for item in run.iter():
        if item.tag == f"{W}t":
            parts.append(item.text or "")
        elif item.tag == f"{W}tab":
            parts.append("\t")
        elif item.tag == f"{W}br":
            parts.append("\n")
    return "".join(parts)


def _run_style(run: ET.Element) -> tuple[bool, bool]:
    r_pr = run.find(f"{W}rPr")
    if r_pr is None:
        return False, False
    return _is_enabled(r_pr.find(f"{W}b")), _is_enabled(r_pr.find(f"{W}i"))


def _is_enabled(element: ET.Element | None) -> bool:
    if element is None:
        return False
    value = element.get(f"{W}val")
    return value is None or value.lower() not in {"0", "false", "off", "none"}


def _wrap_text(text: str, bold: bool, italic: bool) -> str:
    if not text.strip():
        return text
    marker = ""
    if bold and italic:
        marker = "***"
    elif bold:
        marker = "**"
    elif italic:
        marker = "*"
    if not marker:
        return text

    prefix_len = len(text) - len(text.lstrip())
    suffix_len = len(text) - len(text.rstrip())
    prefix = text[:prefix_len]
    core = text[prefix_len:len(text) - suffix_len] if suffix_len else text[prefix_len:]
    suffix = text[len(text) - suffix_len:] if suffix_len else ""
    return f"{prefix}{marker}{core}{marker}{suffix}"


def _paragraph_heading_level(p_pr: ET.Element | None, styles: dict[str, ParagraphStyle]) -> int | None:
    if p_pr is not None:
        outline = p_pr.find(f"{W}outlineLvl")
        if outline is not None:
            value = outline.get(f"{W}val")
            if value and value.isdigit():
                return min(int(value) + 1, 6)

    style_id = _paragraph_style_id(p_pr)
    if not style_id:
        return None

    style = styles.get(style_id)
    if style and style.heading_level:
        return style.heading_level

    normalized = re.sub(r"[\s_-]+", "", style_id).lower()
    heading_match = re.match(r"heading([1-6])$", normalized)
    if heading_match:
        return int(heading_match.group(1))
    if normalized == "title":
        return 1
    return None


def _paragraph_style_id(p_pr: ET.Element | None) -> str | None:
    if p_pr is None:
        return None
    style = p_pr.find(f"{W}pStyle")
    return style.get(f"{W}val") if style is not None else None


def _paragraph_numbering(p_pr: ET.Element | None) -> tuple[str, str] | None:
    if p_pr is None:
        return None
    num_pr = p_pr.find(f"{W}numPr")
    if num_pr is None:
        return None
    num_id_element = num_pr.find(f"{W}numId")
    if num_id_element is None:
        return None
    num_id = num_id_element.get(f"{W}val")
    if not num_id:
        return None
    ilvl_element = num_pr.find(f"{W}ilvl")
    ilvl = ilvl_element.get(f"{W}val") if ilvl_element is not None else "0"
    return num_id, ilvl or "0"


def _read_xml(archive: zipfile.ZipFile, part_name: str) -> ET.Element:
    return ET.fromstring(archive.read(part_name))


def _read_relationships(
    archive: zipfile.ZipFile,
    relationships_part: str,
    source_part: str,
) -> dict[str, Relationship]:
    try:
        root = _read_xml(archive, relationships_part)
    except KeyError:
        return {}

    relationships: dict[str, Relationship] = {}
    for rel in root.findall(f"{REL}Relationship"):
        rel_id = rel.get("Id")
        target = rel.get("Target")
        rel_type = rel.get("Type") or ""
        target_mode = rel.get("TargetMode")
        if not rel_id or not target:
            continue
        if target_mode != "External":
            target = _resolve_part_path(source_part, target)
        relationships[rel_id] = Relationship(rel_id, rel_type, target, target_mode)
    return relationships


def _read_styles(archive: zipfile.ZipFile) -> dict[str, ParagraphStyle]:
    try:
        root = _read_xml(archive, "word/styles.xml")
    except KeyError:
        return {}

    styles: dict[str, ParagraphStyle] = {}
    for style in root.findall(f"{W}style"):
        if style.get(f"{W}type") != "paragraph":
            continue
        style_id = style.get(f"{W}styleId")
        if not style_id:
            continue
        name_element = style.find(f"{W}name")
        name = name_element.get(f"{W}val") if name_element is not None else ""
        heading_level = _style_heading_level(style_id, name, style)
        styles[style_id] = ParagraphStyle(style_id=style_id, name=name or "", heading_level=heading_level)
    return styles


def _style_heading_level(style_id: str, name: str, style: ET.Element) -> int | None:
    p_pr = style.find(f"{W}pPr")
    if p_pr is not None:
        outline = p_pr.find(f"{W}outlineLvl")
        if outline is not None:
            value = outline.get(f"{W}val")
            if value and value.isdigit():
                return min(int(value) + 1, 6)

    for candidate in (style_id, name):
        normalized = re.sub(r"[\s_-]+", "", candidate).lower()
        heading_match = re.match(r"heading([1-6])$", normalized)
        if heading_match:
            return int(heading_match.group(1))
        if normalized == "title":
            return 1
    return None


def _read_numbering(archive: zipfile.ZipFile) -> Numbering:
    try:
        root = _read_xml(archive, "word/numbering.xml")
    except KeyError:
        return Numbering()

    numbering = Numbering()
    for abstract in root.findall(f"{W}abstractNum"):
        abstract_id = abstract.get(f"{W}abstractNumId")
        if not abstract_id:
            continue
        for level in abstract.findall(f"{W}lvl"):
            ilvl = level.get(f"{W}ilvl") or "0"
            fmt_element = level.find(f"{W}numFmt")
            fmt = fmt_element.get(f"{W}val") if fmt_element is not None else None
            if fmt:
                numbering.abstract_level_formats[(abstract_id, ilvl)] = fmt

    for num in root.findall(f"{W}num"):
        num_id = num.get(f"{W}numId")
        abstract_id_element = num.find(f"{W}abstractNumId")
        abstract_id = abstract_id_element.get(f"{W}val") if abstract_id_element is not None else None
        if num_id and abstract_id:
            numbering.num_to_abstract[num_id] = abstract_id

    return numbering


def _resolve_part_path(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    base = posixpath.dirname(source_part)
    return posixpath.normpath(posixpath.join(base, target))


def _safe_image_extension(part_name: str) -> str:
    extension = Path(part_name).suffix.lower()
    if extension in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".emf", ".wmf"}:
        return extension
    return ".bin"


def _relative_assets_dir(out_path: Path, assets_dir: Path) -> str:
    try:
        rel = assets_dir.relative_to(out_path.parent)
    except ValueError:
        try:
            import os

            rel = Path(os.path.relpath(assets_dir, out_path.parent))
        except ValueError:
            rel = assets_dir
    return str(rel).replace("\\", "/")


def _join_rel_path(rel_dir: str, filename: str) -> str:
    if not rel_dir:
        return filename
    return f"{rel_dir}/{filename}".replace("\\", "/")


def _normalize_inline_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


def _strip_outer_emphasis(text: str) -> str:
    for marker in ("***", "**", "*"):
        if text.startswith(marker) and text.endswith(marker) and len(text) > len(marker) * 2:
            return text[len(marker):-len(marker)].strip()
    return text


def _clean_table_cell(cell: str, md_format: str) -> str:
    del md_format
    text = " ".join(cell.split())
    return text.replace("|", "\\|")


def _escape_link_text(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")
