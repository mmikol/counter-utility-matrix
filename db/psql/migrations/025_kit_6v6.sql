-- THE 6V6 KIT: what the wiki's hero articles say changes when the game is
-- played six a side. The owner plays 6v6 Open Queue, and the kit tables
-- hold the 5v5 figures the Cargo table publishes; the articles carry the
-- 6v6 ones beside them - an infobox's health6v6, shield6v6 and armor6v6,
-- and each Ability_details block's 6v6_details lines. pull_kits reads both
-- from the same article fetch and stores them beside the 5v5 numbers, which
-- stay where they are, so a 5v5 reading of the kit stays possible. The
-- facts layer lays the 6v6 figures over the 5v5 ones for the format in
-- force (facts.draft.KIT_FORMAT).
BEGIN;

ALTER TABLE heroes
    ADD COLUMN health_6v6 smallint,
    ADD COLUMN shield_6v6 smallint,
    ADD COLUMN armor_6v6 smallint;

COMMENT ON TABLE heroes IS
    'The composite foreign key makes it impossible to pair a hero with a subrole belonging to a different role than the hero''s own. health, shield and armor are the hero''s own pool in 5v5, all in hp. Blizzard publishes none of them, so pull_kits fills them in; a hero with no shield or armor leaves those NULL rather than storing a zero the source never states. health_6v6, shield_6v6 and armor_6v6 are the same pool in 6v6 where the article''s infobox gives one, NULL where it gives none and the 5v5 figure stands; a value that is not a whole number is rejected, never stored.';

-- The 6v6 lines of each hero's kit: one row per line of the 6v6_details
-- field an Ability_details block carries (pull_kits). piece is the block's
-- ability name as the wiki writes it - an ability, a weapon or a perk of
-- the hero. A line that says a stat increased or was reduced from A to B
-- carries the stat its words name (stat_key_id, NULL where the pull maps
-- none), from_value A and to_value B, a multiplier the wiki writes 2.5x
-- held as the kit holds it, a percent (250). Any other line carries its
-- words alone. A line whose figures do not parse is rejected, never
-- stored. The 5v5 rows are left as they are; facts/kit_format.py moves a
-- stat row from A to B when the format in force is 6v6. Reloaded whole with
-- the kits.
CREATE TABLE kit_6v6 (
    kit_6v6_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hero_id     integer NOT NULL REFERENCES heroes(hero_id),
    piece       text NOT NULL,
    stat_key_id integer REFERENCES stat_keys(stat_key_id),
    from_value  numeric,
    to_value    numeric,
    value_text  text NOT NULL,
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (hero_id, piece, value_text),
    CHECK ((from_value IS NULL) = (to_value IS NULL)),
    CHECK (stat_key_id IS NULL OR from_value IS NOT NULL)
);

CREATE INDEX ix_kit_6v6_hero ON kit_6v6 (hero_id);

COMMENT ON COLUMN kit_6v6.piece IS 'the ability, weapon or perk the line changes, as the article names it';
COMMENT ON COLUMN kit_6v6.from_value IS 'the 5v5 figure the line moves from; NULL for a line with no figure';
COMMENT ON COLUMN kit_6v6.to_value IS 'the 6v6 figure it moves to';
COMMENT ON COLUMN kit_6v6.value_text IS 'the line as the wiki words it';

COMMIT;
