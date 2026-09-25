"""The counters a hero article's Strategy section states, and which way each
runs (db/data/wiki/strategy_sections.py), on fixture wikitext: each cue's
reading around the article's hero and the foes a sentence names, the
clauses, negations, hedges, comparisons and allies it reads nothing from,
and the pairs it drops. No database, no network."""

from db.data.wiki import strategy_sections as ss

ROSTER = [
    "Ana", "Cassidy", "Doomfist", "Genji", "Juno", "Kiriko", "Lúcio", "Mei", "Mercy", "Pharah",
    "Reaper", "Reinhardt", "Roadhog", "Sigma", "Sombra", "Tracer", "Widowmaker", "Winston",
    "Zenyatta"]
ALIASES = {"Lúcio": ["Lúcio", "Lucio"]}


def _side(name, pronoun="she", kit=()):
    return ss.Side(name=name, names=tuple(ALIASES.get(name, [name])), pronoun=pronoun,
                   kit=tuple(kit))


def _article(*sentences):
    """An article whose Strategy section bullets each sentence; one written
    as a bullet already keeps its own depth."""
    return "{{Infobox character}}\n==Strategy==\n%s\n==Trivia==\nWinston counters Tracer.\n" % (
        "\n".join(s if s.startswith("*") else "* " + s for s in sentences))


def _read(side, *sentences):
    reading = ss.read_article(_article(*sentences), side, ROSTER, ALIASES)
    return sorted((c.winner, c.loser) for c in reading.claims), reading.ambiguous


def test_the_hero_that_counters_a_list_answers_every_hero_in_it():
    """An act cue with the hero before it and no object near: the first list
    after it, past a relative clause that names the hero again."""
    claims, _ = _read(_side("Pharah"), "Pharah is a good counter to enemies with short-ranged"
                      " guns that can't hit her in the air, such as Reaper, Mei, and Lúcio.")
    assert claims == [("Pharah", "Lúcio"), ("Pharah", "Mei"), ("Pharah", "Reaper")]


def test_an_ability_of_the_hero_acts_for_it_and_a_mirror_is_no_side():
    """Biotic Grenade is Ana's: it counters Roadhog and Zenyatta; an
    opposing Ana is neither Ana nor a foe."""
    claims, _ = _read(_side("Ana", kit=("Biotic Grenade",)),
                      "Biotic Grenade is a strong counter to all healing effects, such as"
                      " Roadhog's Take a Breather, Zenyatta's Transcendence, or even an opposing"
                      " Ana's Biotic Grenade.")
    assert claims == [("Ana", "Roadhog"), ("Ana", "Zenyatta")]


def test_the_hero_as_the_object_is_answered_by_the_foes_before():
    """Reinhardt counter-charges and stuns Doomfist in Doomfist's article;
    in the next clause Mei stops his engagements - "his" is Doomfist's."""
    claims, _ = _read(_side("Doomfist", pronoun="he"),
                      "Reinhardt possesses the means to counter-charge and stun Doomfist while Mei"
                      " can stop his engagements.")
    assert claims == [("Mei", "Doomfist"), ("Reinhardt", "Doomfist")]


def test_a_vulnerable_hero_is_answered_by_the_list_after_it():
    claims, _ = _read(_side("Pharah"), "This can keep her away from threats on the ground, but"
                      " will leave her vulnerable to enemies with hitscan attacks, such as Cassidy"
                      " and Widowmaker.")
    assert claims == [("Cassidy", "Pharah"), ("Widowmaker", "Pharah")]


def test_foes_that_are_vulnerable_are_answered_by_the_hero():
    claims, _ = _read(_side("Genji", pronoun="he"), "Targets like Mercy and Zenyatta are"
                      " vulnerable to well-executed attacks.",
                      "Only engage if the enemy you're fighting is vulnerable (such as a lone"
                      " Widowmaker).")
    assert claims == [("Genji", "Mercy"), ("Genji", "Widowmaker"), ("Genji", "Zenyatta")]


