"""The UI LAYER's facts: everything the database knows about a board.

    model       the World - the whole database loaded into memory, per request
    tables      the load - every table read into a World, the maps' styles
                and each hero's best maps
    kit         a kit piece's stat rows and the combat numbers read off them;
                the one reader of the wiki's prose
    records     the typed records a Hero, a Map and the World hand on
    compute     the metrics - pure functions over a World, shared with the
                inference layer's solver so both compute the same numbers
    engine      the FactSet - every fact, numbered F1.., for a map and two
                teams: independent facts per hero and map, joint facts per
                team, matchup facts once both teams have picks
"""
