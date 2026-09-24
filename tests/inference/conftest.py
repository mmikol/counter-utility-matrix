"""The inference tests' shared fixtures: a private copy of the reference
playbook, for the tests that write to one; a two-file scratch playbook that
scores every seat of a board on the synthetic World; and the Harbor Gate
board the engine and plan tests read."""

import os
import shutil

import pytest

from facts.draft import Draft
from inference import catalog
from tests.inference import FIXTURE_PLAYBOOK


@pytest.fixture()
def catalog_copy(tmp_path):
    """A private copy of the reference playbook to tune without touching the repo."""
    for name in catalog.strategy_files(FIXTURE_PLAYBOOK):
        shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    return str(tmp_path)


@pytest.fixture()
def scratch_playbook(tmp_path):
    """The reference playbook's two-tank limit and its one heuristic on
    team.win_mean, loaded: enough for every seat of a board to score."""
    for name in ("open-queue-tanks.md", "meta-strength.md"):
        shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    return catalog.load(str(tmp_path))


@pytest.fixture()
def harbor_gate_board(synthetic_world):
    """The board the tests read most - Harbor Gate, Mortar and Gale revealed, Balm
    and Anvil locked, the reference playbook - solved on the synthetic World the
    test is given (a caller's catalog keeps the solve in one process)."""
    from inference import engine
    return engine.board(synthetic_world,
                        Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm", "Anvil")),
                        catalog=catalog.load(FIXTURE_PLAYBOOK))
