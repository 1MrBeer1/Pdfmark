"""Utilities to split combined markdown into chapter files."""

from __future__ import annotations

from pathlib import Path
import re
from typing import List, Tuple

INTRO_TERM = "\u0432\u0432\u0435\u0434\u0435\u043d\u0438\u0435"
CONCLUSION_TERM = "\u0437\u0430\u043a\u043b\u044e\u0447"
APPENDIX_TERM = "\u043f\u0440\u0438\u043b\u043e\u0436"


def split_markdown(md_path: Path, document_title: str | None = None) -> List[Path]:
    """Split a markdown file into separate chapter files.

    Rules:
    - H1 headings (`# `) start a new section.
    - The first intro section -> Vvedenie.md.
    - The first conclusion section -> Zaklychenie.md.
    - Appendix sections -> prilN.md.
    - All other sections -> gN.md.
    - index.md contains the document title and links to every section.
    """

    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    sections: List[Tuple[str, List[str]]] = []
    current_title: str | None = None
    current_lines: List[str] = []

    def flush_section() -> None:
        nonlocal current_title, current_lines
        if current_title is not None:
            sections.append((current_title, current_lines))
        current_title = None
        current_lines = []

    for line in lines:
        if line.startswith("# "):
            flush_section()
            current_title = line[2:].strip() or "Untitled"
            current_lines = [line]
        else:
            if current_title is None:
                current_title = "Untitled"
            current_lines.append(line)
    flush_section()

    intro_idx = None
    for idx, (title, _) in enumerate(sections):
        if _is_intro(title):
            intro_idx = idx
            break
    if intro_idx is not None:
        sections = sections[intro_idx:]

    output_paths: List[Path] = []
    index_entries: List[Tuple[str, Path]] = []
    chapter_idx = 0
    app_idx = 0
    intro_written = False
    concl_written = False

    for title, body_lines in sections:
        if _is_intro(title) and not intro_written:
            filename = "Vvedenie.md"
            intro_written = True
        elif _is_appendix(title):
            app_idx += 1
            filename = f"pril{app_idx}.md"
        elif _is_conclusion(title) and not concl_written:
            filename = "Zaklychenie.md"
            concl_written = True
        else:
            chapter_idx += 1
            filename = f"g{chapter_idx}.md"

        out_path = md_path.parent / filename
        content = "\n".join(body_lines).strip() + "\n"
        out_path.write_text(content, encoding="utf-8")
        output_paths.append(out_path)
        index_entries.append((_clean_section_title(title), out_path))

    index_path = _write_index(md_path, text, document_title, index_entries)
    return [index_path, *output_paths]


def _is_intro(title: str) -> bool:
    return INTRO_TERM in title.lower()


def _is_conclusion(title: str) -> bool:
    return CONCLUSION_TERM in title.lower()


def _is_appendix(title: str) -> bool:
    return title.lower().startswith(APPENDIX_TERM)


def _write_index(
    md_path: Path,
    markdown: str,
    document_title: str | None,
    entries: List[Tuple[str, Path]],
) -> Path:
    title = _index_title(markdown, document_title or md_path.stem)
    lines = [
        "---",
        "sidebar: false",
        "prev:",
        "  text: 'Главная'",
        "  link: '/'",
        "next: false",
        "---",
        "",
        f"# {title}",
        "",
        "## Оглавление {#table-of-contents}",
        "",
        "---",
        "",
        "- **[Печатное издание пособия](PDF.html)**",
        "",
        "---",
        "",
    ]
    for section_title, section_path in entries:
        link = section_path.with_suffix(".html").name
        lines.append(f"- [{_escape_link_label(section_title)}]({link})")

    index_path = md_path.parent / "index.md"
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return index_path


def _index_title(markdown: str, fallback_title: str) -> str:
    intro_heading = re.search(r"(?mi)^#\s+введение\s*$", markdown)
    title_scope = markdown[: intro_heading.start()] if intro_heading else markdown
    quoted_title_match = re.search(
        r"учебн(?:ое|ого)\s+пособи[ея]\s*[\u2013\u2014-]?\s*[\u00ab\"]([^\u00bb\"\n]+)[\u00bb\"]",
        title_scope,
        re.IGNORECASE,
    )
    frontmatter_title_match = re.search(r"(?m)^title:\s*(['\"])(.*?)\1\s*$", title_scope)
    metadata_title = frontmatter_title_match.group(2) if frontmatter_title_match else fallback_title
    metadata_title = re.sub(r"\.(?:html?|xhtml|pdf|docx?)$", "", metadata_title, flags=re.IGNORECASE)
    normalized_metadata = re.sub(r"[_\s]+", " ", metadata_title).strip()

    edition_match = re.search(r"\b(\d+)\s*[- ]?[еe]\s+издани", normalized_metadata, re.IGNORECASE)
    edition = edition_match.group(1) if edition_match else ""

    if quoted_title_match:
        base_title = _clean_index_text(quoted_title_match.group(1))
        title = f"Учебное пособие \u00ab{base_title}\u00bb"
    else:
        base_title = re.sub(
            r"\b\d+\s*[- ]?[еe]\s+издани\w*\b",
            "",
            normalized_metadata,
            flags=re.IGNORECASE,
        ).strip(" ._-")
        base_title = re.sub(r"\s+(Часть\s+\d+\b)", r". \1", base_title, flags=re.IGNORECASE)
        if re.search(r"\bчасть\s+\d+\b", base_title, re.IGNORECASE):
            title = f"Учебное пособие \u00ab{base_title}\u00bb"
        else:
            title = base_title or "Методическое пособие"

    if edition:
        title = f"{title}. Издание {edition}-е"
    return title


def _clean_index_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[*_~`]", "", text)
    return re.sub(r"\s+", " ", text).strip(" .")


def _clean_section_title(title: str) -> str:
    title = re.sub(r"\s+\{#[a-z_-]+\}\s*$", "", title)
    title = _clean_index_text(title)
    if title.casefold() == INTRO_TERM:
        return "Введение"
    if title.casefold().startswith(CONCLUSION_TERM):
        return "Заключение" if title.casefold() == "заключение" else title
    return title


def _escape_link_label(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")
