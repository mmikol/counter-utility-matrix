"""The recorder: an offline run that writes the tests' recorded fixture. It runs
from the repo root as a module, `.venv/bin/python -m scripts.<name>`, so it
imports this package and never an installed `scripts`, and it records the
digest of the playbook in force beside its boards.

    reach         a board per released hero that seats it
                  (tests/fixtures/reach.json)
"""
