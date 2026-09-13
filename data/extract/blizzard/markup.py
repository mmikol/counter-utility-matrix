"""Reading Blizzard's page HTML.

Turns a parsed page node into plain gameplay text.

Used by the blizzard extractors.
"""

import re

WHITESPACE_RE = re.compile(r"\s+")


def to_text(node):
    """Plain gameplay text from a BeautifulSoup node.

    Ability descriptions embed input-icon <img> tags mid-sentence and wrap
    numbers in coloured <span>s. Both are dropped: the schema stores gameplay
    text, not markup or media.
    """
    for image in node.find_all("img"):
        image.decompose()
    return WHITESPACE_RE.sub(" ", node.get_text(" ", strip=True)).strip()
