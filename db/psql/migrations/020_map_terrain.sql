-- MAP TERRAIN: what the wiki's map articles say about each map's ground.
--
-- A map's style was derived from Blizzard's map rates alone. The terrain is
-- the second source: the strategies read it directly, and a map's style is
-- rectified from both. Filled by pull_terrain; run it after this migration.
BEGIN;

-- One row per map and terrain feature, counted in the map's wiki article.
CREATE TABLE map_terrain (
    map_id       integer NOT NULL REFERENCES maps(map_id) ON DELETE CASCADE,
    feature      text NOT NULL CHECK (feature IN (
                     'chokes', 'interiors', 'high_ground', 'flanks',
                     'sightlines', 'open_ground', 'hazards', 'cover')),
    mentions     integer NOT NULL CHECK (mentions >= 0),
    per_thousand numeric(7,2) NOT NULL CHECK (per_thousand >= 0),
    source_id    integer NOT NULL REFERENCES sources(source_id),
    cao          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (map_id, feature)
);

COMMENT ON TABLE map_terrain IS
    'A map''s terrain, counted in its wiki article (pull_terrain). The sections about the ground and how it is played are kept - gameplay, strategy, the per-stage subsections, a rework''s changes, the infobox''s terrain line - and the lore, place-name lists and media are dropped. Each feature has one pattern (db/data/wiki/terrain.py): chokes, interiors, high_ground, flanks, sightlines, open_ground, hazards, cover. A map whose article has text holds all eight rows, zeros included; a map whose article has under 60 words of kept text holds none. Reloaded whole.';
COMMENT ON COLUMN map_terrain.feature IS
    'chokes: choke points, narrow streets, corridors, tunnels, gates. interiors: indoor and enclosed places. high_ground: high ground, roofs, balconies, ledges, stairs, inclines. flanks: flank routes, side and back ways. sightlines: long sightlines, long streets, sniping. open_ground: open areas, plazas, courtyards, cover said to be missing. hazards: pits, wells, cliffs, lava, environmental kills, knockback off the map. cover: cover, pillars, things to hide behind.';
COMMENT ON COLUMN map_terrain.mentions IS
    'Matches of the feature''s pattern in the kept text.';
COMMENT ON COLUMN map_terrain.per_thousand IS
    'mentions per thousand words of the kept text: comparable between a long article and a short one.';

COMMIT;
