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
      <w:pPr><w:pStyle w:val="Heading2"/></w:pPr>
      <w:r><w:t>2.1. Настройка документа — Python / C++</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading3"/></w:pPr>
      <w:r><w:t>Детальная настройка!</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading3"/></w:pPr>
      <w:r><w:t>Детальная настройка!</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Hello </w:t></w:r>
      <w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>
      <w:r><w:t> text.</w:t></w:r>
    </w:p>
    <w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr><w:t>#include &lt;Arduino.h&gt;</w:t></w:r></w:p>
    <w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr><w:t>void setup() {{</w:t></w:r></w:p>
    <w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr><w:t xml:space="preserve">  Serial.begin(9600);</w:t></w:r></w:p>
    <w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr><w:t xml:space="preserve"> </w:t></w:r></w:p>
    <w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr><w:t>}}</w:t></w:r></w:p>
    <w:p>
      <w:r><w:t>Inline method </w:t></w:r>
      <w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr><w:t>motor.speed()</w:t></w:r>
      <w:r><w:t> stays in this paragraph.</w:t></w:r>
    </w:p>
    <w:p><w:pPr><w:pStyle w:val="CodeBlock"/></w:pPr><w:r><w:t>lsusb</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="CodeBlock"/></w:pPr><w:r><w:t>ls -l /dev/serial/by-id/</w:t></w:r></w:p>
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
    assert "# Word Title {#" not in md_text
    assert "## 2.1. Настройка документа — Python / C++ {#nastroyka_dokumenta_python_c}" in md_text
    assert "### Детальная настройка! {#detalnaya_nastroyka}" in md_text
    assert "### Детальная настройка! {#detalnaya_nastroyka_a}" in md_text
    assert "Hello **bold** text." in md_text
    assert "```cpp\n#include <Arduino.h>\nvoid setup() {\n  Serial.begin(9600);\n\n}\n```" in md_text
    assert "Inline method motor.speed() stays in this paragraph." in md_text
    assert "```bash\nlsusb\nls -l /dev/serial/by-id/\n```" in md_text
    assert "| Name | Value |" in md_text
    assert "| A | B |" in md_text


def _create_sample_html(html_path: Path) -> None:
    resources = html_path.parent / "sample-web-resources" / "image"
    resources.mkdir(parents=True)
    (resources / "pic.png").write_bytes(b"image-bytes")

    html = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /><title>HTML Test</title></head>
<body lang="ru-RU">
  <p>UDK 629.735:372.862</p>
  <p class="\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435-\u0433\u043b\u0430\u0432\u044b">\u0413\u043b\u0430\u0432\u0430 1.</p>
  <p class="\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435-\u0433\u043b\u0430\u0432\u044b">\u041d\u0430\u0447\u0430\u043b\u043e</p>
  <p>Intro <strong>bold</strong> and <a href="https://example.com">link</a>.</p>
  <img src="sample-web-resources/image/pic.png" alt="Picture" />
  <p class="\u041f\u043e\u0434\u043f\u0438\u0441\u0438-\u043a-\u043a\u0430\u0440\u0442\u0438\u043d\u043a\u0430\u043c">\u0420\u0438\u0441\u0443\u043d\u043e\u043a 1 - \u041f\u043e\u0434\u043f\u0438\u0441\u044c</p>
  <table>
    <tr><th>Name</th><th>Value</th></tr>
    <tr><td>A</td><td>B</td></tr>
  </table>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")


