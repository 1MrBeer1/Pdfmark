"""Shared custom-anchor generation for Markdown headings."""

from __future__ import annotations

import re


CYRILLIC_TRANSLITERATION = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


class HeadingAnchorGenerator:
    """Generate unique lowercase Latin anchors for one document."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def make(self, title: str) -> str:
        base = heading_anchor(title)
        anchor = base
        suffix_index = 0
        while anchor in self._used:
            suffix_index += 1
            anchor = f"{base}_{_alpha_suffix(suffix_index)}"
        self._used.add(anchor)
        return anchor


def heading_anchor(title: str) -> str:
    title = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", title)
    title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", title)
    title = re.sub(r"<[^>]+>", "", title)
    title = re.sub(r"[*~`]", "", title)
    anchor = title.casefold().translate(CYRILLIC_TRANSLITERATION)
    anchor = re.sub(r"\s+", "_", anchor)
    anchor = re.sub(r"[^a-z_-]", "", anchor)
    anchor = re.sub(r"_+", "_", anchor)
    anchor = re.sub(r"-+", "-", anchor)
    return anchor.strip("_-") or "section"


def _alpha_suffix(index: int) -> str:
    letters: list[str] = []
    while index > 0:
        index -= 1
        letters.append(chr(ord("a") + index % 26))
        index //= 26
    return "".join(reversed(letters)) or "a"
