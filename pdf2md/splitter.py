"""Utilities to split combined markdown into chapter files."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


def split_markdown(md_path: Path) -> List[Path]:
    """Split a markdown file into separate chapter files.

    Rules:
    - H1 headings (`# `) start a new section.
    - Section whose title contains "введение" -> Vvedenie.md (first only).
    - Title containing "заключение" -> Zaklychenie.md (first only).
    - Title starting with "прилож" -> prilN.md.
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

    # Drop everything before "Введение" if оно есть
    intro_idx = None
    for idx, (title, _) in enumerate(sections):
        if "введение" in title.lower():
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
        lowered = title.lower()
        if "введение" in lowered and not intro_written:
            filename = "Vvedenie.md"
            intro_written = True
        elif lowered.startswith("прилож"):
            app_idx += 1
            filename = f"pril{app_idx}.md"
        elif "заключ" in lowered and not concl_written:
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
