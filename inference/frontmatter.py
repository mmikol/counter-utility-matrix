"""The frontmatter dialect a strategy file opens with: `key: value` lines
between two `---` fences, and one level of indented mapping under a key
with no value (`params:`). A value is a quoted or bare string, an int, a
float, a boolean, null, or a [list] of those; a bare word is a string. A
`#` line is a comment.

    ---
    name: Answer every revealed enemy
    weight: 3
    params:
        MARGIN: 0.8
    ---
    the body
"""

import re

# one value: a string, a number, a boolean, a [list] of values, or null
Scalar = str | int | float | bool | list["Scalar"] | None
# a file's frontmatter: flat keys, and one level of indented mapping (params:)
Frontmatter = dict[str, Scalar | dict[str, Scalar]]

_WORDS: dict[str, bool | None] = {"true": True, "yes": True, "false": False, "no": False,
                                  "null": None, "none": None, "~": None}
_INTEGER = re.compile(r"[-+]?\d+(?:_\d+)*\Z")      # what int() reads


class FrontmatterError(ValueError):
    """Text that is not frontmatter in this dialect."""


def _number_or_text(text: str) -> int | float | str:
    """An int where the text is one, else a float, else the text itself: a
    bare word is a string in this dialect."""
    if _INTEGER.match(text):
        return int(text)
    try:
        return float(text)
    except ValueError:
        return text


def _scalar(text: str) -> Scalar:
    """One value, as the dialect reads it."""
    text = text.strip()
    if not text:
        return ""
    if text[0] == text[-1] and text[0] in "\"'" and len(text) >= 2:
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(p) for p in inner.split(",")] if inner else []
    low = text.lower()
    if low in _WORDS:
        return _WORDS[low]
    return _number_or_text(text)


def parse_frontmatter(text: str) -> tuple[Frontmatter, str]:
    """'---\\nkey: value\\n---\\nbody' -> (meta, body). Flat keys plus one
    level of indented mapping (params:)."""
    if not text.startswith("---"):
        raise FrontmatterError("no frontmatter: the file must open with ---")
    end = text.find("\n---", 3)
    if end < 0:
        raise FrontmatterError("unterminated frontmatter")
    header, body = text[3:end], text[end + 4:]
    meta: Frontmatter = {}
    block: dict[str, Scalar] | None = None      # the mapping indented lines fill
    for raw in header.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[0] in " \t"
        line = raw.strip()
        if ":" not in line:
            raise FrontmatterError("bad frontmatter line %r" % raw)
        key, _, value = line.partition(":")
        key = key.strip()
        if indented:
            if block is None:
                raise FrontmatterError("indented line %r under no mapping" % raw)
            block[key] = _scalar(value)
        elif value.strip() == "":
            block = {}
            meta[key] = block
        else:
            meta[key] = _scalar(value)
            block = None
    return meta, body.strip("\n")
