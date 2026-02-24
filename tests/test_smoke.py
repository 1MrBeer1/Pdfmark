import re
from pathlib import Path

from pdf2md.converter import convert_pdf


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
    assets_dir = tmp_path / "output_assets"

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
