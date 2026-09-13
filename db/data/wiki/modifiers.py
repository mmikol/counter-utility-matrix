"""Working out what an ability or perk changes, from the wiki's wording.

The wiki publishes the size of a buff as an ordinary stat (damage_amp = "+50%
dealt") but never says, in a field, what it scales or who it lands on. Both are
recoverable from wording the source does supply: the qualifier in the value
("dealt", "taken", "received") and the ability's own keywords ("amp outgoing",
"amp incoming", "target ally").

Nothing here guesses. Where the source settles nothing, the answer is None.
"""

# Stats that describe a change to someone's numbers rather than a value.
MODIFIER_STATS = {
    "damage_amp": "damage",
    "damage_red": "damage",
    "healing_mod": "healing",
    "mspeed_buff": "movement_speed",
    "mspeed_pen": "movement_speed",
    "mspeed_slow": "movement_speed",
}


def affected_quantity(stat_code, value_text, keywords):
    """What the modifier scales, or None if the source does not say."""
    family = MODIFIER_STATS.get(stat_code)
    if family is None:
        return None
    if family == "movement_speed":
        return "movement_speed"

    text = (value_text or "").lower()
    words = (keywords or "").lower()

    if family == "healing":
        if "received" in text:
            return "healing_received"
        if "dealt" in text:
            return "healing_dealt"
        return None

    # damage_red always reduces what its subject takes.
    if stat_code == "damage_red" or "taken" in text or "amp incoming" in words:
        return "damage_taken"
    if "dealt" in text or "amp outgoing" in words:
        return "damage_dealt"
    return None


def applies_to(stat_code, value_text, keywords):
    """Who the modifier lands on: self, ally, enemy, or None when unclear."""
    words = (keywords or "").lower()
    text = (value_text or "").lower()

    if "target ally" in words:
        return "ally"
    # Amplifying the damage a subject *takes* is something done to an enemy.
    if "amp incoming" in words:
        return "enemy"
    if stat_code == "damage_amp" and "taken" in text:
        return "enemy"
    # A pure damage reduction with no target named is worn by its own caster.
    if stat_code == "damage_red" and "target" not in words:
        return "self"
    return None
