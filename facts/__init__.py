"""The FACTS LAYER: everything the database knows about a board, which
the board, the inference layer, the door and the reach recorder read. It
imports only db.

    model           the World - the whole database loaded into memory, per
                    request
    tables          the load - every table read into a World, the maps'
                    styles and each hero's best maps
    scalars         a hero's numbers, derived from its kit one section at a
                    time
    kit             a kit piece's stat rows and the combat numbers read off
                    them; the one reader of the wiki's prose
    kit_format      the kit in the format in force: the wiki's 6v6 figures
                    laid over the 5v5 rows, and what moved
    counters        the mechanical counter matrix, derived at load from the
                    kit, and the counter graph the default engine reads: the
                    wiki's edges, the matrix's where the wiki has none
    records         the typed records a Hero, a Map and the World hand on
    draft           the board's vocabulary - the lobby's limits, the sides -
                    and the Draft, the board at one stage of the pick-and-ban
                    draft
    roster          every hero and map the board tools accept, as the board's
                    /api/roster and the door's roster tool list them
    team            the team metrics and the typed bag every metric section
                    comes in
    compute         the matchup, map and world metrics and registry(), which
                    gathers every metric a strategy may name - pure functions
                    over a World, shared with the inference layer's solver so
                    both compute the same numbers
    factset         the FactSet - a board's facts numbered F1.., the
                    playbook's record S1.., each fact filed under every
                    metric it states
    board_facts     generate() - every fact for a map and two teams:
                    independent facts per hero and map, joint facts per team,
                    matchup facts once both teams have picks; the meta, bans,
                    map and playbook writers
    hero_facts      a named hero's facts: its kit, rates and relations, then
                    the ones only this board has
    team_facts      a team's facts, one per team metric, and the matchup's
    matches         the owner's recorded matches: Match, one map played, and
                    load_matches, every one oldest first
"""
