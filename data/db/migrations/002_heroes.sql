-- HEROES: the roster, and everything a hero is made of.
--
-- Roles and subroles, abilities, weapons and their firing configs, perks, and
-- the stat measurements attached to each.
--
-- Text comes from overwatch.blizzard.com, which publishes prose only. Every
-- number comes from overwatch.fandom.com, mostly via its Cargo tables.

BEGIN;

CREATE TABLE roles (
    role_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code      text NOT NULL UNIQUE,
    name      text NOT NULL UNIQUE,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now()
);

-- The ten subroles, each belonging to exactly one role, each carrying the
-- passive it grants (e.g. "Tactician: Store excess ultimate charge.").
CREATE TABLE subroles (
    subrole_id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role_id             integer NOT NULL REFERENCES roles(role_id),
    code                text NOT NULL UNIQUE,
    name                text NOT NULL,
    passive_description text NOT NULL,
    source_id           integer NOT NULL REFERENCES sources(source_id),
    cao                 timestamptz NOT NULL DEFAULT now(),
    UNIQUE (role_id, name),
    UNIQUE (subrole_id, role_id)
);

-- The composite foreign key makes it impossible to pair a hero with a subrole
-- belonging to a different role than the hero's own.
-- health, shield and armor are the hero's own pool, all in hp. Blizzard
-- publishes none of them, so the wiki pipeline fills them in; a hero with no
-- shield or armor leaves those NULL rather than storing a zero the source
-- never states.
CREATE TABLE heroes (
    hero_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug       text NOT NULL UNIQUE,
    name       text NOT NULL UNIQUE,
    role_id    integer NOT NULL REFERENCES roles(role_id),
    subrole_id integer NOT NULL REFERENCES subroles(subrole_id),
    health     smallint,
    shield     smallint,
    armor      smallint,
    source_id  integer NOT NULL REFERENCES sources(source_id),
    cao        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (subrole_id, role_id) REFERENCES subroles(subrole_id, role_id)
);

CREATE TABLE ability_kinds (
    kind_id   smallint PRIMARY KEY,
    code      text NOT NULL UNIQUE,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now()
);
-- The vocabulary is the wiki's ability_type field.
INSERT INTO ability_kinds (kind_id, code, source_id)
SELECT v.kind_id, v.code, s.source_id
FROM (VALUES (1, 'weapon'), (2, 'ability'), (3, 'ultimate'), (4, 'passive'))
     AS v(kind_id, code), sources s
WHERE s.code = 'wiki';

-- kind_id is NULL until the wiki pipeline sets it. Blizzard's markup labels
-- neither weapons nor ultimates, and its ordering does not identify them
-- either, so nothing is guessed at scrape time.
CREATE TABLE abilities (
    ability_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hero_id     integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    kind_id     smallint REFERENCES ability_kinds(kind_id),
    name        text NOT NULL,
    description text NOT NULL,
    position    smallint NOT NULL,
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (hero_id, name),
    UNIQUE (hero_id, position)
);

CREATE INDEX ix_abilities_ultimate ON abilities (hero_id) WHERE kind_id = 3;

CREATE TABLE perk_tiers (
    tier_id      smallint PRIMARY KEY,
    code         text NOT NULL UNIQUE,
    name         text NOT NULL UNIQUE,
    unlock_level smallint NOT NULL,
    source_id    integer NOT NULL REFERENCES sources(source_id),
    cao          timestamptz NOT NULL DEFAULT now()
);
INSERT INTO perk_tiers (tier_id, code, name, unlock_level, source_id)
SELECT v.tier_id, v.code, v.name, v.unlock_level, s.source_id
FROM (VALUES (1, 'minor', 'Minor Perk', 2), (2, 'major', 'Major Perk', 3))
     AS v(tier_id, code, name, unlock_level), sources s
WHERE s.code = 'blizzard';

CREATE TABLE perks (
    perk_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hero_id     integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    tier_id     smallint NOT NULL REFERENCES perk_tiers(tier_id),
    name        text NOT NULL,
    description text NOT NULL,
    position    smallint NOT NULL CHECK (position IN (1, 2)),
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (hero_id, name),
    UNIQUE (hero_id, tier_id, position)
);

CREATE INDEX ix_heroes_role ON heroes (role_id);
CREATE INDEX ix_heroes_subrole ON heroes (subrole_id);
CREATE INDEX ix_abilities_hero ON abilities (hero_id);
CREATE INDEX ix_perks_hero ON perks (hero_id);