def test_the_heros_counters_and_threats_answer_it():
    claims, _ = _read(_side("Doomfist", pronoun="he"),
                      "Featuring heroes like Roadhog, Sombra & Zenyatta or Ana, all of the heroes"
                      " involved are considered to be Doomfist's hardest counters.",
                      "Characters like Tracer & Cassidy are exceptionally troublesome when"
                      " pocketed.")
    assert claims == [(hero, "Doomfist") for hero in
                      ("Ana", "Cassidy", "Roadhog", "Sombra", "Tracer", "Zenyatta")]


def test_an_easy_kill_with_foes_names_them_its_answers():
    claims, _ = _read(_side("Sigma", pronoun="he"),
                      "She can also be very easy to burst down with heroes like Widowmaker and"
                      " Roadhog.")
    assert claims == []                    # she is not Sigma: nobody's side, nothing read
    claims, _ = _read(_side("Mercy"), "She can also be very easy to burst down with heroes like"
                      " Widowmaker and Roadhog.")
    assert claims == [("Roadhog", "Mercy"), ("Widowmaker", "Mercy")]


def test_the_foe_to_avoid_answers_the_hero():
    claims, _ = _read(_side("Mercy"), "Try to avoid Sombra, as she can hack you.")
    assert claims == [("Sombra", "Mercy")]


def test_a_negation_a_hedge_a_comparison_and_allies_read_nothing():
    """Each sentence names foes beside a cue, and each reads no edge: the pairs
    named beside a cue are ambiguous, the allies' are not counters at all."""
    side = _side("Roadhog", pronoun="he")
    claims, ambiguous = _read(
        side,
        "It is safe against low-damage targets like Winston or Lúcio, as they don't have the"
        " burst damage needed to kill you.",
        "Flying heroes like Pharah may seem like simple counters to Roadhog.",
        "Like Widowmaker, Roadhog can pick off a lone target.",
        "Tidal Blast synergies:",
        "** Sigma and Tracer struggle to close the distance.",
        "Allies like Reaper benefit, as it stops them from being interrupted.")
    assert claims == []
    assert ambiguous == [("Roadhog", "Lúcio"), ("Roadhog", "Pharah"), ("Roadhog", "Widowmaker"),
                         ("Roadhog", "Winston")]


def test_an_enemy_is_read_beside_allies():
    """A sentence that speaks of a friendly one still reads a foe it calls an
    enemy."""
    claims, _ = _read(_side("Ana", kit=("Biotic Grenade",)), "Biotic Grenade can both counter an"
                      " enemy Zenyatta's Transcendence, and synergize with a friendly one.")
    assert claims == [("Ana", "Zenyatta")]


def test_a_section_that_reads_a_pair_both_ways_drops_it():
    claims, ambiguous = _read(_side("Mei"), "Mei is a good counter to Genji.",
                              "Genji is a threat to Mei.")
    assert (claims, ambiguous) == ([], [("Mei", "Genji")])


def test_only_the_strategy_section_is_read():
    """The Trivia section's sentence is no Strategy text: nothing is read."""
    reading = ss.read_article(_article("Nothing here names a foe."), _side("Winston", "he"),
                              ROSTER, ALIASES)
    assert reading == ss.Reading(claims=[], ambiguous=[])
    assert ss.sentences("No strategy section at all.") == []


def test_two_articles_that_disagree_drop_the_pair_and_the_rest_are_kept():
    """Ana's section says Ana answers Roadhog and Roadhog's the reverse: the
    pair is dropped; a pair one article leaves ambiguous and another reads
    is kept."""
    ana = ss.Reading(claims=[ss.Claim("Ana", "Roadhog", "a"), ss.Claim("Ana", "Mercy", "b")],
                     ambiguous=[("Ana", "Tracer")])
    hog = ss.Reading(claims=[ss.Claim("Roadhog", "Ana", "c")], ambiguous=[])
    tracer = ss.Reading(claims=[ss.Claim("Ana", "Tracer", "d")], ambiguous=[])
    edges, dropped = ss.combine({"Ana": ana, "Roadhog": hog, "Tracer": tracer})
    assert [(c.winner, c.loser, c.sentence) for c in edges] == [
        ("Ana", "Mercy", "b"), ("Ana", "Tracer", "d")]
    assert dropped == [("Ana", "Roadhog")]
