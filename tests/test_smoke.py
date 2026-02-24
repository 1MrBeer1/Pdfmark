import re
from pathlib import Path

from pdf2md.converter import convert_pdf
from pdf2md.extract_text import extract_text_blocks
from pdf2md.splitter import split_markdown


def _create_sample_pdf(pdf_path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from PIL import Image

    img_path = pdf_path.with_suffix(".png")
    img = Image.new("RGB", (100, 100), color=(220, 50, 50))
    img.save(img_path, format="PNG")

    doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []
    elements.append(Paragraph("Sample PDF", styles["Title"]))
    elements.append(Paragraph("Hello from a generated PDF.", styles["BodyText"]))
    elements.append(Spacer(1, 12))
    elements.append(RLImage(str(img_path), width=100, height=100))
    elements.append(Spacer(1, 12))

    data = [["Col1", "Col2"], ["A", "B"], ["C", "D"]]
    table = Table(data)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    elements.append(table)

    doc.build(elements)

    if img_path.exists():
        img_path.unlink()


def test_smoke(tmp_path: Path) -> None:
    pdf_path = tmp_path / "input.pdf"
    _create_sample_pdf(pdf_path)

    out_path = tmp_path / "output.md"
    assets_dir = tmp_path / "media"

    report = convert_pdf(
        input_path=pdf_path,
        out_path=out_path,
        assets_dir=assets_dir,
        md_format="github",
        ocr="off",
        dpi=150,
    )

    assert report.pages_processed >= 1
    assert out_path.exists()
    assert assets_dir.exists()

    md_text = out_path.read_text(encoding="utf-8")
    image_links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md_text)
    assert image_links

    for rel_path in image_links:
        assert (out_path.parent / rel_path).exists()


def test_filters_page_number_block() -> None:
    page_dict = {
        "blocks": [
            {
                "type": 0,
                "bbox": (0, 0, 10, 10),
                "lines": [
                    {
                        "spans": [
                            {"text": "28", "size": 12, "bbox": (0, 0, 5, 5), "flags": 0},
                        ]
                    }
                ],
            }
        ]
    }
    blocks = extract_text_blocks(page_dict)
    assert blocks == []


def test_splitter_skips_preface(tmp_path: Path) -> None:
    md = """# Титульный лист
Some preface text.
# Содержание
- item
# Введение
Intro body.
# Глава 1. Основы
Chapter text.
# Приложение A
Appendix text.
"""
    md_path = tmp_path / "out.md"
    md_path.write_text(md, encoding="utf-8")

    parts = split_markdown(md_path)
    names = [p.name for p in parts]
    assert names[0] == "Vvedenie.md"
    assert "g1.md" in names
    assert any(n.startswith("pril") for n in names)