def test_convert_html_smoke(tmp_path: Path) -> None:
    html_path = tmp_path / "sample.html"
    _create_sample_html(html_path)

    out_path = tmp_path / "output.md"
    report = convert_file(html_path, out_path=out_path, assets_dir=tmp_path / "ignored-assets", md_format="github")

    assert report.pages_processed == 1
    assert report.images_extracted == 1
    assert report.tables_markdown == 1

    md_text = out_path.read_text(encoding="utf-8")
    assert "UDK 629.735:372.862" in md_text
    assert "# UDK 629.735:372.862" not in md_text
    assert "# \u0413\u043b\u0430\u0432\u0430 1. \u041d\u0430\u0447\u0430\u043b\u043e" in md_text
    assert "Intro **bold** and [link](https://example.com)." in md_text
    assert "*\u041f\u043e\u0434\u043f\u0438\u0441\u044c*" in md_text
    assert "\u0420\u0438\u0441\u0443\u043d\u043e\u043a 1" not in md_text
    assert "| Name | Value |" in md_text

    image_links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md_text)
    assert image_links
    assert image_links == ["./image/img_0001.png"]
    assert not (tmp_path / "ignored-assets").exists()
    for rel_path in image_links:
        assert (out_path.parent / rel_path).exists()


def test_convert_html_vitepress_toc(tmp_path: Path) -> None:
    html_path = tmp_path / "site.html"
    html_path.write_text(
        """<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /><title>Site Doc</title></head>
<body lang="ru-RU">
  <p class="\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435-\u0433\u043b\u0430\u0432\u044b">\u041e\u0413\u041b\u0410\u0412\u041b\u0415\u041d\u0418\u0415</p>
  <p>\u0413\u043b\u0430\u0432\u0430 1. \u041d\u0430\u0447\u0430\u043b\u043e................................ 8</p>
  <p class="\u041a\u043e\u0434">1.13. \u041c\u043d\u043e\u0433\u043e\u0441\u0442\u0440\u043e\u0447\u043d\u044b\u0439 \u043f\u0443\u043d\u043a\u0442 \u043e\u0433\u043b\u0430\u0432\u043b\u0435\u043d\u0438\u044f</p>
  <p class="\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435-\u0433\u043b\u0430\u0432\u044b">\u0412\u0432\u0435\u0434\u0435\u043d\u0438\u0435</p>
</body>
</html>
""",
        encoding="utf-8",
    )

    out_path = tmp_path / "site.md"
    report = convert_file(html_path, out_path=out_path, assets_dir=tmp_path / "media", md_format="vitepress")

    assert report.pages_processed == 1
    md_text = out_path.read_text(encoding="utf-8")
    assert 'title: "Site Doc"' in md_text
    assert 'lang: "ru-RU"' in md_text
    assert "[[toc]]" in md_text
    assert "................................" not in md_text
    assert "\u041c\u043d\u043e\u0433\u043e\u0441\u0442\u0440\u043e\u0447\u043d\u044b\u0439 \u043f\u0443\u043d\u043a\u0442" not in md_text
    assert "# \u0412\u0432\u0435\u0434\u0435\u043d\u0438\u0435" in md_text
    assert "```" not in md_text


