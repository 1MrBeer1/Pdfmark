"""Text extraction utilities."""

from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import median
from typing import Iterable, List, Tuple

LIST_ITEM_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+\.)\s+")
PAGE_NUM_RE = re.compile(r"^(?:стр\.?\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?$", re.IGNORECASE)


@dataclass
class TextBlock:
    text: str
    bbox: Tuple[float, float, float, float]
    heading_level: int | None


def extract_text_blocks(page_dict: dict) -> List[TextBlock]:
    blocks = page_dict.get("blocks", [])
    sizes = _collect_span_sizes(blocks)
    body_size = median(sizes) if sizes else 12.0
    text_blocks: List[TextBlock] = []

    for block in blocks:
        if block.get("type") != 0:
            continue
        bbox = tuple(block.get("bbox", (0, 0, 0, 0)))
        lines_text, max_size, bold_ratio = _extract_block_lines(block)
        if not lines_text:
            continue
        normalized = _normalize_lines(lines_text)
        if not normalized.strip():
            continue
        if _is_page_number(normalized):
            continue
        heading_level = _classify_heading(max_size, body_size, normalized, bold_ratio)
        if heading_level:
            normalized = _apply_heading(normalized, heading_level)
        text_blocks.append(TextBlock(text=normalized, bbox=bbox, heading_level=heading_level))

    text_blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
    return text_blocks


def estimate_image_area_ratio(page_dict: dict, page_area: float) -> tuple[float, int]:
    blocks = page_dict.get("blocks", [])
    total_area = 0.0
    image_blocks = 0
    for block in blocks:
        if block.get("type") != 1:
            continue
        bbox = block.get("bbox", (0, 0, 0, 0))
        width = max(0.0, bbox[2] - bbox[0])
        height = max(0.0, bbox[3] - bbox[1])
        total_area += width * height
        image_blocks += 1
    ratio = (total_area / page_area) if page_area > 0 else 0.0
    return ratio, image_blocks


def _collect_span_sizes(blocks: Iterable[dict]) -> List[float]:
    sizes: List[float] = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = span.get("size")
                if size:
                    sizes.append(size)
    return sizes


def _extract_block_lines(block: dict) -> tuple[List[str], float, float]:
    lines_text: List[str] = []
    max_size = 0.0
    bold_chars = 0
    total_chars = 0
    for line in block.get("lines", []):
        segments: List[tuple[tuple[bool, bool], str]] = []
        current_style: tuple[bool, bool] | None = None
        current_text = ""
        prev_span = None
        for span in line.get("spans", []):
            text = span.get("text") or ""
            if not text:
                continue
            size = span.get("size") or 0.0
            max_size = max(max_size, size)
            bold, italic = _span_style(span)
            if prev_span is not None and _needs_space(prev_span, span):
                text = " " + text
            style = (bold, italic)
            if style == current_style:
                current_text += text
            else:
                if current_text:
                    segments.append((current_style or (False, False), current_text))
                current_style = style
                current_text = text
            prev_span = span
            raw = text.strip()
            if raw:
                total_chars += len(raw)
                if bold:
                    bold_chars += len(raw)
        if current_text:
            segments.append((current_style or (False, False), current_text))

        line_text = "".join(_wrap_text(seg_text, style) for style, seg_text in segments).strip()
        if line_text:
            lines_text.append(line_text)

    bold_ratio = (bold_chars / total_chars) if total_chars else 0.0
    return lines_text, max_size, bold_ratio


def _normalize_lines(lines: List[str]) -> str:
    lines = _fix_hyphenation(lines)
    merged_lines: List[str] = []
    buffer = ""

    for line in lines:
        line = line.strip()
        if not line:
            if buffer:
                merged_lines.append(buffer)
                buffer = ""
            continue

        if _is_list_item(line):
            if buffer:
                merged_lines.append(buffer)
                buffer = ""
            merged_lines.append(line)
            continue

        if buffer:
            if _should_join(buffer, line):
                buffer = f"{buffer} {line}"
            else:
                merged_lines.append(buffer)
                buffer = line
        else:
            buffer = line

    if buffer:
        merged_lines.append(buffer)

    return "\n".join(merged_lines)


