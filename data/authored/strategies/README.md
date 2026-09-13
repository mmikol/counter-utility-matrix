# strategies - the operator's own notes

Drop markdown files here (`anti-dive.md`, `our-scrim-team.md`, ...). Each
file becomes one row of the `strategies` table when `load_playbook` runs -
title from the filename, body verbatim - and every note appears on the board
and in the `facts` tool as a citable `strategy.note` entry (S-numbered,
on the strategy side below the facts), which the
`/comp` skill reads alongside the heuristics.

No structure is imposed: a paragraph of prose, a list of rules, a note
about a team's tendencies. This README is skipped by the loader. An empty
directory is a valid state.
