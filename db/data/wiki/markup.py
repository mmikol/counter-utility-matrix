"""Reading the wiki's markup.

The wiki serves data two ways and both need parsing:

    html_to_text      Cargo returns rendered HTML, so its values read like
                      Blizzard's pages: <span title="...">75 over 0.59s</span>
    wikitext_to_text  article source is MediaWiki markup - {{Template|p=v}} -
                      brace-matched rather than parsed as HTML

They are different grammars, but the wiki mixes the same furniture through
both - file links, comments, <br>, bare URLs - so the tidying is shared.
So are the patterns the loaders cut an article with: a link, a file with
its caption, a citation, a wikitable.

section_body cuts an article's section at the next heading of any depth, or
at the next top-level one. DATE is the wiki's date grammar, day or month
first, and parse_date reads a match of it.
"""

import re
from collections.abc import Iterator, Sequence
from datetime import date

from bs4 import BeautifulSoup

# --- shared tidying ----------------------------------------------------

# A file with its caption, which may hold a link of either kind.
FILE_LINK_RE = re.compile(
    r"\[\[(?:File|Image):(?:[^\[\]]|\[\[[^\[\]]*\]\]|\[[^\[\]]*\])*\]\]", re.I)
# A citation, self-closed or not: <ref name="x"/>, <ref>...</ref>.
REF_RE = re.compile(r"<ref\b[^>]*/>|<ref\b[^>]*>.*?</ref>", re.I | re.S)
# A wikitable: from "{|" to "|}", each at the start of a line.
TABLE_RE = re.compile(r"^\{\|.*?^\|\}", re.M | re.S)
BREAK_RE = re.compile(r"<br\s*/?>", re.I)
TAG_RE = re.compile(r"</?[a-z][^>]*>", re.I)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# A link -> its target. The innermost one: a file's caption may hold a link.
LINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]*)?\]\]")
LINK_LABELLED_RE = re.compile(r"\[\[[^\]|]*\|([^\]]*)\]\]")
LINK_PLAIN_RE = re.compile(r"\[\[([^\]]*)\]\]")
URL_RE = re.compile(r"https?://\S+")
WHITESPACE_RE = re.compile(r"\s+")


def tidy(text: str) -> str:
    """Strip links, stray markup and URLs; collapse whitespace."""
    text = LINK_LABELLED_RE.sub(r"\1", text)
    text = LINK_PLAIN_RE.sub(r"\1", text)
    text = URL_RE.sub("", text).replace("\'\'\'", "").replace("\'\'", "")
    return WHITESPACE_RE.sub(" ", text).strip().strip("; ").strip()


# --- Cargo's rendered HTML ---------------------------------------------

def html_to_text(value: str | None) -> str:
    """A Cargo field value -> plain gameplay text."""
    if not value:
        return ""
    text = FILE_LINK_RE.sub(" ", value)
    text = BREAK_RE.sub("; ", text)
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return tidy(text)


# --- article wikitext --------------------------------------------------

# A heading of any depth: "== Gameplay ==", "=== Dive heroes ===".
ANY_HEADING_RE = re.compile(r"^=+.*=+\s*$", re.M)
# A top-level heading: "== Gameplay ==", not "=== Dive heroes ===".
TOP_HEADING_RE = re.compile(r"^==(?!=).*==[ \t]*$", re.M)


def section_body(text: str, start: int, top_level: bool = False) -> str:
    """The text from `start` to the next heading of any depth, or to the end.
    top_level: to the next top-level heading, the subsections kept."""
    body = text[start:]
    following = (TOP_HEADING_RE if top_level else ANY_HEADING_RE).search(body)
    return body[: following.start()] if following else body


MONTHS = [
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december"]
# "4 October 2022", "June 20, 2024", "June 20 2024", or no year at all, the
# month in any case. Five groups: day, month, month, day, year.
DATE = (r"(?i:(?:(\d{1,2})\s+(%(m)s)|(%(m)s)\s+(\d{1,2}))(?:,?\s*(\d{4}))?)"
        % {"m": "|".join(MONTHS)})


def parse_date(groups: Sequence[str | None], year: str | None) -> date | None:
    """A date from a DATE match's first four groups - the day and the month in
    either order, one pair matched and the other None - and a year, its own
    or one the text gives elsewhere; None without a year, or for a day the
    month does not have."""
    day_first, month_first, month_second, day_second = groups[:4]
    day, month = day_first or day_second, month_first or month_second
    if day is None or month is None or year is None:
        return None
    try:
        return date(int(year), MONTHS.index(month.lower()) + 1, int(day))
    except ValueError:
        return None


def find_templates(text: str, name_pattern: str) -> Iterator[str]:
    """Yield the source of each top-level {{Name ...}} template."""
    for match in re.finditer(r"\{\{\s*" + name_pattern, text, re.I):
        depth, index = 0, match.start()
        while index < len(text):
            if text.startswith("{{", index):
                depth += 1
                index += 2
            elif text.startswith("}}", index):
                depth -= 1
                index += 2
                if depth == 0:
                    yield text[match.start():index]
                    break
            else:
                index += 1


def split_params(block: str) -> list[str]:
    """Split a template body on its top-level pipes."""
    body = block[2:-2]
    parts: list[str] = []
    current: list[str] = []
    depth, index = 0, 0
    while index < len(body):
        if body.startswith("{{", index) or body.startswith("[[", index):
            depth += 1
            current.append(body[index:index + 2])
            index += 2
        elif body.startswith("}}", index) or body.startswith("]]", index):
            depth -= 1
            current.append(body[index:index + 2])
            index += 2
        elif body[index] == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            index += 1
        else:
            current.append(body[index])
            index += 1
    parts.append("".join(current))
    return parts


def parse_params(block: str) -> dict[str, str]:
    """Named parameters of a template, as {lowercased key: raw value}."""
    params: dict[str, str] = {}
    for part in split_params(block)[1:]:
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().lower().replace(" ", "_")
        if key:
            params[key] = value.strip()
    return params


def _reduce(template: str) -> str:
    """Reduce one innermost {{...}} to text."""
    parts = split_params(template)
    head = parts[0].strip().lower()
    args = [a.strip() for a in parts[1:] if "=" not in a]
    if head in ("tt", "proj", "al", "abilitylink", "hero"):
        # {{tt|shown|tooltip}} shows the first; {{proj|hitscan}} the last.
        return (args[0] if head == "tt" else args[-1]) if args else ""
    return " ".join(args)


def wikitext_to_text(value: str | None) -> str:
    """A wikitext parameter value -> plain text."""
    if not value:
        return ""
    text = COMMENT_RE.sub("", value)
    for _ in range(20):
        start = text.rfind("{{")
        if start == -1:
            break
        end = text.find("}}", start)
        if end == -1:
            text = text.replace("{{", "")
            break
        text = text[:start] + _reduce(text[start:end + 2]) + text[end + 2:]
    text = BREAK_RE.sub("; ", text)
    text = TAG_RE.sub("", text)
    return tidy(text)