def _fix_hyphenation(lines: List[str]) -> List[str]:
    result: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        core, suffix = _split_emphasis_suffix(line)
        if core.endswith("-") and i + 1 < len(lines):
            next_line = lines[i + 1].lstrip()
            if next_line and next_line[0].islower() and not _is_list_item(next_line):
                line = core[:-1] + next_line + suffix
                i += 2
                result.append(line)
                continue
        result.append(line)
        i += 1
    return result


def _is_list_item(line: str) -> bool:
    return bool(LIST_ITEM_RE.match(line))


def _should_join(prev_line: str, next_line: str) -> bool:
    if prev_line.endswith((".", "!", "?", ":")):
        return False
    if next_line and next_line[0].islower():
        return True
    if prev_line.endswith((",", ";")):
        return True
    return True


def _classify_heading(max_size: float, body_size: float, text: str, bold_ratio: float) -> int | None:
    if body_size <= 0:
        return None
    ratio = max_size / body_size
    if ratio >= 1.6:
        return 1
    if ratio >= 1.35:
        return 2
    if ratio >= 1.2:
        return 3
    if bold_ratio >= 0.6 and _looks_like_heading(text):
        return 3
    if ratio >= 1.05 and _looks_like_heading(text):
        return 3
    return None


def _apply_heading(text: str, level: int) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    head = lines[0].lstrip("# ").strip()
    lines[0] = f"{'#' * level} {head}"
    return "\n".join(lines)


def _span_style(span: dict) -> tuple[bool, bool]:
    flags = span.get("flags", 0) or 0
    font = (span.get("font") or "").lower()
    bold = bool(flags & 16) or ("bold" in font) or ("black" in font)
    italic = bool(flags & 2) or ("italic" in font) or ("oblique" in font)
    return bold, italic


def _wrap_text(text: str, style: tuple[bool, bool]) -> str:
    bold, italic = style
    if not text.strip():
        return text

    prefix_len = len(text) - len(text.lstrip())
    suffix_len = len(text) - len(text.rstrip())
    prefix = text[:prefix_len]
    core = text[prefix_len:len(text) - suffix_len] if suffix_len else text[prefix_len:]
    suffix = text[len(text) - suffix_len:] if suffix_len else ""

    marker = _style_marker(bold, italic)
    if marker:
        core = f"{marker}{core}{marker}"
    return prefix + core + suffix


def _style_marker(bold: bool, italic: bool) -> str:
    if bold and italic:
        return "***"
    if bold:
        return "**"
    if italic:
        return "*"
    return ""


def _needs_space(prev_span: dict, curr_span: dict) -> bool:
    prev_text = prev_span.get("text") or ""
    curr_text = curr_span.get("text") or ""
    if not prev_text or not curr_text:
        return False
    if prev_text.endswith((" ", "\t")) or curr_text.startswith((" ", "\t")):
        return False
    if curr_text.startswith((",", ".", ";", ":", ")", "]", "}", "?", "!", "%")):
        return False
    if prev_text.endswith(("/", "-")):
        return False
    prev_box = prev_span.get("bbox", (0, 0, 0, 0))
    curr_box = curr_span.get("bbox", (0, 0, 0, 0))
    gap = curr_box[0] - prev_box[2]
    prev_size = prev_span.get("size") or 0.0
    curr_size = curr_span.get("size") or 0.0
    avg_size = (prev_size + curr_size) / 2 if (prev_size or curr_size) else 0.0
    return gap > (avg_size * 0.15 if avg_size else 1.5)


def _split_emphasis_suffix(line: str) -> tuple[str, str]:
    match = re.search(r"(\*{1,3})$", line)
    if match:
        suffix = match.group(1)
        return line[:-len(suffix)], suffix
    return line, ""


def _looks_like_heading(text: str) -> bool:
    line = text.splitlines()[0].strip()
    if not line or len(line) > 80:
        return False
    if LIST_ITEM_RE.match(line):
        return False
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return (upper / len(letters)) >= 0.6


def _is_page_number(text: str) -> bool:
    """Detect standalone page number blocks to skip them."""
    single = text.strip()
    single = single.lstrip("#").strip()
    return bool(PAGE_NUM_RE.match(single))
