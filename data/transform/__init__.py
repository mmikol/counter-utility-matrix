"""TRANSFORM: normalising and deriving values from extracted data.

    wiki/         measurements (a stat value -> value, unit, window,
                  condition), names, weapons (firing modes into weapons),
                  modifiers (buff direction and target off the keywords)
    counterpick/  matching its spellings of heroes and maps against ours

Blizzard publishes prose and no numbers, so its extracted text goes straight
to load with nothing to normalise.
"""
