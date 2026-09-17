-- THREE LAYERS: what the data / user / inference layers need on top of the
-- baseline schema.
--
-- Three additions and the inference layer's catalog:
--
--   heroes.portrait_url, roles.icon_url, subroles.icon_url
--       The user layer draws the roster the way the game does. These are
--       pointers to Blizzard's own hosted images, read off the roster page
--       the data layer already scrapes; no media is stored, only its URL.
--   abilities.keywords, weapon_configs.keywords
--       The wiki tags every ability with gameplay keywords ("hitscan",
--       "strong movement", "stun", "lesser cleanse", "ignore barrier").
--       Stored verbatim, '::'-separated as the wiki writes them, they are
--       what lets the facts layer count engage tools, peel, anti-air and
--       cleanses instead of leaving those formulas blocked.
--   heuristics
--       The inference layer's catalog, mirrored from markdown files - then
--       inference/heuristics/, one file per rule of three kinds (constraint,
--       goal, strategy), frontmatter (metric, direction, weight,
--       expressions) over a prose body. The files are the truth; the loader
--       clears and reloads. History: 010 renamed the table `strategies` and
--       the kinds constraint and heuristic, 013 added assumptions.

BEGIN;

ALTER TABLE heroes ADD COLUMN portrait_url text;
ALTER TABLE roles ADD COLUMN icon_url text;
ALTER TABLE subroles ADD COLUMN icon_url text;
ALTER TABLE abilities ADD COLUMN keywords text;
ALTER TABLE weapon_configs ADD COLUMN keywords text;

CREATE TABLE heuristics (
    heuristic_id text PRIMARY KEY,        -- the file's id (its stem)
    name         text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('constraint', 'goal', 'strategy')),
    category     text NOT NULL,
    direction    text CHECK (direction IN ('maximize', 'minimize')),
    metric       text,                    -- the fact key a goal reads
    weight       numeric,                 -- goal weight / rule magnitude
    expression   text,                    -- require / when / bonus / penalty, joined
    params       text,                    -- the dials, as key=value pairs
    body         text NOT NULL,           -- the prose, verbatim
    source_id    integer NOT NULL REFERENCES sources(source_id),
    cao          timestamptz NOT NULL DEFAULT now()
);

COMMIT;
