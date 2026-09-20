-- STAGE TERRAIN: what the wiki's map articles say about each stage's ground.
--
-- map_stages held the Control maps' three stages and the Flashpoint maps'
-- five points. pull_maps now also stores every Hybrid map's two phases and an
-- Escort map's stretches where its article names them; Push maps have none.
-- pull_terrain counts the terrain features per stage. Run pull_maps, then
-- pull_terrain, after this migration.
BEGIN;

-- One row per stage and terrain feature, counted in the stage's own text.
CREATE TABLE stage_terrain (
    stage_id     integer NOT NULL REFERENCES map_stages(stage_id) ON DELETE CASCADE,
    feature      text NOT NULL CHECK (feature IN (
                     'chokes', 'interiors', 'high_ground', 'flanks',
                     'sightlines', 'open_ground', 'hazards', 'cover')),
    mentions     integer NOT NULL CHECK (mentions >= 0),
    per_thousand numeric(7,2) NOT NULL CHECK (per_thousand >= 0),
    source_id    integer NOT NULL REFERENCES sources(source_id),
    cao          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (stage_id, feature)
);

COMMENT ON TABLE map_stages IS
    'Stages within a map, in play order (pull_maps). Control maps: the three stages of the Gameplay section''s list (Ilios: Lighthouse, Well, Ruins). Flashpoint maps: the five points of the same list. Hybrid maps: the two phases the wiki''s Hybrid article names, Assault (the capture point) then Escort (the payload). Escort maps: the stretches of the route, only where the map''s article names them - the Gameplay subsections its opening lists (Havana: City Streets, Distillery, Sea Fort). Push maps: none. No source publishes per-stage rates, so map_meta.stage_id stays NULL.';
COMMENT ON TABLE stage_terrain IS
    'A stage''s terrain, counted in the map''s wiki article (pull_terrain) with map_terrain''s features and patterns. A stage''s text: every kept section under a heading that names the stage, and every paragraph or list item elsewhere that names it and no other stage. A Hybrid phase''s text: every Assault or Escort section, attack and defense together; where the article names the route''s stretches, the first is the capture point''s and the rest the payload''s. A stage with 20 words of text or more holds all eight rows, zeros included; a stage with less holds none. Reloaded whole with map_terrain.';
COMMENT ON COLUMN stage_terrain.feature IS
    'The features of map_terrain.feature.';
COMMENT ON COLUMN stage_terrain.mentions IS
    'Matches of the feature''s pattern in the stage''s text.';
COMMENT ON COLUMN stage_terrain.per_thousand IS
    'mentions per thousand words of the stage''s text. A stage''s text is short - 20 to 200 words - so one mention moves this far; compare stages by mentions as well.';

COMMIT;
