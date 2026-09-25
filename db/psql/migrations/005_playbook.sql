-- PLAYBOOK: judgements about the game, on top of the measurements.
--
-- Nothing in this file is a count of matches. Six tables, six judgements:
-- which playstyle a hero belongs to (the wiki), who answers whom and where a
-- hero is strongest (counterpick.gg), and three of ours, hand-authored in
-- db/data/authored and committed because a rebuild cannot re-scrape them:
-- which heroes work together (synergies), what role shape each style's comp
-- wants (comp_archetypes), and what kind of fight each map rewards
-- (map_playstyle).
--
-- None of these carry a snapshot, region or tier. A judgement is a current
-- read of the game, not a measurement of a population - the dimensioned
-- numbers live in META, and a query that wants both joins them there.
--
-- Depends on heroes (002) and maps (003).

BEGIN;

-- Which playstyle a hero belongs to, straight from the wiki's team
-- composition page. The style vocabulary (dive, brawl, poke) is whatever the
-- page says, kept as text rather than a three-row lookup table: the page is
-- the vocabulary, and a new style there should load, not break.
CREATE TABLE playstyle (
    hero_id   integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    style     text NOT NULL,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hero_id, style)
);

-- Who answers whom: one row means countered_by_id answers hero_id.
--
-- The source publishes two directional columns per hero - "countered by" and
-- "counters" - but they are one claim seen from either side: "X counters Y"
-- IS "Y countered by X". The loader normalises both into this one direction
-- and keeps the union, so a pairing the source lists on only one hero's row
-- (about a third of them) still loads, and one it lists on both collapses to
-- a single row.
--
-- Beware the source's own naming: its field called `counters` is displayed
-- as "Countered by". The loader follows the columns as labelled and explained
-- by their tooltips, not the field names.
CREATE TABLE counters (
    hero_id        integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    countered_by_id integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    source_id      integer NOT NULL REFERENCES sources(source_id),
    cao            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hero_id, countered_by_id),
    CHECK (hero_id <> countered_by_id)
);

-- The maps a hero is strongest on, best first. The source ranks them but
-- publishes no per-map figure, so position is the whole of what it says.
CREATE TABLE map_strategy (
    hero_id   integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    map_id    integer NOT NULL REFERENCES maps(map_id) ON DELETE CASCADE,
    position  smallint NOT NULL,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hero_id, map_id)
);

-- Which heroes work WITH which. Pulled from the Team Synergy column of the
-- "Match-Ups and Team Synergy" section of every released hero's wiki article
-- (pull_synergies). A cell is a claim unless it is a placeholder, rated below
-- GOOD or MIRROR, or unrated and saying there is no synergy. score is 2 when
-- both articles claim the pair, 1 when one does; note is the advice's first
-- sentence, cut to a clause under 120 characters. No snapshot, region or
-- tier: a judgement has no population behind it. Reloaded whole.
--
-- Bidirectional, unlike counters. Synergy is a property of the PAIR: if Mei
-- works with Tracer then Tracer works with Mei - one fact, one row. A counter
-- is an arrow: Mei answering Tracer says nothing about the reverse. So each
-- pair is stored once, lower hero_id first (a CHECK holds it), and read from
-- either side.
CREATE TABLE synergies (
    hero_id   integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    other_id  integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    score     smallint,
    note      text,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hero_id, other_id),
    CHECK (hero_id < other_id)
);


-- What a composition IS, by archetype: the role shape a playstyle wants.
-- playstyle tags heroes; this defines the comp those heroes assemble into -
-- dive wants one engage tank, two flankers who arrive with him, two mobile
-- supports. Authored in db/data/authored/archetypes.csv; the style vocabulary
-- follows the playstyle table by convention. slots describe the standard
-- 1-2-2 shape; Open Queue may flex them, and note says with whom.
CREATE TABLE comp_archetypes (
    style     text NOT NULL,
    role_id   integer NOT NULL REFERENCES roles(role_id),
    slots     smallint NOT NULL,
    note      text,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (style, role_id)
);

-- Which playstyle suits which map: the bridge between MAPS and the playbook.
-- map_strategy picks heroes for a map; this says what KIND of fight the map
-- rewards, which is what a comp is built around. Authored in
-- db/data/authored/map_playstyle.csv, same score scale as synergies.
CREATE TABLE map_playstyle (
    map_id    integer NOT NULL REFERENCES maps(map_id) ON DELETE CASCADE,
    style     text NOT NULL,
    score     smallint,
    note      text,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (map_id, style)
);


CREATE INDEX ix_counters_countered_by ON counters (countered_by_id);
CREATE INDEX ix_map_strategy_map ON map_strategy (map_id);
CREATE INDEX ix_synergies_other ON synergies (other_id);

COMMIT;