-- One row per weapon. A weapon's firing modes are configs, not weapons: Ana
-- carries one Biotic Rifle, fired from the hip or down the sights.
CREATE TABLE weapons (
    weapon_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hero_id   integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    name      text NOT NULL,
    position  smallint NOT NULL,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (hero_id, name)
);

CREATE TABLE weapon_config_slots (
    slot_id   smallint PRIMARY KEY,
    code      text NOT NULL UNIQUE,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now()
);
-- The vocabulary is the wiki's "Weapon;;<mode>" suffix.
INSERT INTO weapon_config_slots (slot_id, code, source_id)
SELECT v.slot_id, v.code, s.source_id
FROM (VALUES (1, 'default'), (2, 'primary_fire'), (3, 'secondary_fire'),
             (4, 'hip_fire'), (5, 'ads')) AS v(slot_id, code), sources s
WHERE s.code = 'wiki';

-- weapon_type lives here rather than on the weapon because it varies by
-- config: Ana's Biotic Rifle is a projectile from the hip and hitscan in ADS.
CREATE TABLE weapon_configs (
    config_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    weapon_id   integer NOT NULL REFERENCES weapons(weapon_id) ON DELETE CASCADE,
    slot_id     smallint NOT NULL REFERENCES weapon_config_slots(slot_id),
    name        text NOT NULL,
    weapon_type text,
    position    smallint NOT NULL,
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (weapon_id, slot_id)
);

-- The stat vocabulary. `unit` is the canonical unit for the stat, used when a
-- value carries no unit of its own ("damage = 90" is 90 hp).
CREATE TABLE stat_keys (
    stat_key_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        text NOT NULL UNIQUE,
    label       text NOT NULL,
    unit        text,
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now()
);

-- One row per measurement, not per stat. A wiki value like
--   "0.67 shots/s (max charge); 3.33 shots/s (min charge)"
-- becomes two rows sharing a stat_key, separated by `condition`.
--
-- Units are split into the unit on top and the unit underneath, so nothing has
-- to parse a "/" to know what a number means. denominator_value carries the
-- magnitude underneath - 1 for a plain rate, or the window a burst spans:
--   "125 m/s"              -> 125,  meters  / seconds,  denominator_value 1
--   "1.25 shots/s"         -> 1.25, shots   / seconds,  denominator_value 1
--   "75 over 0.59 seconds" -> 75,   hp      / seconds,  denominator_value 0.59
--   "14 seconds"           -> 14,   seconds / NULL
-- A rate is therefore always value / denominator_value per unit_denominator.
--
-- value is NULL where the measurement is not numeric (shot types, "partial").
-- value_text and raw_value always keep the source strings, so anything the
-- parser misreads stays recoverable.
CREATE TABLE ability_stats (
    ability_stat_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ability_id      integer NOT NULL REFERENCES abilities(ability_id) ON DELETE CASCADE,
    stat_key_id     integer NOT NULL REFERENCES stat_keys(stat_key_id),
    value             numeric,
    unit_numerator    text,
    unit_denominator  text,
    denominator_value numeric,
    condition       text,
    value_text      text NOT NULL,
    raw_value       text NOT NULL,
    source_id       integer NOT NULL REFERENCES sources(source_id),
    cao             timestamptz NOT NULL DEFAULT now()
,
    -- The same measurement emitted twice is one fact, not two: an ability
    -- named after its weapon gets its stat block from both wiki passes, and
    -- without this the second pass doubles it. NULLS NOT DISTINCT because
    -- most of these columns are legitimately NULL and two NULLs here mean
    -- "same absence", not "different rows".
    UNIQUE NULLS NOT DISTINCT (ability_id, stat_key_id, value, unit_numerator,
        unit_denominator, denominator_value, condition, value_text)
);

CREATE TABLE weapon_stats (
    weapon_stat_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    config_id      integer NOT NULL REFERENCES weapon_configs(config_id) ON DELETE CASCADE,
    stat_key_id    integer NOT NULL REFERENCES stat_keys(stat_key_id),
    value             numeric,
    unit_numerator    text,
    unit_denominator  text,
    denominator_value numeric,
    condition      text,
    value_text     text NOT NULL,
    raw_value      text NOT NULL,
    source_id      integer NOT NULL REFERENCES sources(source_id),
    cao            timestamptz NOT NULL DEFAULT now()
,
    -- The same measurement emitted twice is one fact, not two: an ability
    -- named after its weapon gets its stat block from both wiki passes, and
    -- without this the second pass doubles it. NULLS NOT DISTINCT because
    -- most of these columns are legitimately NULL and two NULLs here mean
    -- "same absence", not "different rows".
    UNIQUE NULLS NOT DISTINCT (config_id, stat_key_id, value, unit_numerator,
        unit_denominator, denominator_value, condition, value_text)
);

