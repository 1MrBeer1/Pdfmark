"""Utilities to split combined markdown into chapter files."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

INTRO_TERM = "\u0432\u0432\u0435\u0434\u0435\u043d\u0438\u0435"
CONCLUSION_TERM = "\u0437\u0430\u043a\u043b\u044e\u0447"
APPENDIX_TERM = "\u043f\u0440\u0438\u043b\u043e\u0436"


def split_markdown(md_path: Path) -> List[Path]:
    """Split a markdown file into separate chapter files.

    Rules:
    - H1 headings (`# `) start a new section.
    - The first intro section -> Vvedenie.md.
    - The first conclusion section -> Zaklychenie.md.
    - Appendix sections -> prilN.md.
    - All other sections -> gN.md.
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

    return output_paths


def _is_intro(title: str) -> bool:
    return INTRO_TERM in title.lower()


def _is_conclusion(title: str) -> bool:
    return CONCLUSION_TERM in title.lower()


def _is_appendix(title: str) -> bool:
    return title.lower().startswith(APPENDIX_TERM)
