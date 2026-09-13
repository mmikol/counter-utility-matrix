-- META: how heroes actually perform - measurements, nothing else.
--
-- Win, pick and ban rates by hero, by map, by rank, all scraped and all
-- current: a dated snapshot records which population each figure was measured
-- on. Judgements about the game - playstyles, counters, synergies - live in
-- 005_playbook, so that everything in this file is something a source counted.
--
-- Depends on heroes (002) and maps (003).

BEGIN;

CREATE TABLE regions (
    region_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code      text NOT NULL UNIQUE,
    name      text NOT NULL UNIQUE,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now()
);

-- 'all' is a real member of the tier dimension: it is the unfiltered figure
-- the page reports, and keeping it as a row avoids a nullable dimension key.
-- Region has no such member. Everything here is the Americas, so an "all
-- regions" row would be a second population mixed in beside it.
--
-- Bronze through Champion, plus the "All Tiers" aggregate the source reports
-- alongside them. rank_order follows the source's own ordering.
CREATE TABLE competitive_tiers (
    tier_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code       text NOT NULL UNIQUE,
    name       text NOT NULL UNIQUE,
    rank_order smallint NOT NULL,
    source_id  integer NOT NULL REFERENCES sources(source_id),
    cao        timestamptz NOT NULL DEFAULT now()
);

-- The game versions the meta moves with. A win rate is true of a patch, so
-- a snapshot records which patch was live when it was captured - that is what
-- makes an accumulated series interpretable ("these rates predate the nerf").
-- Scraped from the wiki's Patches cargo table; name is the wiki's own page
-- name, since Blizzard ships most balance patches unversioned.
-- Seasons: the coarser delineator. A patch tweaks numbers; a season swaps
-- the hero pool and map rotation, so a snapshot records both. Authored in
-- data/proprietary/seasons.csv rather than scraped: the wiki's season pages
-- are lore articles, and its current-era page carries no dates at all.
CREATE TABLE seasons (
    season_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name      text NOT NULL UNIQUE,
    started   date NOT NULL,
    note      text,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_seasons_started ON seasons (started);

CREATE TABLE patches (
    patch_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name      text NOT NULL UNIQUE,
    released  date NOT NULL,
    platform  text,
    url       text,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_patches_released ON patches (released);

CREATE TABLE meta_snapshots (
    snapshot_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    captured_at timestamptz NOT NULL,
    queue       text NOT NULL,
    -- Platform, not input device. The source's query parameter is called
    -- "input" but its values are PC and Console, which say nothing about
    -- whether a controller or a mouse was held - both platforms support both.
    -- Recording it as an input device would assert something no source states.
    platform    text NOT NULL,
    -- The device in the player's hands, which is not the same thing as the
    -- platform - but on console it is derivable: console Overwatch supports
    -- no input except a controller, so platform = console entails
    -- input = controller, and both current sources are console. NULL is for
    -- populations where the device genuinely is not knowable - a PC snapshot
    -- mixes controller and mouse-and-keyboard players, and no source
    -- separates them.
    input       text,
    -- The most recent patch released on or before the capture. NULL only if
    -- the patches pipeline has not run - the orchestrator orders it first.
    patch_id    integer REFERENCES patches(patch_id),
    -- The season live at capture. Backfilled by the seasons loader (it runs
    -- after the snapshot writers), then stamped directly on later captures.
    season_id   integer REFERENCES seasons(season_id),
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (captured_at, queue, platform, input)
);

-- Rates by region and tier. All rates are percentages as published
-- (47.9 means 47.9%). These rows are across all maps.
CREATE TABLE hero_meta (
    hero_meta_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id   integer NOT NULL REFERENCES meta_snapshots(snapshot_id) ON DELETE CASCADE,
    hero_id       integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    region_id     integer NOT NULL REFERENCES regions(region_id),
    tier_id       integer NOT NULL REFERENCES competitive_tiers(tier_id),
    win_rate      numeric,
    pick_rate     numeric,
    ban_rate      numeric,
    source_id     integer NOT NULL REFERENCES sources(source_id),
    cao           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (snapshot_id, hero_id, region_id, tier_id)
);

-- Rates per map, and per tier within a map. The source's filters compose, so
-- a hero's rates on King's Row in Bronze are a different figure from the same
-- hero's rates on King's Row overall - and both are published.
--
-- tier_id 'all' is the unfiltered figure for that map, which keeps the
-- dimension key non-nullable. Region is not broken out here: map x tier is
-- already 240 requests, and map x tier x region would be 720.
CREATE TABLE map_meta (
    map_meta_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id integer NOT NULL REFERENCES meta_snapshots(snapshot_id) ON DELETE CASCADE,
    hero_id     integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    map_id      integer NOT NULL REFERENCES maps(map_id) ON DELETE CASCADE,
    tier_id     integer NOT NULL REFERENCES competitive_tiers(tier_id),
    region_id   integer NOT NULL REFERENCES regions(region_id),
    -- NULL means the whole map, which is every row today. See map_stages.
    stage_id    integer REFERENCES map_stages(stage_id) ON DELETE CASCADE,
    win_rate    numeric,
    pick_rate   numeric,
    ban_rate    numeric,
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now(),
    -- NULLS NOT DISTINCT so two whole-map rows collide as they should:
    -- by default Postgres treats NULL stage_id as always unique, which would
    -- let the same hero/map/tier be inserted twice.
    UNIQUE NULLS NOT DISTINCT
        (snapshot_id, hero_id, map_id, tier_id, region_id, stage_id)
);

CREATE INDEX ix_hero_meta_hero ON hero_meta (hero_id);
CREATE INDEX ix_hero_meta_tier ON hero_meta (tier_id);
CREATE INDEX ix_map_meta_hero ON map_meta (hero_id);
CREATE INDEX ix_map_meta_map ON map_meta (map_id);
CREATE INDEX ix_map_meta_tier ON map_meta (tier_id);

COMMIT;
