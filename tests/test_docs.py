"""Every link resolves, every skill names real tools, the root overview names
what is at the root, and the sections db_docs generates match what the code
generates today. Pure, except the schema check."""

import ast
import json
import os
import re
import shutil
import subprocess

import pytest

from db import ROOT

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


# Any quoted COUNTRIX_ name, not only an os.environ.get argument: a setting read
# through a constant or a helper still spells its name as a literal somewhere
ENV_RE = re.compile(r"""["'](COUNTRIX_[A-Z_]+|DATABASE_URL)["']""")
# read where the code reads them, documented where a reader looks: the settings
# table in architecture.md, or db.md for the refresh clock it delegates
ENV_DOCS = ("architecture.md", "db.md")


def test_every_setting_the_code_reads_is_documented():
    assert ENV_RE.findall('CLI = "COUNTRIX_X"') == ["COUNTRIX_X"]   # a name kept in a constant
    names = set()
    for folder in ("db", "ui", "inference"):
        for base, _, files in os.walk(os.path.join(ROOT, folder)):
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(base, name)
                    with open(path, encoding="utf-8") as handle:
                        names |= set(ENV_RE.findall(handle.read()))
    names |= set(ENV_RE.findall(_read("orchestrator.py")))
    documented = "".join(_read("docs", doc) for doc in ENV_DOCS)
    # the two that only the tests set are the suite's own, not a setting to document
    missing = sorted(n for n in names - {"COUNTRIX_NO_DATABASE", "COUNTRIX_LOCAL_SERVER"}
                     if n not in documented)
    assert not missing, missing


def _import_time_reads(tree):
    """Line numbers of os.environ and os.getenv that run when the module is
    imported: outside a function body, or in a default or a decorator."""
    lines = []

    def visit(node, deferred):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            eager = [*getattr(node, "decorator_list", []), *node.args.defaults,
                     *(d for d in node.args.kw_defaults if d is not None)]
            for child in eager:
                visit(child, deferred)
            for child in node.body if isinstance(node.body, list) else [node.body]:
                visit(child, True)
            return
        if (not deferred and isinstance(node, ast.Attribute)
                and node.attr in ("environ", "getenv")
                and isinstance(node.value, ast.Name) and node.value.id == "os"):
            lines.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, deferred)
    visit(tree, False)
    return lines


def test_no_module_reads_the_environment_at_import():
    """A setting is read when it is used, or by main() at start, never frozen
    into a module global: a snapshot taken at import outlives a change and
    makes a test patch the attribute. It cannot see a module-level call into
    a function that reads the environment."""
    assert _import_time_reads(ast.parse("import os\nX = os.environ.get('A')\n"
                                        "def f(y=os.getenv('B')):\n"
                                        "    return os.environ['C']\n")) == [2, 3]
    paths = [os.path.join(ROOT, "orchestrator.py")]
    for folder in ("db", "ui", "inference", "scripts"):
        for base, dirs, files in os.walk(os.path.join(ROOT, folder)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            paths += [os.path.join(base, name) for name in files if name.endswith(".py")]
    frozen = []
    for path in sorted(paths):
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), path)
        frozen += ["%s:%d" % (os.path.relpath(path, ROOT), line)
                   for line in _import_time_reads(tree)]
    assert not frozen, frozen


def test_the_migrations_row_names_every_migration():
    # the migrations/ row of docs/db.md is the one inventory of the schema's
    # steps, so a new file is named there by its number
    lines = _read("docs", "db.md").splitlines()
    [row] = [line for line in lines if line.startswith("| `migrations/` |")]
    folder = os.path.join(ROOT, "db", "psql", "migrations")
    missing = sorted(name for name in os.listdir(folder)
                     if name.endswith(".sql") and "`%s`" % name[:3] not in row)
    assert not missing, missing


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
    assert set(servers) == {"countrix", "countrix-docker"}
    assert servers["countrix"]["args"] == ["-m", "db.mcp"]
    assert servers["countrix-docker"]["url"].endswith(":8020/mcp")
    docker = servers["countrix-docker"]
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
    """Coverage, not identity: a coding tool may install its own playbook
    beside ours, and a skill this repo does not own does not decide the run."""
    from db.mcp import tools
    registered = {name for name, *_ in tools.REGISTRY}
    skills = _skills()
    assert set(MUST_NAME) <= set(skills)
    for name in MUST_NAME:
        text = skills[name]
        head = text.split("---")[1]
        assert re.search(r"^name: %s$" % name, head, re.M), name
        assert re.search(r"^description: \S", head, re.M), name
        named = set(re.findall(r"`([a-z_]+)`", text)) & registered
        assert MUST_NAME[name] <= named, (name, MUST_NAME[name] - named)


@needs_skills
def test_the_skills_document_covers_every_skill(copy_of):
    doc = _read("docs", "skills.md")
    for name in MUST_NAME:
        assert "## `/%s`" % name in doc, name


def test_every_shipped_strategy_is_in_the_playbook_sources():
    """inference/README.md is the record the playbook is rebuilt from, so it
    holds more ids than the folder does. The other direction has to hold: a
    file in inference/strategies/ that the record does not cite came from
    nowhere."""
    from inference import catalog
    record = _read("inference", "README.md")
    cited = set(re.findall(r"^- `([a-z0-9-]+)`", record, re.M))
    shipped = {name[:-3] for name in catalog.strategy_files(catalog.SHIPPED_DIR)}
    assert shipped and shipped <= cited, sorted(shipped - cited)


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


def test_a_tables_prose_is_the_comment_block_directly_above_it():
    from db.psql import schema
    text = "\n".join([
        "-- THE FILE: a header that is no table's.",
        "BEGIN;",
        "",
        "-- One row per hero.",
        "--",
        "-- The roster, from Blizzard.",
        "CREATE TABLE heroes (",
        "    hero_id serial PRIMARY KEY",
        ");",
        "",
        "-- Not this one: a blank line follows it.",
        "",
        "CREATE TABLE maps (map_id serial PRIMARY KEY);",
        "-- Nor this one:",
        "    -- an indented line ends the block.",
        "CREATE TABLE modes (mode_id serial PRIMARY KEY);",
        "-- Two lines,",
        "-- one sentence.",
        "CREATE TABLE stages (stage_id serial PRIMARY KEY);",
        "COMMIT;",
    ])
    assert schema.table_prose(text) == {
        "heroes": "One row per hero. The roster, from Blizzard.",   # the bare -- is dropped
        "maps": "", "modes": "",
        "stages": "Two lines, one sentence.",
    }


def test_embed_replaces_only_the_marked_section(tmp_path):
    from db import embed
    path = tmp_path / "doc.md"
    path.write_text("# T\n\nkeep\n\n<!-- generated:x -->\nold\n<!-- /generated:x -->"
                    "\n\nalso keep\n")
    embed(str(path), "x", "new\nlines")
    assert path.read_text() == ("# T\n\nkeep\n\n<!-- generated:x -->\nnew\nlines\n"
                                "<!-- /generated:x -->\n\nalso keep\n")
    with pytest.raises(ValueError, match="no y markers"):
        embed(str(path), "y", "z")
