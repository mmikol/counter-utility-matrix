-- 010: STRATEGIES = CONSTRAINTS ∪ HEURISTICS
--
-- The playbook - inference/strategies/*.md - holds exactly two kinds of
-- file. A CONSTRAINT is a limit (`require`, hard unless soft), a scored
-- adjustment (`bonus`/`penalty` while `when` holds), or prose the agent
-- holds a comp to; a HEURISTIC weighs a metric, maximised or minimised.
-- The table that mirrors the files is `strategies`, so the name means one
-- thing: what were "constraints" and "strategies" are constraints now, and
-- what were "goals" are heuristics.
--
-- The operator's free-form notes (the old `strategies` table, loaded from
-- db/data/authored/strategies/) are gone: a note that matters is written as a
-- prose constraint in inference/strategies/, where it is tuned and logged
-- with the rest of the playbook.

DROP TABLE strategies;

-- The mirror of the playbook: one row per markdown file in
-- inference/strategies/ - its kind (constraint | heuristic), the frontmatter
-- a machine scores by (metric, direction, weight, expressions, params) and
-- the prose body a person argues with. Reloaded whole by load_authored so a
-- recommendation can cite the ids it was scored under; the files remain the
-- truth.
CREATE TABLE strategies (
    strategy_id text PRIMARY KEY,        -- the file's id (its stem)
    name         text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('constraint', 'heuristic')),
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

INSERT INTO strategies (strategy_id, name, kind, category, direction, metric, weight, expression, params, body, source_id, cao)
SELECT heuristic_id, name, CASE kind WHEN 'goal' THEN 'heuristic' ELSE 'constraint' END, category, direction, metric, weight, expression, params, body, source_id, cao FROM heuristics;

DROP TABLE heuristics;