CREATE INDEX ix_weapons_hero ON weapons (hero_id);
CREATE INDEX ix_weapon_configs_weapon ON weapon_configs (weapon_id);
CREATE INDEX ix_ability_stats_ability ON ability_stats (ability_id);
CREATE INDEX ix_ability_stats_key ON ability_stats (stat_key_id);
CREATE INDEX ix_weapon_stats_config ON weapon_stats (config_id);
CREATE INDEX ix_weapon_stats_key ON weapon_stats (stat_key_id);

CREATE TABLE perk_stats (
    perk_stat_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    perk_id      integer NOT NULL REFERENCES perks(perk_id) ON DELETE CASCADE,
    stat_key_id  integer NOT NULL REFERENCES stat_keys(stat_key_id),
    value             numeric,
    unit_numerator    text,
    unit_denominator  text,
    denominator_value numeric,
    condition    text,
    value_text   text NOT NULL,
    raw_value    text NOT NULL,
    source_id    integer NOT NULL REFERENCES sources(source_id),
    cao          timestamptz NOT NULL DEFAULT now()
,
    -- The same measurement emitted twice is one fact, not two: an ability
    -- named after its weapon gets its stat block from both wiki passes, and
    -- without this the second pass doubles it. NULLS NOT DISTINCT because
    -- most of these columns are legitimately NULL and two NULLs here mean
    -- "same absence", not "different rows".
    UNIQUE NULLS NOT DISTINCT (perk_id, stat_key_id, value, unit_numerator,
        unit_denominator, denominator_value, condition, value_text)
);

CREATE INDEX ix_perk_stats_perk ON perk_stats (perk_id);
CREATE INDEX ix_perk_stats_key ON perk_stats (stat_key_id);

-- How abilities and perks change other values.
--
-- Two relationships the flat stat tables cannot express:
--
--   perk_ability_effects  which ability a perk alters. perk_stats already
--                         holds the before and after values (condition
--                         'before perk' / 'with perk'); this says what they
--                         are the before and after OF.
--
--   ability_modifiers     an ability that scales someone else's numbers -
--                         Ana's Nano Boost amplifying the damage its target
--                         deals, Zenyatta's Discord Orb amplifying the damage
--                         its target takes.
--
-- Both are derived, and neither is invented. The magnitudes come from the stat
-- the wiki already publishes (damage_amp, healing_mod, ...); the direction
-- comes from its own wording ("+50% dealt", "-45% taken") and its
-- ability_keywords ("amp outgoing", "amp incoming", "target ally"). Where the
-- source settles nothing, applies_to stays NULL rather than being guessed.
--
-- The perk link is matched by name: a perk whose description names one of that
-- hero's abilities is linked to it. Perks describing general behaviour
-- ("Ignited enemies burn 1.5 seconds longer") name no ability and get no row.

CREATE TABLE perk_ability_effects (
    perk_id    integer NOT NULL REFERENCES perks(perk_id) ON DELETE CASCADE,
    ability_id integer NOT NULL REFERENCES abilities(ability_id) ON DELETE CASCADE,
    source_id  integer NOT NULL REFERENCES sources(source_id),
    cao        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (perk_id, ability_id)
);

-- affects names the quantity scaled, so a query can find every effect on
-- outgoing damage without knowing which stat it was published under.
--   damage_dealt · damage_taken · healing_received · healing_dealt · movement_speed
-- magnitude is a signed percentage: +50 amplifies, -45 reduces.
CREATE TABLE ability_modifiers (
    modifier_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ability_id  integer NOT NULL REFERENCES abilities(ability_id) ON DELETE CASCADE,
    stat_key_id integer NOT NULL REFERENCES stat_keys(stat_key_id),
    affects     text NOT NULL,
    applies_to  text,
    magnitude   numeric NOT NULL,
    unit        text NOT NULL,
    source_id   integer NOT NULL REFERENCES sources(source_id),
    cao         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ability_id, stat_key_id, affects, magnitude)
);

CREATE INDEX ix_perk_ability_effects_ability ON perk_ability_effects (ability_id);
CREATE INDEX ix_ability_modifiers_affects ON ability_modifiers (affects);

COMMIT;
