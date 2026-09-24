"""The recorders: offline runs that write the tests' proven fixtures. Each runs
from the repo root as a module, `.venv/bin/python -m scripts.<name>`, so it
imports this package and never an installed `scripts`, and each records the
digest of the playbook in force beside its boards.

    optimal       the proven maxima: the brute force's exact boards, read from
                  its .jsonl output (tests/fixtures/optimal.json)
    reach         a board per released hero that seats it
                  (tests/fixtures/reach.json)
"""
