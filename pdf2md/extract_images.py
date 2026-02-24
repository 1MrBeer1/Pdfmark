"""Image extraction utilities."""

from __future__ import annotations

from dataclasses import dataclass
import io
import re
import itertools
from pathlib import Path
from typing import List, Optional, Tuple, Iterator

from PIL import Image

from .extract_text import TextBlock


@dataclass
class ImageItem:
    path: Path
    rel_path: str
    bbox: Optional[Tuple[float, float, float, float]]
    alt_text: str


def extract_images(
    doc,
    page,
    assets_dir: Path,
    page_num: int,
    text_blocks: List[TextBlock],
    rel_assets_dir: str,
    logger=None,
    counter: Optional[Iterator[int]] = None,
) -> List[ImageItem]:
    images: List[ImageItem] = []
    counter = counter or itertools.count(1)
    image_list = page.get_images(full=True)

    for image in image_list:
        xref = image[0]
        rects = page.get_image_rects(xref)
        if not rects:
            rects = [None]
        for rect in rects:
            img_index = next(counter)
            try:
                image_info = doc.extract_image(xref)
                img_bytes = image_info.get("image", b"")
                if not img_bytes:
                    continue
                image_obj = Image.open(io.BytesIO(img_bytes))
                if image_obj.mode not in ("RGB", "RGBA"):
                    image_obj = image_obj.convert("RGB")
            except Exception as exc:
                if logger:
                    logger.warning("Failed to extract image on page %d: %s", page_num, exc)
                continue

            filename = f"img_{img_index:04d}.png"
            out_path = assets_dir / filename
            image_obj.save(out_path, format="PNG")

            bbox_tuple = None
            if rect is not None:
                bbox_tuple = (rect.x0, rect.y0, rect.x1, rect.y1)

            alt_text = _find_caption(rect, text_blocks, page_num, img_index)
            rel_path = _join_rel_path(rel_assets_dir, filename)
            images.append(ImageItem(path=out_path, rel_path=rel_path, bbox=bbox_tuple, alt_text=alt_text))

    return images


def _find_caption(rect, text_blocks: List[TextBlock], page_num: int, img_index: int) -> str:
    default = f"image {img_index}"
    if rect is None:
        return default

    candidates = []
    for block in text_blocks:
        bbox = block.bbox
        if not bbox:
            continue
        # Below the image
        below_distance = bbox[1] - rect.y1
        if 0 <= below_distance <= 40 and _horiz_overlap(bbox, rect):
            candidates.append((below_distance, block.text))
            continue
        # Above the image
        above_distance = rect.y0 - bbox[3]
        if 0 <= above_distance <= 30 and _horiz_overlap(bbox, rect):
            candidates.append((above_distance + 1000, block.text))

    if candidates:
        candidates.sort(key=lambda item: item[0])
        return _sanitize_caption(candidates[0][1])
    return default


def _horiz_overlap(bbox: Tuple[float, float, float, float], rect) -> bool:
    return bbox[0] <= rect.x1 and bbox[2] >= rect.x0


def _sanitize_caption(text: str) -> str:
    text = re.sub(r"^#+\s+", "", text.strip())
    text = re.sub(r"\s+", " ", text)
    return text[:120] if text else text


def _join_rel_path(rel_dir: str, filename: str) -> str:
    if not rel_dir:
        return filename
    return f"{rel_dir}/{filename}".replace("\\", "/")
