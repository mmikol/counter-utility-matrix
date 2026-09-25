"""Unit tests: the roster page and a hero page read into subroles, role
icons, hero cards, abilities and perks, and the pull over them. No database, no
network: the pages are inline HTML."""

import pytest
from bs4 import BeautifulSoup

from db.data import fetch
from db.data.blizzard import BlizzardError
from db.data.blizzard import heroes as blizzard_heroes
from db.data.blizzard.heroes import (
    AbilityText,
    HeroCard,
    Subrole,
    node_text,
    parse_abilities,
    parse_icons,
    parse_perks,
    parse_roster,
    parse_subroles,
)
from tests.db.recording import RecordingConnection


def soup(page):
    return BeautifulSoup(page, "html.parser")


# --- the roster page ------------------------------------------------------

SUBROLES = """
<div class="subrole" data-role="support" data-subrole="tactician">
    <span>Tactician: </span>
    <span>Ult charge <img src="i.png"> builds   faster.</span>
</div>
<div class="subrole" data-role="damage" data-subrole="flanker">
    <span>Flanker:</span>
    <span>Health packs heal more.</span>
</div>
<div class="subrole" data-role="tank" data-subrole="bruiser">
    <span>Bruiser</span>
</div>
"""

FILTERS = """
<select>
    <option class="role" data-role="all-heroes" style="background-image:url(all.svg)">All</option>
    <option class="role" data-role="tank" style="background-image:url(tank.svg)">Tank</option>
    <option class="role" data-role="tank">Tank</option>
    <option class="role" data-role="damage"
            style="background-image:url('damage.svg')">Damage</option>
    <option class="role" data-role="support"
            style="background-image:url(&quot;support.png&quot;)">Support</option>
</select>
"""

CARDS = """
<a class="hero-card" data-role="support" data-subrole="tactician" href="/heroes/ana">
    <blz-card icon="support.svg">
        <blz-image class="heroCardPortrait" src="ana.png"></blz-image>
        <h2 slot="heading">Ana</h2>
    </blz-card>
</a>
<a class="hero-card" data-role="damage" data-subrole="flanker" href="/en-us/heroes/tracer/">
    <blz-card icon="card-damage.svg">
        <h2 slot="heading">Tracer</h2>
    </blz-card>
</a>
"""

ROSTER = SUBROLES + FILTERS + CARDS


def test_node_text_reads_the_words_and_takes_the_images_out_of_the_tree():
    node = soup('<p><img src="lmb.png"> Long-range   rifle <span>75</span> damage.</p>').p
    assert node_text(node) == "Long-range rifle 75 damage."
    assert node.find("img") is None


def test_a_subrole_is_its_label_and_its_passive():
    # the one-span div is no subrole; the passive's icon is dropped
    assert parse_subroles(soup(ROSTER)) == {
        "tactician": Subrole(code="tactician", role_code="support", name="Tactician",
                             passive_description="Ult charge builds faster."),
        "flanker": Subrole(code="flanker", role_code="damage", name="Flanker",
                           passive_description="Health packs heal more."),
    }


def test_a_roster_with_no_subroles_is_refused():
    with pytest.raises(BlizzardError, match="no subroles"):
        parse_subroles(soup(CARDS))


def test_a_filter_icon_beats_the_card_icon():
    # bare, single- and double-quoted url() all read; all-heroes is no role,
    # and a styleless option draws nothing
    assert parse_icons(soup(ROSTER)) == {
        "tank": "tank.svg", "damage": "damage.svg", "support": "support.png"}
    # a role with no filter icon falls back to its cards' icon
    assert parse_icons(soup(CARDS)) == {"support": "support.svg", "damage": "card-damage.svg"}


def test_a_hero_card_gives_the_slug_its_link_ends_in():
    # with or without a trailing slash; no portrait is None
    assert parse_roster(soup(ROSTER)) == [
        HeroCard(slug="ana", name="Ana", role_code="support", subrole_code="tactician",
                 portrait_url="ana.png"),
        HeroCard(slug="tracer", name="Tracer", role_code="damage", subrole_code="flanker",
                 portrait_url=None),
    ]


@pytest.mark.parametrize("page, reason", [
    (
        '<a class="hero-card" id="c1" data-role="tank" data-subrole="bruiser"'
        ' href="/heroes/rein"><blz-card></blz-card></a>', "missing a name or link: 'c1'"),
    (
        '<a class="hero-card" id="c2" data-role="tank" data-subrole="bruiser">'
        '<h2 slot="heading">Reinhardt</h2></a>', "missing a name or link: 'c2'"),
    (SUBROLES, "no hero cards"),
], ids=["no name", "no link", "no cards"])
def test_a_roster_without_whole_hero_cards_is_refused(page, reason):
    with pytest.raises(BlizzardError, match=reason):
        parse_roster(soup(page))


# --- a hero page ----------------------------------------------------------

SLIDE = (
    '<blz-feature slot="slide"><h3 class="heading">%s</h3>'
    '<p slot="description">%s</p></blz-feature>')
CAROUSEL = "<blz-carousel>%s%s</blz-carousel>" % (
    SLIDE % ("Biotic Rifle", '<img src="lmb.png"> Long-range rifle that heals allies.'),
    SLIDE % ("Sleep Dart", "Puts an enemy to sleep."))

PERK = ('<div class="perk-details"><h3 slot="subheading">%s</h3>'
        '<div slot="description">%s</div></div>')
