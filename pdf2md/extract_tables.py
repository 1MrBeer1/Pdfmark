"""Table extraction utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image


@dataclass
class TableItem:
    kind: str  # "markdown" or "image"
    markdown: Optional[str]
    rel_path: Optional[str]
    bbox: Tuple[float, float, float, float]
    alt_text: Optional[str] = None


def extract_tables(
    page_plumber,
    page_fitz,
    assets_dir: Path,
    page_num: int,
    rel_assets_dir: str,
    dpi: int,
    md_format: str,
    temp_dir: Optional[Path] = None,
    logger=None,
) -> List[TableItem]:
    tables: List[TableItem] = []

    table_settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "intersection_tolerance": 5,
        "snap_tolerance": 3,
        "edge_min_length": 3,
        "join_tolerance": 3,
    }

    try:
        found_tables = page_plumber.find_tables(table_settings)
    except Exception as exc:
        if logger:
            logger.warning("Failed to detect tables on page %d: %s", page_num, exc)
        return tables
    if not found_tables:
        return tables

    table_index = 0
    for table in found_tables:
        table_index += 1
        bbox = tuple(table.bbox)
        rows = table.extract() or []
        if not _is_table_quality_good(rows):
            image_item = _render_table_image(
                page_fitz=page_fitz,
                bbox=bbox,
                assets_dir=assets_dir,
                page_num=page_num,
                table_index=table_index,
                rel_assets_dir=rel_assets_dir,
                dpi=dpi,
                temp_dir=temp_dir,
            )
            if image_item:
                tables.append(image_item)
            continue

        markdown = table_to_markdown(rows, md_format)
        if not markdown:
            continue
        tables.append(TableItem(kind="markdown", markdown=markdown, rel_path=None, bbox=bbox))

    return tables


def table_to_markdown(rows: List[List[str]], md_format: str) -> str:
    if not rows:
        return ""

    max_cols = max(len(row) for row in rows if row) if rows else 0
    if max_cols == 0:
        return ""

    normalized = []
    for row in rows:
        row = row or []
        cleaned = [(_clean_cell(cell, md_format) or "") for cell in row]
        if len(cleaned) < max_cols:
            cleaned.extend([""] * (max_cols - len(cleaned)))
        normalized.append(cleaned)

    header = normalized[0]
    separator = ["---"] * max_cols

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]

    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def _clean_cell(cell: Optional[str], md_format: str) -> str:
    if cell is None:
        return ""
    text = " ".join(str(cell).split())
    if "|" in text:
        text = text.replace("|", "\\|")
    return text


def _is_table_quality_good(rows: List[List[str]]) -> bool:
    if not rows:
        return False

    row_lengths = [len(row) for row in rows if row]
    if not row_lengths:
        return False
    max_cols = max(row_lengths)
    if max_cols == 0:
        return False

    total_cells = max_cols * len(rows)
    empty_cells = 0
    ragged_rows = 0
    for row in rows:
        row = row or []
        if len(row) != max_cols:
            ragged_rows += 1
        for idx in range(max_cols):
            cell = row[idx] if idx < len(row) else ""
            if not (str(cell).strip()):
                empty_cells += 1

    empty_ratio = empty_cells / total_cells if total_cells else 1.0
    ragged_ratio = ragged_rows / len(rows) if rows else 1.0

    if empty_ratio > 0.6:
        return False
    if ragged_ratio > 0.4:
        return False

    return True


def _render_table_image(
    page_fitz,
    bbox: Tuple[float, float, float, float],
    assets_dir: Path,
    page_num: int,
    table_index: int,
    rel_assets_dir: str,
    dpi: int,
    temp_dir: Optional[Path],
) -> Optional[TableItem]:
    try:
        import fitz  # type: ignore
    except Exception:
        return None

    zoom = dpi / 72.0
    pix = page_fitz.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    left = max(0, int(bbox[0] * zoom))
    top = max(0, int(bbox[1] * zoom))
    right = min(image.width, int(bbox[2] * zoom))
    bottom = min(image.height, int(bbox[3] * zoom))
    if right <= left or bottom <= top:
        return None

    cropped = image.crop((left, top, right, bottom))
    filename = f"page_{page_num}_table_{table_index}.png"
    out_path = assets_dir / filename
    cropped.save(out_path, format="PNG")

    if temp_dir:
        temp_path = temp_dir / f"page_{page_num}_table_{table_index}_full.png"
        image.save(temp_path, format="PNG")

    rel_path = _join_rel_path(rel_assets_dir, filename)
    alt_text = f"table page {page_num} {table_index}"
    return TableItem(kind="image", markdown=None, rel_path=rel_path, bbox=bbox, alt_text=alt_text)


def _join_rel_path(rel_dir: str, filename: str) -> str:
    if not rel_dir:
        return filename
    return f"{rel_dir}/{filename}".replace("\\", "/")
