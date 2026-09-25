-- UNREAD COLUMNS: what the pulls wrote and nothing read.
--
-- raw_value on the three stat tables: the wiki's markup beside value_text,
-- about half the bytes of their mirror. The page cache keeps that markup,
-- and db_rebuild re-parses from it.
-- patches.platform and patches.url: a patch is read by its name and its
-- release day only.
-- subroles.icon_url: the board draws the role icons, never a subrole's.
-- stat_keys.label: the code with spaces. stat_keys.unit: a copy of
-- STAT_UNITS in db/data/wiki/kits/kit_store.py, the one source of the unit
-- a bare value is read in.
-- roles.name: the code capitalised; the facts capitalise the code.
--
-- The pulls stop writing them in the same change. The comments below
-- restate what 002 and 007 said about them.
BEGIN;

ALTER TABLE ability_stats DROP COLUMN raw_value;
ALTER TABLE weapon_stats DROP COLUMN raw_value;
ALTER TABLE perk_stats DROP COLUMN raw_value;
ALTER TABLE patches DROP COLUMN platform, DROP COLUMN url;
ALTER TABLE subroles DROP COLUMN icon_url;
ALTER TABLE stat_keys DROP COLUMN label, DROP COLUMN unit;
ALTER TABLE roles DROP COLUMN name;

COMMENT ON TABLE ability_stats IS
    'One row per measurement, not per stat. A wiki value like "0.67 shots/s (max charge); 3.33 shots/s (min charge)" becomes two rows sharing a stat_key, separated by condition. Units are split into the unit on top and the unit underneath, so nothing has to parse a "/" to know what a number means. denominator_value carries the magnitude underneath - 1 for a plain rate, or the window a burst spans: "125 m/s" is 125 meters / seconds over 1, "1.25 shots/s" 1.25 shots / seconds over 1, "75 over 0.59 seconds" 75 hp / seconds over 0.59, and "14 seconds" 14 seconds with no unit underneath. A rate is therefore always value / denominator_value per unit_denominator. value is NULL where the measurement is not numeric (shot types, "partial"). value_text keeps the text each measurement was read from, so anything the parser misreads stays recoverable; the wiki markup behind it stays in the page cache. weapon_stats and perk_stats hold the same measurements for a weapon''s firing config and for a perk.';

COMMENT ON TABLE stat_keys IS
    'The stat vocabulary: one row per stat code a kit carries, added by pull_kits and never reloaded. A value with no unit of its own is read in its stat''s unit from STAT_UNITS in db/data/wiki/kits/kit_store.py ("damage = 90" is 90 hp), stored as the measurement''s unit_numerator.';

COMMENT ON COLUMN roles.icon_url IS
    'the icon Blizzard''s role filter draws for the role, else its hero cards'' icon; the board draws it beside the role. No subrole carries one.';

COMMIT;
