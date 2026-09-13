"""Extracting team-composition playstyles from the wiki.

A hero appears under every playstyle they suit, so the lists overlap by design.
"""

import re

from data.sources.wiki import WikiError

COMPOSITION_PAGE = "Team Composition"

# "=== Dive heroes ===" opens the hero list for the Dive playstyle.
HERO_SECTION_RE = re.compile(r"^===\s*(.+?)\s+heroes\s*===\s*$", re.M | re.I)
ANY_HEADING_RE = re.compile(r"^=+.*=+\s*$", re.M)
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def parse_playstyles(text):
    """[(code, name, [hero_name])] in page order."""
    playstyles = []
    for match in HERO_SECTION_RE.finditer(text):
        name = match.group(1).strip()
        body = text[match.end():]
        following = ANY_HEADING_RE.search(body)
        if following:
            body = body[: following.start()]
        heroes = [link.strip() for link in LINK_RE.findall(body)]
        if heroes:
            playstyles.append((name.lower(), name, heroes))

    if not playstyles:
        raise WikiError("%s: no '<name> heroes' sections found" % COMPOSITION_PAGE)
    return playstyles