def test_convert_indesign_html_preserves_css_formatting_and_structure(tmp_path: Path) -> None:
    html_path = tmp_path / "indesign.html"
    resources = tmp_path / "indesign-web-resources"
    css_dir = resources / "css"
    image_dir = resources / "image"
    css_dir.mkdir(parents=True)
    image_dir.mkdir(parents=True)
    (image_dir / "picture.png").write_bytes(b"image-bytes")
    (css_dir / "idGeneratedStyles.css").write_text(
        """
span.Bold { font-weight: bold; }
span.ItalicBold { font-style: italic; font-weight: bold; }
span.Reset { font-style: normal; font-weight: normal; }
span.Super { vertical-align: super; }
p.Indented { margin-left: 34px; }
.Hidden { display: none; }
""",
        encoding="utf-8",
    )
    html_path.write_text(
        """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>InDesign</title>
  <link href="indesign-web-resources/css/idGeneratedStyles.css" rel="stylesheet" />
</head>
<body>
  <p class="Код">1.1.1. Детальный пункт ................................ 3</p>
  <p class="Название-главы">ОГЛАВЛЕНИЕ</p>
  <p class="Название-главы">Глава 1. Большой</p>
  <p class="Название-главы">заголовок</p>
  <p class="основной-абзац ParaOverride-1">Глава 1. Большой заголовок</p>
  <p class="основной-абзац ParaOverride-1">Глава 1. Большой заголовок</p>
  <p class="основной-абзац ParaOverride-1">Учебное пособие «Тест»</p>
  <p class="основной-абзац ParaOverride-1">Учебное пособие «Тест»</p>
  <p class="основной-абзац ParaOverride-1">Учебное пособие «Тест»</p>
  <p class="Название-подглавы"><span class="Bold">1.1. Реальный раздел</span></p>
  <p class="Название-подглавы">Обычный абзац с тем же стилем InDesign.</p>
  <p>1.1.1. Детальный пункт</p>
  <p>Глава 1. Большой заголовок</p>
  <p><span class="Bold">жирный</span>, <span class="ItalicBold">жирный курсив</span>, <span class="ItalicBold Reset">обычный</span>, x<span class="Super">2</span>.</p>
  <p><span class="Bold">•</span> Верхний пункт</p>
  <p class="Indented">- Вложенный пункт</p>
  <p>Первая строка<br />Вторая строка</p>
  <p class="Название-подглавы"><img src="indesign-web-resources/image/picture.png" alt="Рисунок" /><img src="indesign-web-resources/image/picture.png" alt="Рисунок" /></p>
  <p class="Подписи-к-картинкам"><span class="Bold">Рис. 1.2. </span><span>Описание изображения</span></p>
  <p class="Hidden">Служебный скрытый текст</p>
  <table><tr><td><p>Строка 1</p><p>Строка 2</p></td><td>Значение</td></tr></table>
</body>
</html>
""",
        encoding="utf-8",
    )

    out_path = tmp_path / "indesign.md"
    report = convert_file(html_path, out_path=out_path, assets_dir=tmp_path / "image", md_format="github")
    md_text = out_path.read_text(encoding="utf-8")

    assert "# Глава 1. Большой заголовок" in md_text
    assert "## **1.1. Реальный раздел**" not in md_text
    assert "## 1.1. Реальный раздел {#realnyy_razdel}" in md_text
    assert "### 1.1.1. Детальный пункт {#detalnyy_punkt}" in md_text
    assert "## Обычный абзац" not in md_text
    assert md_text.count("# Глава 1. Большой заголовок") == 1
    assert md_text.count("Глава 1. Большой заголовок") == 1
    assert "Учебное пособие «Тест»" not in md_text
    assert "................................" not in md_text
    assert "Обычный абзац с тем же стилем InDesign." in md_text
    assert "**жирный**" in md_text
    assert "***жирный курсив***" in md_text
    assert "***обычный***" not in md_text
    assert "<sup>2</sup>" in md_text
    assert "- Верхний пункт" in md_text
    assert "    - Вложенный пункт" in md_text
    assert "Первая строка  \nВторая строка" in md_text
    assert "Служебный скрытый текст" not in md_text
    assert "Строка 1<br>Строка 2" in md_text
    assert md_text.count("![Рисунок]") == 2
    assert md_text.count("![Рисунок](./image/img_0001.png)") == 2
    assert "*Описание изображения*" in md_text
    assert "Рис. 1.2." not in md_text
    assert report.images_extracted == 1
    assert len(list((tmp_path / "image").iterdir())) == 1


