-- HEURISTICS: the playbook's tunable brain.
--
-- The playbook's other tables hold judgements about heroes and maps. These
-- two hold judgements about HOW TO JUDGE: the catalog of every consideration
-- the dossier mathematically encodes when weighing a team composition, and
-- the numeric thresholds those formulas run on. Both are authored in
-- data/proprietary (heuristics.csv, heuristic_params.csv) and reloaded
-- whole-file, because tuning them is meant to be continuous: edit the CSV,
-- re-run the loader, and the next dossier build computes with the new values
-- - no code change.
--
-- heuristics is the catalog. One row per consideration, numbered, with the
-- formula written out and an honest status: `live` means the dossier emits
-- it today (the tag column is the evidence tag it appears under), `ready`
-- means the current schema can compute it but nothing emits it yet, and
-- `blocked` names a formula whose inputs the database does not hold yet -
-- kept in the catalog so the gap stays visible instead of forgotten.
--
-- heuristic_params is the dial panel. Each row is one named constant a live
-- formula reads at build time; the same names exist as defaults in
-- data/proprietary/dossier.py so the dossier still runs against a database
-- that predates this table. A row here overrides the default.

CREATE TABLE heuristics (
    heuristic_id smallint PRIMARY KEY,
    tag          text NOT NULL,
    name         text NOT NULL UNIQUE,
    category     text NOT NULL,
    formula      text NOT NULL,
    inputs       text NOT NULL,
    status       text NOT NULL CHECK (status IN ('live', 'ready', 'blocked')),
    rationale    text NOT NULL,
    source_id    integer NOT NULL REFERENCES sources(source_id),
    cao          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE heuristic_params (
    code      text PRIMARY KEY,
    value     numeric NOT NULL,
    note      text NOT NULL,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now()
);
