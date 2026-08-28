"""HTML conversion utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import logging
import re
import shutil
from typing import Iterator, Optional
from urllib.parse import unquote, urlparse

from .anchors import HeadingAnchorGenerator
from .code_blocks import CodeLanguageTracker, format_fenced_code
from .config import ConversionError, SUPPORTED_FORMATS, resolve_output_paths
from .postprocess import format_image_link
from .report import ConversionReport, PageReport


VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
SKIP_TAGS = {"script", "style", "head", "meta", "link", "title"}
BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "body",
    "div",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "img",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}

INTRO_TERM = "\u0432\u0432\u0435\u0434\u0435\u043d\u0438\u0435"
TOC_TERMS = {
    "\u043e\u0433\u043b\u0430\u0432\u043b\u0435\u043d\u0438\u0435",
    "\u0441\u043e\u0434\u0435\u0440\u0436\u0430\u043d\u0438\u0435",
}
CHAPTER_TITLE_TERM = "\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435-\u0433\u043b\u0430\u0432\u044b"
CHAPTER_NUMBER_TERM = "\u043d\u043e\u043c\u0435\u0440-\u0433\u043b\u0430\u0432\u044b"
SUBCHAPTER_TITLE_TERM = "\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435-\u043f\u043e\u0434\u0433\u043b\u0430\u0432\u044b"
CAPTION_TERM = "\u043f\u043e\u0434\u043f\u0438\u0441\u0438-\u043a-\u043a\u0430\u0440\u0442\u0438\u043d\u043a\u0430\u043c"
CODE_CLASS_TERM = "\u043a\u043e\u0434"
RUNNING_HEADER_OVERRIDE_CLASS = "paraoverride-1"
CHAPTER_RE = re.compile("^(?:\u0433\u043b\u0430\u0432\u0430|\u0440\u0430\u0437\u0434\u0435\u043b)\\s+\\d+", re.IGNORECASE)
NUMBERED_HEADING_RE = re.compile("^(\\d+(?:\\.\\d+)+)\\.?\\s+\\S+")
TOC_LEADER_RE = re.compile("\\.{5,}\\s*\\d{1,4}$")
PAGE_NUMBER_RE = re.compile("^\\d{1,4}$")
FIGURE_CAPTION_PREFIX_RE = re.compile(
    r"^\s*(?:рис(?:унок)?\.?)\s*\d+(?:\.\d+)*\.?\s*(?:[-\u2013\u2014:]\s*)?",
    re.IGNORECASE,
)
FIGURE_CAPTION_MARKDOWN_PREFIX_RE = re.compile(
    r"^\s*(?:\*{1,3}|_{1,3})?\s*(?:рис(?:унок)?\.?)\s*\d+(?:\.\d+)*\.?"
    r"\s*(?:\*{1,3}|_{1,3})?\s*(?:[-\u2013\u2014:]\s*)?",
    re.IGNORECASE,
)
HARD_BREAK = "\ue000"
LIST_ITEM_RE = re.compile(r"^\s*([•●▪◦‣⁃-])\s+(.+)$", re.DOTALL)
ORDERED_LIST_ITEM_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+)$", re.DOTALL)
CSS_FORMAT_PROPERTIES = {
    "display",
    "font-style",
    "font-weight",
    "margin-left",
    "text-decoration",
    "text-decoration-line",
    "text-indent",
    "vertical-align",
    "visibility",
}


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["HtmlNode | str"] = field(default_factory=list)


@dataclass(frozen=True)
class CssRule:
    tag: str | None
    classes: frozenset[str]
    declarations: dict[str, str]
    order: int

    @property
    def specificity(self) -> tuple[int, int, int]:
        return (len(self.classes), 1 if self.tag else 0, self.order)

    def matches(self, node: HtmlNode) -> bool:
        if self.tag is not None and self.tag != node.tag:
            return False
        return self.classes.issubset(_class_tokens(node))


class CssStyles:
    """Small CSS cascade for semantic formatting in exported documents.

    InDesign stores bold, italic, super/subscript, and similar formatting in
    generated class rules instead of semantic HTML elements. A full browser
    CSS engine is unnecessary here; simple tag/class selectors cover those
    generated character styles while keeping the converter dependency-free.
    """

    def __init__(self, rules: list[CssRule] | None = None) -> None:
        self.rules = rules or []

    @classmethod
    def from_document(
        cls,
        root: HtmlNode,
        input_path: Path,
        logger: Optional[logging.Logger] = None,
    ) -> "CssStyles":
        chunks: list[str] = []
        for style_node in _iter_nodes(root, "style"):
            css_text = _node_text(style_node)
            if css_text.strip():
                chunks.append(css_text)

        for link_node in _iter_nodes(root, "link"):
            rel = link_node.attrs.get("rel", "").casefold().split()
            href = link_node.attrs.get("href", "").strip()
            if "stylesheet" not in rel or not href:
                continue
            css_path = _resolve_local_path(input_path, href)
            if css_path is None or not css_path.is_file():
                if logger:
                    logger.warning("Stylesheet not loaded: %s", href)
                continue
            try:
                chunks.append(_read_html_text(css_path))
            except OSError:
                if logger:
                    logger.warning("Stylesheet not loaded: %s", href)

        return cls(_parse_css_rules("\n".join(chunks)))

    def style_for(self, node: HtmlNode) -> dict[str, str]:
        declarations = _indesign_class_defaults(node)
        matching = [rule for rule in self.rules if rule.matches(node)]
        for rule in sorted(matching, key=lambda item: item.specificity):
            declarations.update(rule.declarations)
        declarations.update(_parse_declarations(node.attrs.get("style", "")))
        return declarations

    def is_hidden(self, node: HtmlNode) -> bool:
        if "hidden" in node.attrs or node.attrs.get("aria-hidden", "").casefold() == "true":
            return True
        style = self.style_for(node)
        return style.get("display", "").casefold() == "none" or style.get("visibility", "").casefold() == "hidden"


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(tag.lower(), {name.lower(): value or "" for name, value in attrs})
        self._stack[-1].children.append(node)
        if node.tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(tag.lower(), {name.lower(): value or "" for name, value in attrs})
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


class ImageExtractor:
    def __init__(
        self,
        input_path: Path,
        assets_dir: Path,
        rel_assets_dir: str,
        md_format: str,
        logger: Optional[logging.Logger],
    ) -> None:
        self.input_path = input_path
        self.assets_dir = assets_dir
        self.rel_assets_dir = rel_assets_dir
        self.md_format = md_format
        self.logger = logger
        self._counter: Iterator[int] = iter(range(1, 10**9))
        self._saved: dict[str, str] = {}
        self._reference_count = 0

    @property
    def saved_count(self) -> int:
        return len(self._saved)

    @property
    def reference_count(self) -> int:
        return self._reference_count

    def markdown_link(self, src: str, alt_text: str = "") -> str:
        src = src.strip()
        if not src:
            return ""
        self._reference_count += 1

        source_path = self._resolve_local_source(src)
        rel_path = self._saved.get(src)
        if rel_path is None and source_path is not None and source_path.is_file():
            extension = source_path.suffix or ".bin"
            filename = f"img_{next(self._counter):04d}{extension}"
            output_path = self.assets_dir / filename
            shutil.copyfile(source_path, output_path)
            rel_path = _join_rel_path(self.rel_assets_dir, filename)
            self._saved[src] = rel_path
        elif rel_path is None:
            rel_path = _normalize_src_for_markdown(src)
            if self.logger:
                self.logger.warning("Image resource not copied: %s", src)

        alt_text = _escape_image_alt(_normalize_text(alt_text) or _alt_from_src(src), self.md_format)
        return format_image_link(rel_path, alt_text, self.md_format)

    def _resolve_local_source(self, src: str) -> Path | None:
        return _resolve_local_path(self.input_path, src)


def convert_html(
    input_path: Path | str,
    out_path: Optional[Path | str] = None,
    assets_dir: Optional[Path | str] = None,
    md_format: str = "github",
    max_pages: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
    progress=None,
) -> ConversionReport:
    del max_pages

    input_path = Path(input_path)
    out_path, _resolved_assets_dir = resolve_output_paths(
        input_path,
        Path(out_path) if out_path else None,
        Path(assets_dir) if assets_dir else None,
    )
    # HTML output has one fixed resource layout so links stay valid after the
    # chapter splitter runs: every Markdown file sits next to ./image/.
    assets_dir = out_path.parent / "image"

    if md_format not in SUPPORTED_FORMATS:
        raise ConversionError(f"Unsupported format: {md_format}")
    if not input_path.exists():
        raise ConversionError(f"Input file not found: {input_path}")

    logger = logger or logging.getLogger("pdf2md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Converting %s -> %s", input_path, out_path)
    html_text = _read_html_text(input_path)

    parser = TreeBuilder()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as exc:
        raise ConversionError(f"Failed to parse HTML: {input_path}") from exc

    rel_assets_dir = _relative_assets_dir(out_path, assets_dir)
    image_extractor = ImageExtractor(input_path, assets_dir, rel_assets_dir, md_format, logger)
    css_styles = CssStyles.from_document(parser.root, input_path, logger)
    renderer = MarkdownRenderer(parser.root, image_extractor, md_format, css_styles)
    markdown = renderer.render()
    out_path.write_text((markdown + "\n") if markdown else "", encoding="utf-8")

    report = ConversionReport(processed_label="documents")
    report.add_page(
        PageReport(
            page_number=1,
            text_chars=len(markdown),
            images=image_extractor.saved_count,
            tables_markdown=renderer.tables_count,
            tables_images=0,
            ocr_used=False,
        )
    )
    if progress is not None:
        progress.update(1)

    logger.info(
        "HTML document: chars=%d image_refs=%d images_copied=%d tables_md=%d",
        len(markdown),
        image_extractor.reference_count,
        image_extractor.saved_count,
        renderer.tables_count,
    )
    logger.info("Saved markdown to %s", out_path)
    return report


class MarkdownRenderer:
    def __init__(
        self,
        root: HtmlNode,
        image_extractor: ImageExtractor,
        md_format: str,
        css_styles: CssStyles | None = None,
    ) -> None:
        self.root = root
        self.image_extractor = image_extractor
        self.md_format = md_format
        self.css_styles = css_styles or CssStyles()
        self.toc_heading_numbers = _extract_toc_heading_numbers(root)
        self.running_header_texts = _extract_running_header_texts(root)
        self.tables_count = 0
        self._toc_seen = False
        self._toc_emitted = False
        self.heading_anchors = HeadingAnchorGenerator()
        self.code_languages = CodeLanguageTracker()

    def render(self) -> str:
        body = _first_node(self.root, "body") or self.root
        blocks: list[str] = []

        if self.md_format == "vitepress":
            frontmatter = self._frontmatter()
            if frontmatter:
                blocks.append(frontmatter)

        blocks.extend(self._blocks_from_children(body))
        blocks = _merge_split_headings(blocks)
        return _join_blocks(blocks)

    def _frontmatter(self) -> str:
        title_node = _first_node(self.root, "title")
        title = _normalize_text(_node_text(title_node)) if title_node is not None else ""
        body = _first_node(self.root, "body")
        lang = body.attrs.get("lang", "") if body is not None else ""
        lines = ["---"]
        if title:
            lines.append(f"title: {_yaml_quote(title)}")
        if lang:
            lines.append(f"lang: {_yaml_quote(lang)}")
        lines.append("---")
        return "\n".join(lines) if len(lines) > 2 else ""

    def _blocks_from_children(self, node: HtmlNode) -> list[str]:
        blocks: list[str] = []
        inline_run: list[HtmlNode | str] = []
        code_run: list[tuple[HtmlNode, str]] = []

        def flush_inline_run() -> None:
            if not inline_run:
                return
            wrapper = HtmlNode("span", children=list(inline_run))
            text = _normalize_text(_inline_to_markdown(wrapper, self.image_extractor, self.css_styles))
            if text:
                blocks.append(text)
            inline_run.clear()

        def flush_code_run() -> None:
            if not code_run:
                return
            while code_run and not code_run[0][1].strip():
                code_run.pop(0)
            while code_run and not code_run[-1][1].strip():
                code_run.pop()
            if code_run:
                code = "\n".join(line for _, line in code_run)
                language = self._code_language(code, [item for item, _ in code_run])
                blocks.append(format_fenced_code(code, language))
            code_run.clear()

        for child in node.children:
            if isinstance(child, HtmlNode) and child.tag in BLOCK_TAGS:
                flush_inline_run()
                code_line = self._code_line_from_paragraph(child)
                if code_line is not None:
                    code_run.append((child, code_line))
                    continue
                flush_code_run()
                blocks.extend(self._block_from_node(child))
            elif isinstance(child, HtmlNode) and child.tag in SKIP_TAGS:
                continue
            else:
                if isinstance(child, str) and not child.strip() and code_run:
                    continue
                flush_code_run()
                inline_run.append(child)
        flush_code_run()
        flush_inline_run()
        return blocks

    def _code_line_from_paragraph(self, node: HtmlNode) -> str | None:
        if node.tag != "p" or self.css_styles.is_hidden(node) or self._toc_seen:
            return None
        plain_text = _normalize_text(_node_text(node))
        if _is_toc_line(plain_text) or PAGE_NUMBER_RE.fullmatch(plain_text):
            return None
        if not _is_code_only_paragraph(node):
            return None
        return _code_text(node)

    def _block_from_node(self, node: HtmlNode) -> list[str]:
        if node.tag in SKIP_TAGS or self.css_styles.is_hidden(node):
            return []
        if node.tag == "hr":
            return ["---"]
        if node.tag == "img":
            image = self._image_from_node(node)
            return [image] if image else []
        if node.tag == "pre":
            text = _code_text(node)
            language = self._code_language(text, [node])
            return [format_fenced_code(text, language)] if text else []
        if node.tag == "blockquote":
            text = "\n\n".join(self._blocks_from_children(node)) or _normalize_text(
                _inline_to_markdown(node, self.image_extractor, self.css_styles)
            )
            if not text:
                return []
            return ["\n".join(f"> {line}" if line else ">" for line in text.splitlines())]
        if node.tag == "table":
            table = self._table_from_node(node)
            return [table] if table else []
        if node.tag in {"ul", "ol"}:
            rendered_list = self._list_from_node(node)
            return [rendered_list] if rendered_list else []
        if node.tag == "li":
            text = self._li_text(node)
            return [f"- {text}"] if text else []
        if node.tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
            return self._paragraph_from_node(node)

        if any(isinstance(child, HtmlNode) and child.tag in BLOCK_TAGS for child in node.children):
            return self._blocks_from_children(node)

        text = _normalize_text(_inline_to_markdown(node, self.image_extractor, self.css_styles))
        return [text] if text else []

    def _paragraph_from_node(self, node: HtmlNode) -> list[str]:
        plain_text = _normalize_text(_node_text(node))
        text = _normalize_text(_inline_to_markdown(node, self.image_extractor, self.css_styles))
        if not text or (plain_text and PAGE_NUMBER_RE.fullmatch(plain_text)):
            return []

        lowered = plain_text.casefold()
        if lowered in TOC_TERMS:
            self._toc_seen = True
            if self.md_format == "vitepress" and not self._toc_emitted:
                self._toc_emitted = True
                return ["[[toc]]"]
            return []
        classes = _classes(node)
        if self._toc_seen and (_is_toc_line(plain_text) or _looks_like_toc_class(classes)):
            return []

        # InDesign can export a first TOC entry before the visible TOC title.
        # Leader dots plus a page number are sufficient to identify it, and
        # this check must happen before heading classification.
        if _is_toc_line(plain_text):
            return []

        heading_level = _heading_level_for(node, plain_text, self.toc_heading_numbers)
        if heading_level:
            self._toc_seen = False
            clean = _strip_heading_markup(text)
            heading = f"{'#' * heading_level} {clean}"
            if heading_level >= 2:
                heading = f"{heading} {{#{self.heading_anchors.make(plain_text)}}}"
            return [heading]

        if _is_running_header(node, plain_text, self.running_header_texts):
            return []

        if CAPTION_TERM in classes:
            caption = _strip_figure_caption_prefix(plain_text, text)
            return [f"*{_strip_outer_emphasis(caption)}*"] if caption else []

        list_item = _as_markdown_list_item(plain_text, text, _list_indent(node, self.css_styles))
        if list_item:
            return [list_item]
        return [text]

    def _code_language(self, code: str, nodes: list[HtmlNode]) -> str:
        return self.code_languages.resolve(code, _language_hint_from_nodes(nodes))

    def _image_from_node(self, node: HtmlNode) -> str:
        return self.image_extractor.markdown_link(node.attrs.get("src", ""), node.attrs.get("alt", ""))

    def _list_from_node(self, node: HtmlNode) -> str:
        ordered = node.tag == "ol"
        lines: list[str] = []
        item_number = 1
        for child in node.children:
            if not isinstance(child, HtmlNode) or child.tag != "li":
                continue
            text = self._li_text(child)
            if not text:
                continue
            marker = f"{item_number}." if ordered else "-"
            lines.append(f"{marker} {text}")
            for nested in [item for item in child.children if isinstance(item, HtmlNode) and item.tag in {"ul", "ol"}]:
                nested_text = self._list_from_node(nested)
                lines.extend(f"    {line}" for line in nested_text.splitlines())
            item_number += 1
        return "\n".join(lines)

    def _li_text(self, node: HtmlNode) -> str:
        content = HtmlNode(
            "li",
            attrs=node.attrs,
            children=[child for child in node.children if not (isinstance(child, HtmlNode) and child.tag in {"ul", "ol"})],
        )
        blocks = self._blocks_from_children(content)
        if blocks:
            return " ".join(_strip_list_marker(block) for block in blocks)
        return _normalize_text(_inline_to_markdown(content, self.image_extractor, self.css_styles))

    def _table_from_node(self, node: HtmlNode) -> str:
        rows: list[list[str]] = []
        for tr in _iter_nodes(node, "tr"):
            row: list[str] = []
            for cell in [child for child in tr.children if isinstance(child, HtmlNode) and child.tag in {"td", "th"}]:
                text = self._table_cell_text(cell)
                row.append(text.replace("|", "\\|"))
            if row:
                rows.append(row)

        if not rows:
            return ""
        self.tables_count += 1
        max_cols = max(len(row) for row in rows)
        normalized = [row + [""] * (max_cols - len(row)) for row in rows]
        lines = [
            "| " + " | ".join(normalized[0]) + " |",
            "| " + " | ".join(["---"] * max_cols) + " |",
        ]
        for row in normalized[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    def _table_cell_text(self, cell: HtmlNode) -> str:
        parts: list[str] = []
        inline_run: list[HtmlNode | str] = []

        def flush_inline() -> None:
            if not inline_run:
                return
            wrapper = HtmlNode("span", children=list(inline_run))
            text = _normalize_text(_inline_to_markdown(wrapper, self.image_extractor, self.css_styles))
            if text:
                parts.append(text)
            inline_run.clear()

        for child in cell.children:
            if isinstance(child, HtmlNode) and child.tag in {"p", "div", "ul", "ol"}:
                flush_inline()
                if child.tag in {"ul", "ol"}:
                    text = self._list_from_node(child).replace("\n", "<br>")
                else:
                    text = _normalize_text(_inline_to_markdown(child, self.image_extractor, self.css_styles))
                if text:
                    parts.append(text)
            else:
                inline_run.append(child)
        flush_inline()
        return "<br>".join(parts)


def _read_html_text(path: Path) -> str:
    data = path.read_bytes()
    encoding = _detect_encoding(data) or "utf-8"
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _detect_encoding(data: bytes) -> str | None:
    prefix = data[:4096].decode("ascii", errors="ignore")
    match = re.search("charset=[\"']?([A-Za-z0-9._-]+)", prefix, re.IGNORECASE)
    if match:
        return match.group(1)
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return None


def _inline_to_markdown(
    node: HtmlNode | str,
    image_extractor: ImageExtractor,
    css_styles: CssStyles | None = None,
) -> str:
    css_styles = css_styles or CssStyles()
    if isinstance(node, str):
        return node
    if node.tag in SKIP_TAGS or css_styles.is_hidden(node):
        return ""
    if node.tag == "br":
        return HARD_BREAK
    if node.tag == "img":
        image = image_extractor.markdown_link(node.attrs.get("src", ""), node.attrs.get("alt", ""))
        return f" {image} " if image else ""

    content = "".join(_inline_to_markdown(child, image_extractor, css_styles) for child in node.children)
    if not content:
        return ""

    if node.tag == "code":
        return _format_inline_code(content)

    style = css_styles.style_for(node)
    bold = node.tag in {"strong", "b"}
    italic = node.tag in {"em", "i"}
    underline = node.tag == "u"
    strike = node.tag in {"s", "strike", "del"}

    if "font-weight" in style:
        bold = _is_bold_weight(style["font-weight"])
    if "font-style" in style:
        italic = style["font-style"].casefold() in {"italic", "oblique"}
    decoration = style.get("text-decoration-line", style.get("text-decoration"))
    if decoration is not None:
        decoration_tokens = set(decoration.casefold().split())
        underline = "underline" in decoration_tokens
        strike = "line-through" in decoration_tokens

    # Generated InDesign spans containing only placed images should not wrap
    # those image links in emphasis markers.
    has_text = bool(_normalize_text(_node_text(node)))
    if has_text:
        if bold and italic:
            content = _wrap_inline(content, "***")
        elif bold:
            content = _wrap_inline(content, "**")
        elif italic:
            content = _wrap_inline(content, "*")
        if strike:
            content = _wrap_inline(content, "~~")
        if underline:
            content = _wrap_html_inline(content, "u")

    vertical_align = style.get("vertical-align", "").casefold()
    if node.tag == "sub" or vertical_align == "sub":
        content = _wrap_html_inline(content, "sub")
    elif node.tag == "sup" or vertical_align in {"super", "sup"}:
        content = _wrap_html_inline(content, "sup")

    if node.tag == "a":
        href = node.attrs.get("href", "").strip()
        if href:
            return f"[{_escape_link_text(_normalize_text(content))}]({href})"
    return content


def _heading_level_for(node: HtmlNode, text: str, toc_heading_numbers: frozenset[str] | None = None) -> int | None:
    if re.fullmatch("h[1-6]", node.tag):
        return int(node.tag[1])

    classes = _classes(node)
    lowered = text.casefold().rstrip(".:")
    is_chapter_style = CHAPTER_TITLE_TERM in classes or CHAPTER_NUMBER_TERM in classes
    is_numbered_heading_style = is_chapter_style or SUBCHAPTER_TITLE_TERM in classes

    if lowered in {INTRO_TERM, "заключение"}:
        return 1

    if CHAPTER_RE.match(text) and is_chapter_style:
        return 1

    numbered = NUMBERED_HEADING_RE.match(text)
    if numbered:
        number = numbered.group(1)
        if is_numbered_heading_style or number in (toc_heading_numbers or frozenset()):
            return min(max(len(number.split(".")), 2), 6)

    if CHAPTER_TITLE_TERM in classes:
        return 1
    return None


def _extract_toc_heading_numbers(root: HtmlNode) -> frozenset[str]:
    numbers: set[str] = set()
    body = _first_node(root, "body") or root
    for paragraph in _iter_nodes(body, "p"):
        classes = _classes(paragraph)
        if not _looks_like_toc_class(classes):
            continue
        text = _normalize_text(_node_text(paragraph))
        match = NUMBERED_HEADING_RE.match(text)
        if match and (_is_toc_line(text) or re.search(r"\s\d{1,4}$", text)):
            numbers.add(match.group(1))
    return frozenset(numbers)


def _extract_running_header_texts(root: HtmlNode) -> frozenset[str]:
    counts: dict[str, int] = {}
    override_counts: dict[str, int] = {}
    original_text: dict[str, str] = {}
    body = _first_node(root, "body") or root

    for paragraph in _iter_nodes(body, "p"):
        text = _normalize_text(_node_text(paragraph))
        if not text or PAGE_NUMBER_RE.fullmatch(text) or _is_toc_line(text):
            continue
        key = _running_header_key(text)
        counts[key] = counts.get(key, 0) + 1
        original_text.setdefault(key, text)
        if RUNNING_HEADER_OVERRIDE_CLASS in _class_tokens(paragraph):
            override_counts[key] = override_counts.get(key, 0) + 1

    headers: set[str] = set()
    for key, count in counts.items():
        text = original_text[key]
        repeated_chapter_title = count >= 2 and bool(CHAPTER_RE.match(text))
        repeated_page_title = override_counts.get(key, 0) >= 3 and 20 <= len(text) <= 180
        if repeated_chapter_title or repeated_page_title:
            headers.add(key)
    return frozenset(headers)


def _is_running_header(node: HtmlNode, text: str, running_headers: frozenset[str]) -> bool:
    if not text or _running_header_key(text) not in running_headers:
        return False
    return RUNNING_HEADER_OVERRIDE_CLASS in _class_tokens(node) or bool(CHAPTER_RE.match(text))


def _running_header_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _classes(node: HtmlNode) -> str:
    return node.attrs.get("class", "").casefold()


def _class_tokens(node: HtmlNode) -> frozenset[str]:
    return frozenset(item.casefold() for item in node.attrs.get("class", "").split() if item)


def _is_toc_line(text: str) -> bool:
    return bool(TOC_LEADER_RE.search(text))


def _looks_like_toc_class(classes: str) -> bool:
    return CODE_CLASS_TERM in classes


def _node_text(node: HtmlNode | None) -> str:
    if node is None:
        return ""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n")
        else:
            parts.append(_node_text(child))
    return "".join(parts)


def _is_code_only_paragraph(node: HtmlNode) -> bool:
    if CODE_CLASS_TERM in _class_tokens(node):
        return True

    code_parts: list[str] = []
    outside_parts: list[str] = []

    def collect(item: HtmlNode | str, inside_code: bool = False) -> None:
        if isinstance(item, str):
            (code_parts if inside_code else outside_parts).append(item)
            return
        styled_as_code = inside_code or item.tag == "code" or CODE_CLASS_TERM in _class_tokens(item)
        for child in item.children:
            collect(child, styled_as_code)

    for child in node.children:
        collect(child)
    return bool(_normalize_text("".join(code_parts))) and not _normalize_text("".join(outside_parts))


def _code_text(node: HtmlNode) -> str:
    text = _node_text(node).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return text.strip("\n").rstrip()


def _language_hint_from_nodes(nodes: list[HtmlNode]) -> str:
    aliases = {
        "c": "cpp",
        "cc": "cpp",
        "cpp": "cpp",
        "cxx": "cpp",
        "c++": "cpp",
        "python": "python",
        "py": "python",
        "bash": "bash",
        "sh": "bash",
        "shell": "bash",
        "javascript": "js",
        "js": "js",
    }
    prefixes = ("language-", "lang-", "source-", "highlight-source-")
    for node in nodes:
        candidates = [node, *_iter_nodes(node, "code")]
        for candidate in candidates:
            for token in _class_tokens(candidate):
                normalized = token.casefold().replace("_", "-")
                values = [normalized]
                values.extend(normalized[len(prefix) :] for prefix in prefixes if normalized.startswith(prefix))
                for value in values:
                    if value in aliases:
                        return aliases[value]
    return ""


def _iter_nodes(node: HtmlNode, tag: str) -> Iterator[HtmlNode]:
    for child in node.children:
        if not isinstance(child, HtmlNode):
            continue
        if child.tag == tag:
            yield child
        yield from _iter_nodes(child, tag)


def _first_node(node: HtmlNode, tag: str) -> HtmlNode | None:
    for child in node.children:
        if not isinstance(child, HtmlNode):
            continue
        if child.tag == tag:
            return child
        found = _first_node(child, tag)
        if found is not None:
            return found
    return None


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\n\f\v]+", " ", text)
    text = re.sub(rf" *{re.escape(HARD_BREAK)} *", HARD_BREAK, text)
    return text.strip().replace(HARD_BREAK, "  \n")


def _strip_heading_markup(text: str) -> str:
    text = _strip_outer_emphasis(text)
    text = re.sub("\\.{5,}\\s*\\d{1,4}$", "", text).strip()
    return text


def _strip_figure_caption_prefix(plain_text: str, markdown_text: str) -> str:
    if FIGURE_CAPTION_PREFIX_RE.match(plain_text) is None:
        return markdown_text.strip()
    cleaned = FIGURE_CAPTION_MARKDOWN_PREFIX_RE.sub("", markdown_text, count=1)
    return cleaned.strip()


def _merge_split_headings(blocks: list[str]) -> list[str]:
    merged: list[str] = []
    for block in blocks:
        heading = _parse_heading_block(block)
        prev_heading = _parse_heading_block(merged[-1]) if merged else None
        if (
            heading
            and prev_heading
            and heading[0] == prev_heading[0] == 1
            and re.match(r"^(?:глава|раздел)\s+\d+\b", _strip_heading_markup(prev_heading[1]), re.IGNORECASE)
        ):
            level, text = heading
            _, prev_text = prev_heading
            merged[-1] = f"{'#' * level} {_normalize_text(prev_text + ' ' + text)}"
            continue
        merged.append(block)
    return merged


def _join_blocks(blocks: list[str]) -> str:
    joined: list[str] = []
    for raw_block in (item for item in blocks if item.strip()):
        block = raw_block.rstrip()
        if not _is_list_block(block):
            block = block.strip()
        if joined and _is_list_block(joined[-1]) and _is_list_block(block):
            joined[-1] = f"{joined[-1]}\n{block}"
        else:
            joined.append(block)
    return "\n\n".join(joined).strip()


def _is_list_block(block: str) -> bool:
    return bool(re.match(r"^\s*(?:[-*+] |\d+\. )", block))


def _as_markdown_list_item(plain_text: str, markdown_text: str, indent: str = "") -> str | None:
    bullet_match = LIST_ITEM_RE.match(plain_text)
    if bullet_match:
        content = re.sub(r"^\s*(?:\*{1,3})?[•●▪◦‣⁃-](?:\*{1,3})?\s+", "", markdown_text, count=1)
        return f"{indent}- {content.strip()}" if content.strip() else None

    ordered_match = ORDERED_LIST_ITEM_RE.match(plain_text)
    if ordered_match:
        number = ordered_match.group(1)
        content = re.sub(
            rf"^\s*(?:\*{{1,3}})?{re.escape(number)}[.)](?:\*{{1,3}})?\s+",
            "",
            markdown_text,
            count=1,
        )
        return f"{indent}{number}. {content.strip()}" if content.strip() else None
    return None


def _list_indent(node: HtmlNode, css_styles: CssStyles) -> str:
    style = css_styles.style_for(node)
    values: list[float] = []
    for property_name in ("margin-left", "text-indent"):
        match = re.match(r"(-?\d+(?:\.\d+)?)", style.get(property_name, ""))
        if match is not None:
            values.append(float(match.group(1)))
    return "    " if values and max(values) >= 25 else ""


def _parse_heading_block(block: str) -> tuple[int, str] | None:
    if "\n" in block:
        return None
    match = re.match("^(#{1,6})\\s+(.+)$", block.strip())
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _strip_outer_emphasis(text: str) -> str:
    for marker in ("***", "**", "*"):
        if text.startswith(marker) and text.endswith(marker) and len(text) > len(marker) * 2:
            return text[len(marker):-len(marker)].strip()
    return text


def _strip_list_marker(text: str) -> str:
    return re.sub(r"^\s*(?:[-*+•●▪◦‣⁃]|\d+[.)])\s+", "", text).strip()


def _wrap_inline(text: str, marker: str) -> str:
    if not text.strip():
        return text
    prefix_len = len(text) - len(text.lstrip())
    suffix_len = len(text) - len(text.rstrip())
    prefix = text[:prefix_len]
    core = text[prefix_len : len(text) - suffix_len] if suffix_len else text[prefix_len:]
    suffix = text[len(text) - suffix_len :] if suffix_len else ""
    return f"{prefix}{marker}{core}{marker}{suffix}"


def _wrap_html_inline(text: str, tag: str) -> str:
    if not text.strip():
        return text
    prefix_len = len(text) - len(text.lstrip())
    suffix_len = len(text) - len(text.rstrip())
    prefix = text[:prefix_len]
    core = text[prefix_len : len(text) - suffix_len] if suffix_len else text[prefix_len:]
    suffix = text[len(text) - suffix_len :] if suffix_len else ""
    return f"{prefix}<{tag}>{core}</{tag}>{suffix}"


def _format_inline_code(text: str) -> str:
    core = text.strip()
    if not core:
        return ""
    runs = [len(match.group(0)) for match in re.finditer(r"`+", core)]
    delimiter = "`" * (max(runs, default=0) + 1)
    padding = " " if core.startswith("`") or core.endswith("`") else ""
    return f"{delimiter}{padding}{core}{padding}{delimiter}"


def _is_bold_weight(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"bold", "bolder"}:
        return True
    if normalized in {"normal", "lighter"}:
        return False
    match = re.match(r"\d+", normalized)
    return bool(match and int(match.group(0)) >= 600)


def _escape_link_text(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def _escape_image_alt(text: str, md_format: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    if md_format == "obsidian":
        return text.replace("|", "\\|").replace("]", "\\]")
    return _escape_link_text(text)


def _alt_from_src(src: str) -> str:
    parsed = urlparse(src)
    stem = Path(unquote(parsed.path or src)).stem
    return stem or "image"


def _normalize_src_for_markdown(src: str) -> str:
    return unquote(src).replace("\\", "/")


def _resolve_local_path(input_path: Path, reference: str) -> Path | None:
    reference = reference.strip()
    if not reference or reference.casefold().startswith("data:"):
        return None

    if re.match(r"^[A-Za-z]:[\\/]", reference):
        return Path(unquote(reference))

    parsed = urlparse(reference)
    if parsed.scheme and parsed.scheme.casefold() != "file":
        return None

    decoded_path = unquote(parsed.path or reference)
    if parsed.scheme.casefold() == "file":
        if parsed.netloc:
            decoded_path = f"//{parsed.netloc}{decoded_path}"
        elif re.match(r"^/[A-Za-z]:/", decoded_path):
            decoded_path = decoded_path[1:]
        return Path(decoded_path)

    decoded_path = decoded_path.replace("/", "\\")
    return (input_path.parent / decoded_path).resolve()


def _parse_css_rules(css_text: str) -> list[CssRule]:
    css_text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    rules: list[CssRule] = []
    order = 0
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css_text):
        declarations = _parse_declarations(match.group(2))
        if not declarations:
            continue
        for raw_selector in match.group(1).split(","):
            selector = raw_selector.strip()
            parsed = _parse_simple_selector(selector)
            if parsed is None:
                continue
            tag, classes = parsed
            rules.append(CssRule(tag=tag, classes=classes, declarations=declarations, order=order))
            order += 1
    return rules


def _parse_simple_selector(selector: str) -> tuple[str | None, frozenset[str]] | None:
    if not selector or any(token in selector for token in (" ", ">", "+", "~", "#", "[", ":")):
        return None
    match = re.fullmatch(r"(?P<tag>[A-Za-z][A-Za-z0-9_-]*)?(?P<classes>(?:\.[^.]+)+)", selector)
    if match is None:
        return None
    tag = match.group("tag")
    classes = frozenset(part.casefold() for part in match.group("classes").split(".") if part)
    return (tag.casefold() if tag else None, classes)


def _parse_declarations(declaration_text: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for declaration in declaration_text.split(";"):
        if ":" not in declaration:
            continue
        property_name, value = declaration.split(":", 1)
        property_name = property_name.strip().casefold()
        if property_name not in CSS_FORMAT_PROPERTIES:
            continue
        value = re.sub(r"\s*!important\s*$", "", value.strip(), flags=re.IGNORECASE)
        if value:
            declarations[property_name] = value
    return declarations


def _indesign_class_defaults(node: HtmlNode) -> dict[str, str]:
    classes = _class_tokens(node)
    declarations: dict[str, str] = {}
    if "выделение-курсив" in classes:
        declarations.update({"font-style": "italic", "font-weight": "bold"})
    if classes.intersection({"выделение-синим", "выделение-черным", "подписи-к-картинкам--выделение-"}):
        declarations["font-weight"] = "bold"
    return declarations


def _relative_assets_dir(out_path: Path, assets_dir: Path) -> str:
    try:
        import os

        rel = os.path.relpath(assets_dir, out_path.parent)
    except ValueError:
        rel = str(assets_dir)
    rel = rel.replace("\\", "/")
    return "./image" if rel == "image" else rel


def _join_rel_path(rel_dir: str, filename: str) -> str:
    if not rel_dir:
        return filename
    return f"{rel_dir}/{filename}".replace("\\", "/")


def _yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
