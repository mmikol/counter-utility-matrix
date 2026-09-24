"""The inference layer's tests, and the reference playbook they prove the solver against."""

import os

from db import ROOT

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
# the former shipped playbook - every kind and every form - kept as the reference the
# solver's behaviours are proven against; the live playbook is the user's own
FIXTURE_PLAYBOOK = os.path.join(FIXTURES, "playbook")
