"""Configuration and logging helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TextIO
import logging
import sys

SUPPORTED_FORMATS = {"github", "gfm", "obsidian"}
SUPPORTED_OCR = {"auto", "off", "always"}


@dataclass
class ConversionConfig:
    out_path: Path
    assets_dir: Path
    md_format: str = "github"
    dpi: int = 200
    ocr: str = "auto"
    max_pages: Optional[int] = None
    keep_temp: bool = False
    verbose: bool = False
    ocr_min_chars: int = 50
    ocr_image_area_ratio: float = 0.4
    ocr_timeout_seconds: int = 20


class DependencyError(RuntimeError):
    pass


class ConversionError(RuntimeError):
    pass


def resolve_output_paths(input_path: Path, out_path: Optional[Path], assets_dir: Optional[Path]) -> tuple[Path, Path]:
    if out_path is None:
        out_path = input_path.with_suffix(".md")
    if assets_dir is None:
        stem = out_path.with_suffix("")
        assets_dir = Path(f"{stem}_assets")
    return out_path, assets_dir


def setup_logger(name: str = "pdf2md", verbose: bool = False, stream: Optional[TextIO] = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    logger.propagate = False

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
