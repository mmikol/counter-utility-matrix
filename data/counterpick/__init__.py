"""counterpick.gg: page to table.

    heroes   counters, best maps, and its own win and pick rates (a
             different population from Blizzard's, so their own snapshot)

Ordinary web pages, fetched with data.sources.cached_get. Its table is
server rendered, so no browser is needed, and its filters are query
parameters; the project's scope pins competitive, console, Americas.
"""

BASE_URL = "https://counterpickgg.com/"

# The sources row this module's pages become.
COUNTERPICK = ("counterpick", "counterpick.gg", "https://counterpickgg.com/")

from data import sources

GAMEMODE = "competitive"
PLATFORM = sources.PLATFORM        # the site spells it the same way

# their region values -> the code used in our regions table
# Americas only, to match the rest of the database. The site also publishes
# "all", europe and asia-pacific; they are deliberately not read, because a
# database scoped to one region should not carry rows from another.
REGIONS = {
    "americas": sources.REGION,
}
