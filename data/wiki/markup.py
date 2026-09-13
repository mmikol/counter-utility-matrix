"""Reading the wiki's markup.

The wiki serves data two ways and both need parsing:

    html_to_text      Cargo returns rendered HTML, so its values read like
                      Blizzard's pages: <span title="...">75 over 0.59s</span>
    wikitext_to_text  article source is MediaWiki markup - {{Template|p=v}} -
                      brace-matched rather than parsed as HTML

They are different grammars, but the wiki mixes the same furniture through
both - file links, comments, <br>, bare URLs - so the tidying is shared.

split_type unpicks Cargo's typed fields, where a kind and a firing mode are
packed into one string: "Weapon;;Hip Fire".
"""

import re

from bs4 import BeautifulSoup


# --- shared tidying ----------------------------------------------------

FILE_LINK_RE = re.compile(r"\[\[File:[^\]]*\]\]", re.I)
BREAK_RE = re.compile(r"<br\s*/?>", re.I)
TAG_RE = re.compile(r"</?[a-z][^>]*>", re.I)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
LINK_LABELLED_RE = re.compile(r"\[\[[^\]|]*\|([^\]]*)\]\]")
LINK_PLAIN_RE = re.compile(r"\[\[([^\]]*)\]\]")
URL_RE = re.compile(r"https?://\S+")
WHITESPACE_RE = re.compile(r"\s+")


def tidy(text):
    """Strip links, stray markup and URLs; collapse whitespace."""
    text = LINK_LABELLED_RE.sub(r"\1", text)
    text = LINK_PLAIN_RE.sub(r"\1", text)
    text = URL_RE.sub("", text).replace("\'\'\'", "").replace("\'\'", "")
    return WHITESPACE_RE.sub(" ", text).strip().strip("; ").strip()


# --- Cargo's rendered HTML ---------------------------------------------

def html_to_text(value):
    """A Cargo field value -> plain gameplay text."""
    if not value:
        return ""
    text = FILE_LINK_RE.sub(" ", value)
    text = BREAK_RE.sub("; ", text)
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return tidy(text)


# "Weapon;;Hip Fire" and "Weapon (Hip Fire)" mean the same thing; the wiki uses
# both. "Ultimate Ability (Mech)" and "Ultimate Ability;;Mech" likewise.
TYPE_SPLIT_RE = re.compile(r"^(.*?)\s*(?:;;\s*(.+)|\(([^)]*)\))\s*$")


def split_type(ability_type):
    """'Weapon;;Hip Fire' -> ('Weapon', 'Hip Fire'). No suffix -> (type, None)."""
    text = (ability_type or "").strip()
    match = TYPE_SPLIT_RE.match(text)
    if not match:
        return text, None
    return match.group(1).strip(), (match.group(2) or match.group(3) or "").strip() or None


# --- article wikitext --------------------------------------------------

def find_templates(text, name_pattern):
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


def split_params(block):
    """Split a template body on its top-level pipes."""
    body = block[2:-2]
    parts, depth, current, index = [], 0, [], 0
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


def parse_params(block):
    """Named parameters of a template, as {lowercased key: raw value}."""
    params = {}
    for part in split_params(block)[1:]:
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().lower().replace(" ", "_")
        if key:
            params[key] = value.strip()
    return params


def _reduce(template):
    """Reduce one innermost {{...}} to text."""
    parts = split_params(template)
    head = parts[0].strip().lower()
    args = [a.strip() for a in parts[1:] if "=" not in a]
    if head in ("tt", "proj", "al", "abilitylink", "hero"):
        # {{tt|shown|tooltip}} shows the first; {{proj|hitscan}} the last.
        return (args[0] if head == "tt" else args[-1]) if args else ""
    return " ".join(args)


def wikitext_to_text(value):
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
