"""Shared fenced-code formatting and lightweight language detection."""

from __future__ import annotations

import re


CODE_LANGUAGES = {"cpp", "python", "bash", "js"}


class CodeLanguageTracker:
    """Detect a language and reuse it for ambiguous excerpts in one document."""

    def __init__(self) -> None:
        self.last_language = ""

    def resolve(self, code: str, hint: str = "") -> str:
        language = hint if hint in CODE_LANGUAGES else detect_code_language(code)
        if language:
            self.last_language = language
            return language
        return self.last_language


def detect_code_language(code: str) -> str:
    scores = {language: 0 for language in CODE_LANGUAGES}

    scores["cpp"] += 10 * len(re.findall(r"(?m)^\s*#\s*(?:include|define|ifdef|ifndef|endif|pragma)\b", code))
    scores["cpp"] += 6 * len(re.findall(r"\b(?:std::|Serial\.|Dynamixel\w*|uint(?:8|16|32|64)_t)\b", code))
    scores["cpp"] += 5 * len(re.findall(r"(?m)^\s*void\s+(?:setup|loop|\w+)\s*\(", code))
    scores["cpp"] += 2 * len(re.findall(r"(?m)^\s*(?:const\s+)?(?:int|float|double|bool|char|long|byte)\b[^\n;]*;", code))
    scores["cpp"] += len(re.findall(r"(?m);\s*$", code))

    scores["python"] += 12 * len(re.findall(r"(?m)^\s*(?:async\s+)?def\s+\w+\s*\(", code))
    scores["python"] += 10 * len(re.findall(r"(?m)^\s*class\s+\w+(?:\([^\n]*\))?\s*:", code))
    scores["python"] += 8 * len(re.findall(r"(?m)^\s*from\s+[\w.]+\s+import\s+", code))
    scores["python"] += 6 * len(re.findall(r"(?m)^\s*import\s+[\w.]+(?:\s+as\s+\w+)?\s*$", code))
    scores["python"] += 8 * len(re.findall(r"if\s+__name__\s*==\s*['\"]__main__['\"]", code))
    scores["python"] += 3 * len(re.findall(r"(?m)^\s*(?:if|elif|else|for|while|try|except|with)\b[^\n]*:\s*$", code))

    shell_commands = (
        r"alias|apt|apt-get|awk|cd|chmod|chown|cp|curl|docker|echo|export|find|git|grep|kill|ls|lsusb|"
        r"make|mkdir|mv|npm|pip|python|rm|rsync|sed|ssh|sudo|systemctl|tar|touch|wget|which|yarn"
    )
    scores["bash"] += 15 * len(re.findall(r"(?m)^\s*#!\s*/(?:usr/bin/env\s+)?(?:ba|z|k)?sh\b", code))
    scores["bash"] += 6 * len(re.findall(rf"(?m)^\s*(?:\$\s*)?(?:{shell_commands})(?:\s|$)", code))
    scores["bash"] += 3 * len(re.findall(r"(?:^|\s)(?:&&|\|\||\$\{|/dev/|2>&1)(?:\s|$|[^\s])", code))

    scores["js"] += 12 * len(re.findall(r"\bconsole\.(?:log|warn|error)\s*\(", code))
    scores["js"] += 10 * len(re.findall(r"(?m)^\s*(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=", code))
    scores["js"] += 10 * len(re.findall(r"\bfunction\s+[A-Za-z_$][\w$]*\s*\(", code))
    scores["js"] += 8 * len(re.findall(r"(?:\([^\n)]*\)|[A-Za-z_$][\w$]*)\s*=>", code))
    scores["js"] += 8 * len(re.findall(r"(?m)^\s*import\s+.+\s+from\s+['\"][^'\"]+['\"]", code))
    scores["js"] += 5 * len(re.findall(r"\b(?:document|window|require)\s*(?:\.|\()", code))

    language, score = max(scores.items(), key=lambda item: item[1])
    return language if score > 0 else ""


def format_fenced_code(code: str, language: str = "") -> str:
    code = code.strip("\n").rstrip()
    if not code:
        return ""
    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", code)), default=0)
    fence = "`" * max(3, longest_run + 1)
    language = language if language in CODE_LANGUAGES else ""
    return f"{fence}{language}\n{code}\n{fence}"
