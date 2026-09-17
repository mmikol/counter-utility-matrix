"""The inference layer's tests, and the reference playbook they prove the solver against."""

import os

# the former shipped playbook - every kind and every form - kept as the reference the
# solver's behaviours are proven against; the live playbook is the user's own
FIXTURE_PLAYBOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "fixtures", "playbook")
