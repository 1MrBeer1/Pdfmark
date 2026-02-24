"""Conversion report models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class PageReport:
    page_number: int
    text_chars: int
    images: int
    tables_markdown: int
    tables_images: int
    ocr_used: bool


@dataclass
class ConversionReport:
    pages: List[PageReport] = field(default_factory=list)

    def add_page(self, page_report: PageReport) -> None:
        self.pages.append(page_report)

    @property
    def pages_processed(self) -> int:
        return len(self.pages)

    @property
    def chars_extracted(self) -> int:
        return sum(p.text_chars for p in self.pages)

    @property
    def images_extracted(self) -> int:
        return sum(p.images for p in self.pages)

    @property
    def tables_markdown(self) -> int:
        return sum(p.tables_markdown for p in self.pages)

    @property
    def tables_images(self) -> int:
        return sum(p.tables_images for p in self.pages)

    @property
    def ocr_pages(self) -> int:
        return sum(1 for p in self.pages if p.ocr_used)

    def summary_text(self) -> str:
        return (
            "pages processed: {pages}\n"
            "chars extracted: {chars}\n"
            "images extracted: {images}\n"
            "tables as markdown: {tables_md}\n"
            "tables as images: {tables_img}\n"
            "ocr pages count: {ocr_pages}"
        ).format(
            pages=self.pages_processed,
            chars=self.chars_extracted,
            images=self.images_extracted,
            tables_md=self.tables_markdown,
            tables_img=self.tables_images,
            ocr_pages=self.ocr_pages,
        )