def test_html_code_blocks_languages_and_heading_anchors(tmp_path: Path) -> None:
    html_path = tmp_path / "code.html"
    html_path.write_text(
        """<!DOCTYPE html>
<html><head><meta charset="utf-8" /></head><body>
  <h1>Примеры</h1>
  <h2>Настройка полётного контроллера: C++ / JS 2</h2>
  <p class="Код">#include &lt;Arduino.h&gt;</p>
  <p class="Код">void setup() {</p>
  <p class="Код">Serial.begin(9600);</p>
  <p class="Код">}</p>
  <p>Обычный текст с <code>inline_value</code>.</p>
  <h3>Скрипт Python</h3>
  <pre>def greet(name):
    print(name)</pre>
  <h3>Команды Linux</h3>
  <p><span class="Код">lsusb</span></p>
  <p><span class="Код">ls -l /dev/serial/by-id/</span></p>
  <h3>JavaScript</h3>
  <pre><code class="language-js">const ready = true;
console.log(ready);</code></pre>
  <h3>JavaScript</h3>
</body></html>
""",
        encoding="utf-8",
    )

    out_path = tmp_path / "code.md"
    convert_file(html_path, out_path=out_path, md_format="vitepress")
    md_text = out_path.read_text(encoding="utf-8")

    assert "## Настройка полётного контроллера: C++ / JS 2 {#nastroyka_poletnogo_kontrollera_c_js}" in md_text
    assert "### Скрипт Python {#skript_python}" in md_text
    assert "### JavaScript {#javascript}" in md_text
    assert "### JavaScript {#javascript_a}" in md_text
    assert "```cpp\n#include <Arduino.h>\nvoid setup() {\nSerial.begin(9600);\n}\n```" in md_text
    assert "```python\ndef greet(name):\n    print(name)\n```" in md_text
    assert "```bash\nlsusb\nls -l /dev/serial/by-id/\n```" in md_text
    assert "```js\nconst ready = true;\nconsole.log(ready);\n```" in md_text
    assert "Обычный текст с `inline_value`." in md_text


def test_splitter_skips_preface(tmp_path: Path) -> None:
    md = (
        "# \u0422\u0438\u0442\u0443\u043b\u044c\u043d\u044b\u0439 \u043b\u0438\u0441\u0442\n"
        "Some preface text.\n"
        "# \u0421\u043e\u0434\u0435\u0440\u0436\u0430\u043d\u0438\u0435\n"
        "- item\n"
        "# \u0412\u0432\u0435\u0434\u0435\u043d\u0438\u0435\n"
        "Intro body with a reference to \u0443\u0447\u0435\u0431\u043d\u043e\u0435 \u043f\u043e\u0441\u043e\u0431\u0438\u0435 \u00ab\u0427\u0443\u0436\u043e\u0435\u00bb.\n"
        "# \u0413\u043b\u0430\u0432\u0430 1. \u041e\u0441\u043d\u043e\u0432\u044b\n"
        "## 1.1. \u041f\u043e\u0434\u0433\u043b\u0430\u0432\u0430\n"
        "Subchapter text.\n"
        "### 1.1.1. \u041f\u0443\u043d\u043a\u0442\n"
        "Nested section text.\n"
        "Chapter text.\n"
        "# \u041f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435 A\n"
        "Appendix text.\n"
    )
    md_path = tmp_path / "out.md"
    md_path.write_text(md, encoding="utf-8")

    parts = split_markdown(md_path, document_title="СТЕМ_Мастерская_Часть_1_1е_издание")
    names = [p.name for p in parts]
    assert names[0] == "index.md"
    assert names[1] == "Vvedenie.md"
    assert "g1.md" in names
    assert any(n.startswith("pril") for n in names)
    assert len(parts) == 4
    index_text = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "sidebar: false" in index_text
    assert "# Учебное пособие «СТЕМ Мастерская. Часть 1». Издание 1-е" in index_text
    assert "## Оглавление {#table-of-contents}" in index_text
    assert "- **[Печатное издание пособия](PDF.html)**" in index_text
    assert "- [Введение](Vvedenie.html)" in index_text
    assert "- [Глава 1. Основы](g1.html)" in index_text
    assert "- [Приложение A](pril1.html)" in index_text
    chapter_text = (tmp_path / "g1.md").read_text(encoding="utf-8")
    assert "## 1.1. \u041f\u043e\u0434\u0433\u043b\u0430\u0432\u0430" in chapter_text
    assert "### 1.1.1. \u041f\u0443\u043d\u043a\u0442" in chapter_text
