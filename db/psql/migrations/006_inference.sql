-- INFERENCE: what the model was asked, what it was shown, what it answered.
--
-- The proprietary layer's output side. A recommendation here is an opinion
-- the database PRODUCED, not one it recorded - so every row must be
-- explainable: the strategies it read, the evidence lines it was shown, and
-- which of them justified each pick, all kept alongside the answer.
--
-- These tables are a session log. `rebuild` drops them like everything else;
-- the durable record is the transcript each recommendation also writes into
-- db/data/authored/recommendations/, which is committed and survives.
--
-- Depends on heroes (002), maps (003) and the playbook (005).

BEGIN;

-- Free-form strategy notes, authored as markdown files in
-- db/data/authored/strategies/ and loaded whole: the model conditions on
-- the prose, so no structure is imposed on it.
CREATE TABLE strategies (
    strategy_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title       text NOT NULL UNIQUE,
    body        text NOT NULL,
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE recommendations (
    rec_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    request     text NOT NULL,           -- the question, as asked
    map_id      integer REFERENCES maps(map_id),
    model       text NOT NULL,           -- exact model id that answered
    playstyle   text,                    -- the archetype the comp commits to
    reasoning   text NOT NULL,           -- the model's overall argument
    prompt      text NOT NULL,           -- full prompt, for reproducibility
    response    text NOT NULL,           -- full structured answer, verbatim
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE recommendation_picks (
    rec_id    integer NOT NULL REFERENCES recommendations(rec_id) ON DELETE CASCADE,
    position  smallint NOT NULL,
    hero_id   integer NOT NULL REFERENCES heroes(hero_id),
    why       text NOT NULL,             -- one sentence per pick
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rec_id, position),
    UNIQUE (rec_id, hero_id)
);

-- The board's fact lines the decider cited, by tag (F1, F2, ...). hero_id links a
-- citation to the specific pick it justified; NULL means it supported the
-- comp as a whole.
CREATE TABLE recommendation_evidence (
    rec_id       integer NOT NULL REFERENCES recommendations(rec_id) ON DELETE CASCADE,
    tag          text NOT NULL,
    source_table text NOT NULL,          -- which table the line was drawn from
    description  text NOT NULL,          -- the line as the model saw it
    hero_id      integer REFERENCES heroes(hero_id),
    source_id    integer NOT NULL REFERENCES sources(source_id),
    cao          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rec_id, tag, hero_id)
);

COMMIT;
