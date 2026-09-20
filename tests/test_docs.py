"""Every link resolves, every skill names real tools, the root overview names
what is at the root, and the sections db_docs generates match what the code
generates today. Pure, except the schema check."""

import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
SKILLS = os.path.join(ROOT, ".claude", "skills")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# the git index and the .claude folder are not in the Docker image; the two
# tests that read them skip there, not fail
needs_git = pytest.mark.skipif(
    not os.path.isdir(os.path.join(ROOT, ".git")) or not shutil.which("git"),
                               reason="needs the git checkout")
needs_skills = pytest.mark.skipif(not os.path.isdir(SKILLS),
                                  reason="the skills are not in the image")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def _section(text, name):
    start, end = "<!-- generated:%s -->" % name, "<!-- /generated:%s -->" % name
    return text[text.index(start) + len(start):text.index(end)].strip()


@pytest.fixture()
def copy_of(tmp_path):
    def make(doc):
        target = tmp_path / os.path.basename(doc)
        shutil.copy(os.path.join(ROOT, doc), target)
        return str(target)
    return make


# --- links and inventories -------------------------------------------------------------------

def test_every_relative_link_in_the_docs_resolves():
    broken = []
    for doc in ["README.md", *sorted("docs/" + n for n in os.listdir(DOCS) if n.endswith(".md"))]:
        base = os.path.dirname(os.path.join(ROOT, doc))
        for target in LINK_RE.findall(_read(doc)):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path = target.split("#")[0]
            if path and not os.path.exists(os.path.join(base, path)):
                broken.append("%s -> %s" % (doc, target))
    assert not broken, broken


@needs_git
def test_the_overview_names_everything_at_the_root():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True).stdout.split()
    entries = {p.split("/")[0] for p in tracked} - {"README.md", "docs"}
    overview = _read("docs", "architecture.md")
    missing = sorted(e for e in entries if e not in overview)
    assert not missing, missing


def test_mcp_json_registers_the_two_servers():
    servers = json.loads(_read(".mcp.json"))["mcpServers"]
    assert set(servers) == {"counter-utility-matrix", "counter-utility-matrix-docker"}
    assert servers["counter-utility-matrix"]["args"] == ["-m", "db.mcp"]
    assert servers["counter-utility-matrix-docker"]["url"].endswith(":8020/mcp")
    docker = servers["counter-utility-matrix-docker"]
    assert docker["headers"]["Authorization"].startswith("Bearer ${")


# --- the skills ---------------------------------------------------------------------------------

MUST_NAME = {   # a skill is a playbook over these tools; if a tool is renamed, so is the skill
    "up": {"sync_all"},
    "comp": {"infer", "facts", "board"},
    "tune": {"tune", "tuning_log", "strategies"},
    "strategy": {"metrics", "strategies", "add_strategy", "infer_strategy", "board", "db_docs"},
    "refresh": {"db_status", "sync_all", "pull_seasons", "pull_rates", "pull_synergies",
                "pull_counters", "infer_strategy", "db_docs", "export_csv", "load_authored"},
    "maintain": {"db_docs", "db_status", "strategies"},
    "patches": {"pull_patches", "pull_rates", "pull_kits", "pull_heroes", "db_docs", "export_csv"},
    "heroes": {"roster", "pull_heroes", "pull_kits", "pull_synergies", "pull_counters"},
    "maps": {"roster", "pull_maps", "pull_rates", "pull_playstyles", "facts"},
}


def _skills():
    return {name: _read(".claude", "skills", name, "SKILL.md")
            for name in sorted(os.listdir(SKILLS))
            if os.path.isfile(os.path.join(SKILLS, name, "SKILL.md"))}


@needs_skills
def test_every_skill_has_frontmatter_and_names_its_tools():
    from db.mcp import tools
    registered = {name for name, *_ in tools.REGISTRY}
    skills = _skills()
    assert set(skills) == set(MUST_NAME)
    for name, text in skills.items():
        head = text.split("---")[1]
        assert re.search(r"^name: %s$" % name, head, re.M), name
        assert re.search(r"^description: \S", head, re.M), name
        named = set(re.findall(r"`([a-z_]+)`", text)) & registered
        assert MUST_NAME[name] <= named, (name, MUST_NAME[name] - named)


@needs_skills
def test_the_skills_document_covers_every_skill(copy_of):
    doc = _read("docs", "skills.md")
    for name in _skills():
        assert "## `/%s`" % name in doc, name


def test_the_tool_reference_is_current(copy_of):
    from db.mcp import tools
    committed = _read("docs", "mcp.md")
    listed = set(re.findall(r"^\| `([a-z_]+)` \|", _section(committed, "tools"), re.M))
    assert listed == {name for name, *_ in tools.REGISTRY}
    fresh = copy_of("docs/mcp.md")
    tools.write_tool_docs(fresh)
    with open(fresh, encoding="utf-8") as handle:
        assert _section(handle.read(), "tools") == _section(committed, "tools"), \
            "docs/mcp.md is behind the tools: run `python -m db.mcp call db_docs`"


# --- the generated sections ------------------------------------------------------------------

def test_the_catalog_document_matches_the_strategy_files(copy_of):
    from inference import catalog
    committed = _read("docs", "inference.md")
    fresh = copy_of("docs/inference.md")
    catalog.write_docs(catalog.load(), fresh)
    with open(fresh, encoding="utf-8") as handle:
        assert _section(handle.read(), "catalog") == _section(committed, "catalog"), \
            "docs/inference.md is behind inference/strategies/: run `python -m db.mcp call db_docs`"


@pytest.mark.invariant
def test_the_schema_sections_match_the_live_database(db, copy_of):
    from db.psql import schema
    committed = _read("docs", "db.md")
    fresh = copy_of("docs/db.md")
    schema.generate_docs(db, fresh)
    with open(fresh, encoding="utf-8") as handle:
        text = handle.read()
    assert _section(text, "erd") == _section(committed, "erd"), \
        "docs/db.md's ER diagrams are behind the schema: run `python -m db.mcp call db_docs`"
    assert _section(text, "dictionary") == _section(committed, "dictionary"), \
        "docs/db.md's data dictionary is behind the database: run `python -m db.mcp call db_docs`"


def test_embed_replaces_only_the_marked_section(tmp_path):
    from db.psql import schema
    path = tmp_path / "doc.md"
    path.write_text("# T\n\nkeep\n\n<!-- generated:x -->\nold\n<!-- /generated:x -->"
                    "\n\nalso keep\n")
    schema.embed(str(path), "x", "new\nlines")
    assert path.read_text() == ("# T\n\nkeep\n\n<!-- generated:x -->\nnew\nlines\n"
                                "<!-- /generated:x -->\n\nalso keep\n")
    with pytest.raises(schema.SchemaError, match="no y markers"):
        schema.embed(str(path), "y", "z")
