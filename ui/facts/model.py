"""The World: the whole database in memory - the heroes, the maps, the
relations between them and the names they resolve by. ui.facts.tables.load
builds one from Postgres on every request, so the UI layer always reads what
the data layer stored. A hero's kit pieces and the numbers read off their
rows are ui.facts.kit's.
"""

from collections import defaultdict

from db import KIND_ULTIMATE
from db.data.names import name_key
from ui.facts.kit import Kit

ROLES = ("tank", "damage", "support")

REMECH = ("Call Mech",)     # climbing back into the mech: an ultimate by kind, not a fight tool
SQUISHY_POOL = 250


class Hero:
    @property
    def released(self):
        return self.status == "released"

    def __init__(self, hid, name, role, subrole, health, shield, armor,
                 portrait, status="released", release_date=None):
        self.id, self.name = hid, name
        self.role, self.subrole = role, subrole
        self.status, self.release_date = status, release_date   # announced: shown, never picked
        self.health, self.shield, self.armor = health or 0, shield or 0, armor or 0
        self.portrait = portrait
        self.styles = set()
        self.abilities, self.weapons, self.perks = [], [], []
        self.modifiers = []
        self.win = self.pick = self.ban = None
        self.by_tier = {}
        self.prev_win = None
        self.map_rates = {}
        self.map_bans = {}           # map_id -> ban rate on that map, when published
        self.best_maps = []          # map ids, three at most: see best_maps()
        self.perk_effects = []       # (perk, the ability it alters)
        # What scalars.derive() reads off the kit and derive_rates() off the
        # rates, at rest: the class states its whole shape here, so a hero the
        # rows never filled reads zero rather than raising, and a reader sees
        # the fields in one place.
        self.pool = 0
        self.keywords = set()
        self.form_armor = 0.0
        self.dps = self.burst = 0.0
        self.hps = self.peak_heal = self.self_hps = self.self_heal = 0.0
        self.lifesteal = 0.0
        self.max_range = self.hitscan_range = 0.0
        self.cooldowns = []
        self.median_cooldown = None
        self.weapon_kinds = set()
        self.hitscan = self.beam = self.melee = self.melee_only = False
        self.aoe_count = self.aoe_damage = 0
        self.barrier_hp = 0.0
        self.pierces_barrier = False
        self.overhealth = 0.0
        self.antiheal = self.heal_amp = self.dmg_amp = 0.0
        self.cc_tools = []
        self.mobility_tools = []
        self.flyer = False
        self.cleanse_tools, self.invuln_tools = [], []
        self.team_cleanse_tools, self.save_tools = [], []
        self.deployables = []
        self.ult = None
        self.ult_damage_raw = self.ult_damage = 0.0
        self.ult_cost = None
        self.dmg_ult = False
        self.rank_spread = 0.0
        self.trend = None

    @property
    def ults(self) -> list[Kit]:
        """The ultimates the hero fights with: climbing back into the mech is not one."""
        return [a for a in self.abilities if a.kind == KIND_ULTIMATE and a.name not in REMECH]

    def derive_rates(self) -> None:
        """rank_spread and trend, from the rates the load read: the win rate's
        spread across the tiers, and its move since the previous capture."""
        tiers = [w for w in self.by_tier.values() if w[0] is not None]
        self.rank_spread = (
            max(t[0] for t in tiers) - min(t[0] for t in tiers) if len(tiers) >= 2 else 0.0)
        self.trend = (
            self.win - self.prev_win
            if self.win is not None and self.prev_win is not None else None)

    def cap_ult(self, cap: float) -> None:
        """ult_damage: the raw figure, capped at `cap` where the roster has a cap."""
        self.ult_damage = min(self.ult_damage_raw, cap) if cap else self.ult_damage_raw

    def map_win(self, map_id):
        rate = self.map_rates.get(map_id)
        return rate[0] if rate else None

    def map_ban(self, map_id):
        return self.map_bans.get(map_id)

    def map_pick(self, map_id):
        rate = self.map_rates.get(map_id)
        return rate[1] if rate else None


# the terrain the wiki's map articles describe, as map_terrain stores it
TERRAIN_FEATURES = ("chokes", "interiors", "high_ground", "flanks", "sightlines",
                    "open_ground", "hazards", "cover")
# the terrain each playstyle is played on (authored; cover leans to none)
TERRAIN_LEAN = {
    "brawl": ("chokes", "interiors"),
    "dive": ("high_ground", "flanks", "hazards"),
    "poke": ("sightlines", "open_ground"),
}


