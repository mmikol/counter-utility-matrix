"""The inference tests' shared fixture: a private copy of the reference
playbook, for the tests that write to one."""

import os
import shutil

import pytest

from inference import catalog
from tests.inference import FIXTURE_PLAYBOOK


@pytest.fixture()
def catalog_copy(tmp_path):
    """A private copy of the reference playbook to tune without touching the repo."""
    for name in catalog.strategy_files(FIXTURE_PLAYBOOK):
        shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    return str(tmp_path)
