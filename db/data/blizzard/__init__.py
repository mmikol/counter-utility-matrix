"""overwatch.blizzard.com - the official site: page to table.

    heroes          the roster: heroes, roles, subroles, portraits, ability
                    and perk text (Blizzard publishes prose and no numbers)
    meta            the rates page: win, pick and ban rates as a dated
                    snapshot
    attr            a tag's attribute as text, which both read the pages with
    BlizzardError   a page that answered in a shape neither reader knows

Ordinary web pages fetched with db.data.fetch.cached_get; the endpoints and
the `sources` row its pages become are named here, once.
"""

from bs4 import Tag

from db import Source
from db.data.fetch import FetchError

BASE_URL = "https://overwatch.blizzard.com/en-us"
HEROES_URL = BASE_URL + "/heroes/"
RATES_URL = BASE_URL + "/rates/"

# The sources row this module's pages become.
BLIZZARD = Source(code="blizzard", name="Blizzard Overwatch site", url=BASE_URL + "/")


class BlizzardError(FetchError):
    """The site answered, but not with the page expected: it changed shape."""


def attr(node: Tag, name: str) -> str:
    """A tag's attribute as text; KeyError when the tag lacks it. bs4 splits
    a multi-valued attribute (class) into a list, joined back here."""
    value = node[name]
    return value if isinstance(value, str) else " ".join(value)