class Map:
    def __init__(self, mid, name, mode):
        self.id, self.name, self.mode = mid, name, mode
        self.stages = []          # names, in play order: see map_stages
        self.stage_terrain = {}   # stage -> {feature: (per thousand words, mentions)}; text only
        self.stage_z = {}         # stage -> {feature: z}: see stage_terrain
        self.terrain = {}         # feature -> mentions per thousand words; empty without text
        self.terrain_z = dict.fromkeys(TERRAIN_FEATURES, 0.0)   # see map_terrain
        self.rate_lift = {}       # style -> z: see map_styles
        self.terrain_lean = {}    # style -> z: see map_terrain
        self.styles = {}          # style -> (rate_lift + terrain_lean, None)

    @property
    def style_top(self):
        if not self.styles:
            return None
        return sorted(self.styles, key=lambda s: (-(self.styles[s][0] or 0), s))[0]

    @property
    def style_margin(self):
        scores = sorted((v[0] or 0 for v in self.styles.values()), reverse=True)
        if len(scores) >= 2:
            return round(scores[0] - scores[1], 3)
        return scores[0] if scores else 0


class World:
    def __init__(self):
        self.heroes = {}
        self.by_key = {}
        self.maps = {}
        self.maps_by_key = {}
        self.counters = set()
        self.answered_by = defaultdict(set)     # loser -> {winners}
        self.answers = defaultdict(set)         # winner -> {losers}
        self.synergies = {}                     # frozenset({a,b}) -> (score, note)
        self.partners = defaultdict(dict)       # a -> {b: (score, note)}
        self.snapshots = []
        self.newer_patches = []
        self.subrole_passives = {}              # subrole -> its passive's description
        self.role_icons = {}
        self.heal_bench = 0.0
        self.hps_bench = 0.0         # 2 x the median sustained healing across the supports
        self.ult_cap = 0.0           # the largest single figure an ultimate publishes
        self.catalog_counts = {}     # the strategies mirror: kind -> count
        self.playbook = ""           # the folder the mirror came from, when not the shipped one

    # --- lookups -------------------------------------------------------

    def hero(self, name):
        hid = self.by_key.get(name_key(name))
        return self.heroes[hid] if hid is not None else None

    def map(self, name):
        mid = self.maps_by_key.get(name_key(name))
        return self.maps[mid] if mid is not None else None

    def resolve(self, map_name, red, blue, bans=(), allow_announced=False):
        """Names -> (map or None, [Hero] red, [Hero] blue, [Hero] banned);
        unknown names raise, and so does a pick that is banned - or, unless
        `allow_announced`, a hero announced but not yet released."""
        unknown = [n for n in list(red) + list(blue) + list(bans) if self.hero(n) is None]
        if unknown:
            raise ValueError("unknown heroes: %s" % ", ".join(unknown))
        # a hero may play for either team but cannot hold two seats on one, and a
        # ban list naming the same hero twice bans one hero
        for label, names in (("red", red), ("blue", blue), ("ban", bans)):
            seen, twice = set(), []
            for n in names:
                hid = self.hero(n).id
                twice.append(n) if hid in seen else seen.add(hid)
            if twice:
                raise ValueError("%s picks the same hero twice: %s"
                                 % (label, ", ".join(sorted(set(twice)))))
        if not allow_announced:
            early = [self.hero(n) for n in list(red) + list(blue) + list(bans)
                     if not self.hero(n).released]
            if early:
                raise ValueError("announced, not yet playable: %s" % ", ".join(
                    "%s (releases %s)" % (h.name, h.release_date) if h.release_date else h.name
                    for h in early))
        m = None
        if map_name:
            m = self.map(map_name)
            if m is None:
                raise ValueError("unknown map: %s" % map_name)
        banned = [self.hero(n) for n in bans]
        banned_ids = {h.id for h in banned}
        picked = [self.hero(n) for n in list(red) + list(blue)]
        clash = [h.name for h in picked if h.id in banned_ids]
        if clash:
            raise ValueError("banned this match, cannot be picked: %s" % ", ".join(clash))
        return (m, [self.hero(n) for n in red], [self.hero(n) for n in blue], banned)

    def heroes_by_role(self):
        return sorted(self.heroes.values(),
                      key=lambda h: (ROLES.index(h.role), h.name))

    def maps_sorted(self):
        return sorted(self.maps.values(), key=lambda m: m.name)

    def synergy(self, a, b):
        return self.synergies.get(frozenset((a, b)))

    def counters_of(self, loser, winner):
        return (loser, winner) in self.counters
