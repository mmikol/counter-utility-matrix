-- INFERENCE (history): the recommendations the model produced - what it was
-- asked, what it was shown, what it answered, the strategies and evidence
-- behind each pick - and the operator's free-form strategy notes.
--
-- Superseded: 010 replaced the notes table with the playbook's mirror, and
-- 014 dropped the recorded tables - nothing is recorded now. The file stays
-- as the sequence's record; a rebuild replays it and the later migrations.
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
