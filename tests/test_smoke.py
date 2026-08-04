import re
from pathlib import Path
import zipfile

from pdf2md.converter import convert_file, convert_pdf
from pdf2md.extract_text import extract_text_blocks
from pdf2md.splitter import split_markdown

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


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
    assert "# Sample PDF" in md_text
    assert "# **Sample PDF**" not in md_text
    assert "\nCol1 Col2\n" not in md_text
    assert "\nA B\n" not in md_text

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


def test_filters_russian_page_number_block() -> None:
    page_dict = {
        "blocks": [
            {
                "type": 0,
                "bbox": (0, 0, 40, 10),
                "lines": [
                    {
                        "spans": [
                            {"text": "\u0441\u0442\u0440. 28", "size": 12, "bbox": (0, 0, 35, 5), "flags": 0},
                        ]
                    }
                ],
            }
        ]
    }
    blocks = extract_text_blocks(page_dict)
    assert blocks == []


def _create_sample_docx(docx_path: Path) -> None:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Word Title</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Hello </w:t></w:r>
      <w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>
      <w:r><w:t> text.</w:t></w:r>
    </w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    package_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    document_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>
"""

    with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", document_rels)


def test_convert_docx_smoke(tmp_path: Path) -> None:
    docx_path = tmp_path / "input.docx"
    _create_sample_docx(docx_path)

    out_path = tmp_path / "output.md"
    assets_dir = tmp_path / "media"
    report = convert_file(docx_path, out_path=out_path, assets_dir=assets_dir, md_format="github")

    assert report.pages_processed == 1
    assert out_path.exists()
    assert assets_dir.exists()

    md_text = out_path.read_text(encoding="utf-8")
    assert "# Word Title" in md_text
    assert "Hello **bold** text." in md_text
    assert "| Name | Value |" in md_text
    assert "| A | B |" in md_text


def test_splitter_skips_preface(tmp_path: Path) -> None:
    md = (
        "# \u0422\u0438\u0442\u0443\u043b\u044c\u043d\u044b\u0439 \u043b\u0438\u0441\u0442\n"
        "Some preface text.\n"
        "# \u0421\u043e\u0434\u0435\u0440\u0436\u0430\u043d\u0438\u0435\n"
        "- item\n"
        "# \u0412\u0432\u0435\u0434\u0435\u043d\u0438\u0435\n"
        "Intro body.\n"
        "# \u0413\u043b\u0430\u0432\u0430 1. \u041e\u0441\u043d\u043e\u0432\u044b\n"
        "Chapter text.\n"
        "# \u041f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435 A\n"
        "Appendix text.\n"
    )
    md_path = tmp_path / "out.md"
    md_path.write_text(md, encoding="utf-8")

    parts = split_markdown(md_path)
    names = [p.name for p in parts]
    assert names[0] == "Vvedenie.md"
    assert "g1.md" in names
    assert any(n.startswith("pril") for n in names)
