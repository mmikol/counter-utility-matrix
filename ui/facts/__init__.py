"""The UI LAYER's facts: everything the database knows about a board.

    model    the World - the whole database loaded into memory, per request
    compute  the metrics - pure functions over a World, shared with the
             inference layer's solver so both compute the same numbers
    engine   the FactSet - every fact, numbered F1.., for a map and two
             teams: independent facts per hero and map, joint facts per
             team, matchup facts once both teams have picks
"""
