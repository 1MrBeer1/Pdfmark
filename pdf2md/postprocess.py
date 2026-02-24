"""Post-processing and markdown assembly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from .extract_images import ImageItem
from .extract_tables import TableItem
from .extract_text import TextBlock


@dataclass
class ContentItem:
    kind: str
    y0: float
    x0: float
    text: Optional[str] = None
    rel_path: Optional[str] = None
    alt_text: Optional[str] = None


def assemble_page_markdown(
    page_num: int,
    text_blocks: List[TextBlock],
    images: List[ImageItem],
    tables: List[TableItem],
    md_format: str,
    ocr_used: bool,
) -> str:
    items: List[ContentItem] = []

    for block in text_blocks:
        y0, x0 = _bbox_origin(block.bbox)
        items.append(ContentItem(kind="text", y0=y0, x0=x0, text=block.text))

    for image in images:
        y0, x0 = _bbox_origin(image.bbox)
        items.append(
            ContentItem(
                kind="image",
                y0=y0,
                x0=x0,
                rel_path=image.rel_path,
                alt_text=image.alt_text,
            )
        )

    for table in tables:
        y0, x0 = _bbox_origin(table.bbox)
        if table.kind == "markdown":
            items.append(ContentItem(kind="table_md", y0=y0, x0=x0, text=table.markdown))
        else:
            items.append(
                ContentItem(
                    kind="table_img",
                    y0=y0,
                    x0=x0,
                    rel_path=table.rel_path,
                    alt_text=table.alt_text or f"table page {page_num}",
                )
            )

    items.sort(key=lambda item: (item.y0, item.x0))

    lines: List[str] = [f"<!-- page: {page_num} -->"]
    if ocr_used:
        lines.append("<!-- ocr: true -->")

    for item in items:
        if item.kind == "text" and item.text:
            lines.append(item.text.strip())
        elif item.kind == "image" and item.rel_path:
            lines.append(format_image_link(item.rel_path, item.alt_text or "image", md_format))
        elif item.kind == "table_md" and item.text:
            lines.append(item.text)
        elif item.kind == "table_img" and item.rel_path:
            lines.append(format_image_link(item.rel_path, item.alt_text or "table", md_format))

    return "\n\n".join(lines).strip() + "\n"


def format_image_link(rel_path: str, alt_text: str, md_format: str) -> str:
    if md_format == "obsidian":
        return f"![[{rel_path}|{alt_text}]]"
    return f"![{alt_text}]({rel_path})"


def _bbox_origin(bbox: Optional[Tuple[float, float, float, float]]) -> tuple[float, float]:
    if not bbox:
        return (1e9, 1e9)
    return (bbox[1], bbox[0])
