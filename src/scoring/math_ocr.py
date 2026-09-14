"""Extract observed LaTeX, never forward free-form reasoning to the grader."""

import re

# Prefer explicit spans, preserving their order and excluding surrounding prose.
_BLOCKS = re.compile(
    r"(?P<fence>```(?P<language>[a-zA-Z]*)[^\S\n]*\n(?P<code>.*?)```)"
    r"|(?P<display>\$\$(?P<display_body>.*?)\$\$)"
    r"|(?P<bracket>\\\[(?P<bracket_body>.*?)\\\])"
    r"|(?P<paren>\\\((?P<paren_body>.*?)\\\))"
    r"|(?P<inline>(?<![\\$])\$(?!\$)(?P<inline_body>.*?)(?<!\\)\$)"
    r"|(?P<environment>\\begin\{(?P<env>align\*?|aligned|equation\*?|gather\*?|gathered)\}"
    r".*?\\end\{(?P=env)\})",
    re.S,
)
_PREFIX = re.compile(r"^\s*(?:LaTeX|数式)\s*[:：]\s*", re.I)
_FUNCTIONS = {"sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "lim", "exp",
              "max", "min", "det", "mod"}


def _balanced_braces(text):
    depth = 0
    for char in re.sub(r"\\[{}]", "", text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _math_line(text):
    """Conservative fallback for a bare formula on its own line."""
    if not text or not _balanced_braces(text):
        return False
    if any(token in text for token in ("```", "$", r"\[", r"\]", r"\(", r"\)")):
        return False
    reduced = re.sub(r"\\(?:begin|end)\{[a-zA-Z*]+\}", "", text)
    reduced = re.sub(r"\\(?:text|textrm|mathrm|operatorname)\{[^{}]*\}", "", reduced)
    reduced = re.sub(r"\\[a-zA-Z]+|\\.", "", reduced)
    if re.search(r"[^\x00-\x7f]", reduced):
        return False
    if any(word not in _FUNCTIONS for word in re.findall(r"[A-Za-z]{2,}", reduced)):
        return False
    if re.search(r"[^A-Za-z0-9\s{}\[\]()+*/=<>^_.,:;|!&%~'-]", reduced):
        return False
    # A lone punctuation mark or a prose-only \text{...} is not a formula.
    return bool(re.search(r"[A-Za-z0-9]|\\(?:frac|sqrt|sum|int|alpha|beta|gamma|pi|infty)\b", reduced)
                or re.search(r"\\(?:frac|sqrt|sum|int|alpha|beta|gamma|pi|infty)\b", text))


def extract_latex_fragments(text):
    """Return only math spans/lines; keep distinct (even conflicting) candidates."""
    pieces = []
    cursor = 0

    def lines(fragment):
        for line in fragment.splitlines():
            line = _PREFIX.sub("", line).strip()
            if _math_line(line):
                pieces.append(line)

    for match in _BLOCKS.finditer(text):
        lines(text[cursor:match.start()])
        cursor = match.end()
        if match.group("fence"):
            if match.group("language").lower() in {"", "latex", "tex", "math"}:
                # Recursion handles $$ / environments inside code fences without
                # accepting prose merely because the code block is labelled latex.
                pieces.extend(extract_latex_fragments(match.group("code")))
        elif match.group("environment"):
            body = match.group("environment").strip()
            if _math_line(body):
                pieces.append(body)
        else:
            body = next(match.group(name) for name in
                        ("display_body", "bracket_body", "paren_body", "inline_body")
                        if match.group(name) is not None).strip()
            if _math_line(body):
                pieces.append(body)
    lines(text[cursor:])
    return pieces


def parse_math_response(raw, page_id):
    choice = raw["choices"][0]
    truncated = choice.get("finish_reason") != "stop"
    if truncated and choice.get("finish_reason") not in {"length"}:
        raise ValueError(f"数式OCRが正常終了していません: {choice.get('finish_reason')}")
    message = choice["message"]
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""
    if not isinstance(content, str) or not isinstance(reasoning, str):
        raise ValueError("OCRのcontent/reasoning_contentは文字列が必要")
    source = "content" if content.strip() else "reasoning_content"
    text = content if content.strip() else reasoning
    duplicate_removed = False
    if source == "reasoning_content":
        # Same narrow duplicate-half correction as eval_handwrite.py.
        lines = [line for line in text.strip().splitlines() if line.strip()]
        half = len(lines) // 2
        if half and len(lines) % 2 == 0 and lines[:half] == lines[half:]:
            text = "\n".join(lines[:half])
            duplicate_removed = True
    latex = extract_latex_fragments(text)
    if not latex:
        raise ValueError(f"{source}からLaTeXを抽出できません。空答案として扱いません")
    uncertainties = [{"location": "page", "candidates": [],
                      "reason": "数式候補はページ単位で抽出。位置・設問対応・転記と推論の区別は元画像で確認が必要"}]
    if source == "reasoning_content":
        uncertainties.append({"location": "page", "candidates": [],
                              "reason": "contentが空のためreasoning_contentから数式候補を抽出"})
    if truncated:
        uncertainties.append({"location": "generation", "candidates": latex,
                              "reason": "生成がlengthで打ち切られたため、末尾が欠落している可能性がある"})
    return {"page_id": page_id, "text": "\n".join(latex), "latex": latex,
            "source": source, "duplicate_half_removed": duplicate_removed,
            "truncated": truncated, "uncertainties": uncertainties}
