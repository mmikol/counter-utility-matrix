"""The validation report page and its command line, over no database: the
page draws a chart per question and a table under each, says it is for
personal use and labels what reads the rates, escapes what the owner
typed, and the command line prints the text, writes the page and the JSON
beside it, and answers a refusal with exit status 2."""

import contextlib
import json
import re

import pytest

from inference import catalog, validate
from tests import matches
from tests.inference import FIXTURE_PLAYBOOK
from ui import validation


@pytest.fixture(scope="module")
def report():
    from tests import synthetic
    world = synthetic.world()
    rows = matches.rows(world, 240, matches.score, seed="page")
    rows[0] = rows[0]._replace(match=rows[0].match._replace(
        note="<script>alert(1)</script>", result=validate.DRAW))
    kin_ids = ("coverage", "exposure")
    rows = [r._replace(blue_terms={"coverage": r.blue_score}, red_terms={"coverage": r.red_score})
            for r in rows]
    playbook = [s for s in catalog.load(FIXTURE_PLAYBOOK) if s.id in kin_ids]
    return validate.assess(validate.Rescoring(rows, [validate.Refused(999, "unknown heroes")]),
                           matches.judged(rows, playbook))


def test_the_page_draws_every_chart_with_a_table_beside_it(report):
    page = validation.page(report)
    assert page.count("<svg") == 7    # 2 splits x (models, ablations), calibration, score, heroes
    for heading in ("The data guard", "The models", "The calibration",
                    "The playbook score and the results", "The heroes", "The digests",
                    "The maps", "The refused maps"):
        assert "<h2>%s</h2>" % heading in page, heading
    assert page.count("<table>") >= 6
    assert 'data-tip="' in page and 'tabindex="0"' in page
    assert "prefers-color-scheme: dark" in page and "http" not in page.split("<main>")[1]


def test_the_page_is_for_personal_use_and_labels_what_reads_the_rates(report):
    page = validation.page(report)
    assert "licensed for personal use" in page and "never published" in page
    assert "rate-derived" in page and "map win diff (rates)" in page


def test_the_page_escapes_what_the_owner_typed(report):
    page = validation.page(report)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert page.count("<script>") == 1                        # the page's own tooltip script


def test_a_page_with_nothing_judged_draws_no_chart():
    empty = validate.assess(validate.Rescoring([], []), matches.judged([]))
    page = validation.page(empty)
    assert "<svg" not in page and "No recorded map was played under this playbook" in page
    unpinned = validate.assess(validate.Rescoring([], []), matches.judged([], pinned=False))
    assert "No decided map to judge." in validation.page(unpinned)


def test_the_scale_ticks_on_round_values_and_keeps_zero_in_view():
    x = validation.scale([0.013, 0.021], 0, 100)
    assert x.low == 0.0 and x.ticks[-1] >= 0.021
    assert all(abs(t * 1000 - round(t * 1000)) < 1e-9 for t in x.ticks)
    assert x.at(x.low) == 0 and x.at(x.high) == 100
    assert validation.scale([], 0, 10).ticks[0] == -1.0          # no values: a unit either way


def test_the_command_line_prints_the_text_and_writes_the_page_and_its_json(
        report, tmp_path, monkeypatch, synthetic_world):
    digest = catalog.playbook_digest(FIXTURE_PLAYBOOK)
    recorded = [r.match for r in matches.rows(synthetic_world, 4, matches.noise, seed="cli",
                                             digest=digest, per_session=2)]
    monkeypatch.setattr(validation.psql, "default_dsn", lambda: "postgresql://nowhere")
    monkeypatch.setattr(validation.psycopg, "connect", lambda dsn: contextlib.nullcontext("cx"))
    monkeypatch.setattr(validation.tables, "load", lambda cx: synthetic_world)
    monkeypatch.setattr(validation, "load_matches", lambda cx: recorded)
    printed = []
    out = tmp_path / "report.html"
    args = validation.command_line(["--playbook", "tests/fixtures/playbook", "--out", str(out)])
    judged = validation.run(args, out=printed.append)
    assert judged["counts"]["judged"] == 4
    assert printed[0].startswith("validation of tests/fixtures/playbook")
    assert printed[-1].startswith("the report: ") and printed[-1].endswith("report.html")
    assert re.search(r"<title>Playbook validation</title>", out.read_text(encoding="utf-8"))
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["counts"] == \
        judged["counts"]


def test_the_command_line_answers_a_refusal_with_status_2(capsys):
    assert validation.main(["--playbook", "..", "--out", "/dev/null"]) == 2
    assert "inside the repo" in capsys.readouterr().err
    assert validation.main(["--playbook", "docs", "--out", "/dev/null"]) == 2