MINOR = '<div class="perk-category minor">%s%s</div>' % (
    PERK % ("Shrike", "Sleep Dart recharges faster."),
    PERK % ("Speed Serum", "Biotic Rifle speeds allies."))
MAJOR = '<div class="perk-category major">%s%s</div>' % (
    PERK % ("Headhunter", "Biotic Rifle scopes deal more."),
    PERK % ("Biotic Bounce", "Biotic Grenade bounces."))
PERKS = '<blz-section id="perks">%s%s</blz-section>' % (MINOR, MAJOR)
STADIUM = (
    '<blz-section id="stadium"><div class="perk-category minor">%s</div></blz-section>'
    % (PERK % ("Power Surge", "A Stadium Power.")))

HERO = CAROUSEL + PERKS + STADIUM


def test_a_hero_page_gives_its_abilities_in_carousel_order():
    assert parse_abilities(soup(HERO), "ana") == [
        AbilityText(name="Biotic Rifle", description="Long-range rifle that heals allies.",
                    position=0),
        AbilityText(name="Sleep Dart", description="Puts an enemy to sleep.", position=1),
    ]


@pytest.mark.parametrize("page, reason", [
    (PERKS, "ana: expected 1 carousel, found 0"),
    (CAROUSEL + CAROUSEL, "ana: expected 1 carousel, found 2"),
    ("<blz-carousel></blz-carousel>", "ana: no abilities"),
    (
        '<blz-carousel><blz-feature slot="slide"><h3 class="heading">Biotic Rifle</h3>'
        "</blz-feature></blz-carousel>", "ana: ability slide 0 is malformed"),
], ids=["no carousel", "two carousels", "no slides", "no description"])
def test_a_malformed_hero_page_is_refused_by_name(page, reason):
    with pytest.raises(BlizzardError, match=reason):
        parse_abilities(soup(page), "ana")


def test_stadium_powers_are_not_read_as_perks():
    perks = parse_perks(soup(HERO), "ana")
    assert [(p.tier_id, p.position, p.name) for p in perks] == [
        (1, 1, "Shrike"), (1, 2, "Speed Serum"), (2, 1, "Headhunter"), (2, 2, "Biotic Bounce")]
    assert perks[0].description == "Sleep Dart recharges faster."


@pytest.mark.parametrize("page, reason", [
    (CAROUSEL, "ana: no perks section"),
    (
        '<blz-section id="perks"><div class="perk-category">%s%s</div></blz-section>'
        % (PERK % ("A", "a"), PERK % ("B", "b")), "ana: perk category has no tier"),
    (
        '<blz-section id="perks"><div class="perk-category minor">%s</div></blz-section>'
        % (PERK % ("A", "a") * 3), "ana: expected 2 minor perks, found 3"),
    (
        '<blz-section id="perks"><div class="perk-category minor">%s'
        '<div class="perk-details"><h3 slot="subheading">B</h3></div></div></blz-section>'
        % (PERK % ("A", "a")), "ana: malformed minor perk"),
    ('<blz-section id="perks">%s</blz-section>' % MINOR, "ana: expected 4 perks, found 2"),
], ids=["no section", "no tier", "three perks", "no description", "one category"])
def test_a_malformed_perks_section_is_refused_by_name(page, reason):
    with pytest.raises(BlizzardError, match=reason):
        parse_perks(soup(page), "ana")


# --- the pull over the pages ------------------------------------------------

def test_a_hero_page_that_will_not_fetch_is_recorded_and_the_rest_are_stored(monkeypatch):
    """A hero page gone from the cache and the network alike is one missing
    line, not a failed pull: the roster and every other hero page are still
    stored, and the missing hero's rows are left as they were."""
    def pages(pull, url, key, **kwargs):
        if key == "ana":
            raise fetch.FetchError("%s failed after 3 attempts: gone" % url)
        return HERO if key == "tracer" else ROSTER
    monkeypatch.setattr(blizzard_heroes, "cached_get", pages)
    connection = RecordingConnection()
    summary = blizzard_heroes.run(connection, fetch.PullContext(None, log=lambda line: None))
    assert [line.split(":")[0] for line in summary["missing"]] == ["Ana"]
    assert summary["heroes"] == 2 and summary["abilities"] == 2 and summary["perks"] == 4
    [cursor] = connection.cursors
    stored = [
        params[0] for sql, params in cursor.statements if sql.startswith("INSERT INTO heroes")]
    assert stored == ["ana", "tracer"]
    owners = {
        params[0] for sql, params in cursor.statements
        if sql.startswith(("INSERT INTO abilities", "INSERT INTO perks"))}
    assert len(owners) == 1                  # one hero's rows, Tracer's; none written for Ana
    # only a parsed page's hero may lose a wiki kit: Ana's is never cleared
    assert cursor.written("DELETE FROM") == [(["tracer"], 1), (["tracer"], 1)]


def test_a_changed_hero_page_fails_the_pull_and_is_not_counted_missing(monkeypatch):
    """A page that fetched but no longer reads as a hero page is the site
    changing shape, not a page that would not fetch: the pull raises before
    it writes anything, and no hero is counted missing."""
    def pages(pull, url, key, **kwargs):
        return "<main></main>" if key == "tracer" else HERO if key == "ana" else ROSTER
    monkeypatch.setattr(blizzard_heroes, "cached_get", pages)
    connection = RecordingConnection()
    with pytest.raises(BlizzardError, match="tracer: expected 1 carousel, found 0"):
        blizzard_heroes.run(connection, fetch.PullContext(None, log=lambda line: None))
    assert connection.cursors == [] and connection.commits == 0
