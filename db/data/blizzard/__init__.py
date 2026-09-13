"""overwatch.blizzard.com - the official site: page to table.

    heroes   the roster: heroes, roles, subroles, portraits, ability and
             perk text (Blizzard publishes prose and no numbers)
    meta     the rates page: win, pick and ban rates as a dated snapshot

Ordinary web pages fetched with db.data.fetch.cached_get; the endpoints and
the `sources` row its pages become are named here, once.
"""

BASE_URL = "https://overwatch.blizzard.com/en-us"
HEROES_URL = BASE_URL + "/heroes/"
RATES_URL = BASE_URL + "/rates/"

# The sources row this module's pages become.
BLIZZARD = ("blizzard", "Blizzard Overwatch site", "https://overwatch.blizzard.com/en-us/")
