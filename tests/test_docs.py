"""Every link resolves, every skill names real tools and only strategies the
playbook holds, the root overview and every package map name what they hold,
only the door calls the playbook's writers, each layer imports only the
layers below it, every shallow indent sits on a four-column stop, every type
alias is a type statement, and the sections db_docs generates match what the
code generates today. Pure, except the schema check."""

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

# the git index and the .claude folder are not in the Docker image; the
# tests that read them skip there, not fail. A worktree's .git is a file.
needs_git = pytest.mark.skipif(
    not os.path.exists(os.path.join(ROOT, ".git")) or not shutil.which("git"),
    reason="needs the git checkout")
needs_skills = pytest.mark.skipif(not os.path.isdir(SKILLS),
                                  reason="the skills are not in the image")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def _section(text, name):
    start, end = "<!-- generated:%s -->" % name, "<!-- /generated:%s -->" % name
    return text[text.index(start) + len(start):text.index(end)].strip()


def _python_files(*folders):
    """Every .py file under the folders, and orchestrator.py, sorted."""
    paths = [os.path.join(ROOT, "orchestrator.py")]
    for folder in folders:
        for base, dirs, files in os.walk(os.path.join(ROOT, folder)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            paths += [os.path.join(base, name) for name in files if name.endswith(".py")]
    return sorted(paths)


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
    for path in _python_files("db", "facts", "inference", "door", "ui"):
        with open(path, encoding="utf-8") as handle:
            names |= set(ENV_RE.findall(handle.read()))
    documented = "".join(_read("docs", doc) for doc in ENV_DOCS)
    # the two that only the tests set are the suite's own, not a setting to document
    missing = sorted(n for n in names - {"COUNTRIX_NO_DATABASE", "COUNTRIX_LOCAL_SERVER"}
                     if n not in documented)
    assert not missing, missing


# a call that writes the playbook's files or reloads the strategies table
WRITER_RE = re.compile(r"\b(?:catalog|catalog_module)\.mirror\(|\btune\.(?:tune|add|complete)\("
                       r"|\bderive\.derive\(")


def test_only_the_door_calls_the_playbook_writers():
    """docs/architecture.md's rule: the door gates every write. The code that
    writes the playbook and its table lives in inference/ (catalog.mirror,
    tune.tune, tune.add, tune.complete, and derive.derive over them), and only
    a door tool calls it - or inference/derive.py, inside a run the door
    started. The board stores a weight through ctx.call, not tune."""
    assert WRITER_RE.search("        catalog.mirror(cx, cat)")
    assert not WRITER_RE.search('tool_context().call("tune", **arguments)')
    outside = []
    for path in _python_files("db", "facts", "inference", "door", "ui", "scripts"):
        relative = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as handle:
            calls = WRITER_RE.search(handle.read())
        if calls and not relative.startswith("door/mcp/") and relative != "inference/derive.py":
            outside.append(relative)
    assert not outside, outside


# the layers, bottom up: each imports only the ones before it
LAYERS = ("db", "facts", "inference", "door")
FIRST_PARTY = {*LAYERS, "ui", "scripts", "tests", "orchestrator"}


def _first_party_imports(tree):
    """The first-party packages a module imports, deferred imports included:
    the first dotted part of every import and of every absolute from-import."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names & FIRST_PARTY


def test_each_layer_imports_only_the_layers_below_it():
    """docs/architecture.md's layering: db <- facts <- inference <- door, each
    importing only the layers below it, a deferred import as much as one at
    the top. ui/, scripts/ and orchestrator.py stand over them and may import
    any layer."""
    snippet = "import db.psql\nfrom ui.board import x\ndef f():\n    from door import refresh\n"
    assert _first_party_imports(ast.parse(snippet)) == {"db", "ui", "door"}
    upward = []
    for rank, package in enumerate(LAYERS):
        below = set(LAYERS[:rank + 1])
        for base, dirs, files in os.walk(os.path.join(ROOT, package)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in sorted(n for n in files if n.endswith(".py")):
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), path)
                upward += ["%s: %s" % (os.path.relpath(path, ROOT), above)
                           for above in sorted(_first_party_imports(tree) - below)]
    assert not upward, upward


def test_every_shallow_indent_sits_on_a_four_column_stop():
    """desloppify reads a file's indent unit as the GCD of its indents of 1 to
    16 columns and counts nesting in that unit: one line off a multiple of 4
    makes the unit 1 and every column a level. Docstrings and strings count."""
    off = []
    for path in _python_files("db", "facts", "inference", "door", "ui", "tests", "scripts"):
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                text = line.lstrip()
                indent = len(line) - len(text)
                if text and not text.startswith("#") and 0 < indent <= 16 and indent % 4:
                    off.append("%s:%d" % (os.path.relpath(path, ROOT), number))
    assert not off, off


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
    frozen = []
    for path in _python_files("db", "facts", "inference", "door", "ui", "scripts"):
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), path)
        frozen += ["%s:%d" % (os.path.relpath(path, ROOT), line)
                   for line in _import_time_reads(tree)]
    assert not frozen, frozen


def _bare_aliases(tree):
    """Line numbers of the module-level assignments that read as a type
    alias: one CamelCase name (an UPPER constant is not one) bound to a
    subscript or a union."""
    return [node.lineno for node in tree.body
            if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and re.match(r"[A-Z][a-z]\w*", node.targets[0].id)
            and (isinstance(node.value, ast.Subscript)
                 or (isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.BitOr)))]


def test_every_type_alias_is_a_type_statement():
    """An alias is a PEP 695 type statement: a bare assignment is another
    runtime object under the same name, and two spellings leave the next
    alias without a rule to follow."""
    assert _bare_aliases(ast.parse("Pairs = dict[int, str]\nSeat = int | None\n"
                                   "SIDES = ('a', 'b')\nMAX_BANS = 5\n"
                                   "type Query = int\n")) == [1, 2]
    bare = []
    for path in _python_files("db", "facts", "inference", "door", "ui", "scripts"):
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), path)
        bare += ["%s:%d" % (os.path.relpath(path, ROOT), line) for line in _bare_aliases(tree)]
    assert not bare, bare


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


def _maps(doc, entry):
    """Whether a package docstring has a map line for the entry: indented,
    the name (a module without .py, a folder with or without its slash),
    then the column gap or the line's end. A word that opens a wrapped line
    of prose is followed by one space, so it is not a map line."""
    stem = entry[:-3] if entry.endswith(".py") else entry
    return re.search(r"^ {2,}%s(?:\.py)?/?(?: {2,}|$)" % re.escape(stem), doc, re.M) is not None


@needs_git
def test_every_package_map_names_what_the_package_holds():
    """A package's __init__ docstring maps every tracked module, folder and
    file in it, the way the overview maps the root."""
    assert _maps("    board.py    the server\n    facts/      the World", "facts")
    assert not _maps("    board.py    the board's endpoints over the\n"
                     "                facts and the inference layer", "facts")
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True).stdout.split()
    packages = sorted({os.path.dirname(p) for p in tracked
                       if os.path.basename(p) == "__init__.py" and not p.startswith("tests/")})
    assert "db/data/wiki" in packages
    missing = []
    for package in packages:
        entries = {p[len(package) + 1:].split("/")[0] for p in tracked
                   if p.startswith(package + "/")} - {"__init__.py"}
        tree = ast.parse(_read(package, "__init__.py"))
        doc = ast.get_docstring(tree, clean=False) or ""
        missing += ["%s/%s" % (package, e) for e in sorted(entries) if not _maps(doc, e)]
    assert not missing, missing


def test_mcp_json_registers_the_two_servers():
    servers = json.loads(_read(".mcp.json"))["mcpServers"]
    assert set(servers) == {"countrix", "countrix-docker"}
    assert servers["countrix"]["args"] == ["-m", "door.mcp"]
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
    "maps": {"roster", "pull_maps", "pull_terrain", "pull_rates", "pull_playstyles", "facts"},
}


def _skills():
    return {name: _read(".claude", "skills", name, "SKILL.md")
            for name in sorted(os.listdir(SKILLS))
            if os.path.isfile(os.path.join(SKILLS, name, "SKILL.md"))}


@needs_skills
def test_every_skill_has_frontmatter_and_names_its_tools():
    """Coverage, not identity: a coding tool may install its own playbook
    beside ours, and a skill this repo does not own does not decide the run."""
    from door.mcp import tools
    registered = set(tools.REGISTRY.names())
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


def _record_and_shipped():
    """The ids inference/README.md cites, and the ids of the strategy files
    in inference/strategies/."""
    from inference import catalog
    cited = set(re.findall(r"^- `([a-z0-9-]+)`", _read("inference", "README.md"), re.M))
    shipped = {name[:-3] for name in catalog.strategy_files(catalog.SHIPPED_DIR)}
    return cited, shipped


def test_every_shipped_strategy_is_in_the_playbook_sources():
    """inference/README.md is the record the playbook is rebuilt from, so it
    holds more ids than the folder does. The other direction has to hold: a
    file in inference/strategies/ that the record does not cite came from
    nowhere."""
    cited, shipped = _record_and_shipped()
    assert shipped and shipped <= cited, sorted(shipped - cited)


@needs_skills
def test_the_skills_name_only_strategies_the_playbook_holds():
    """A skill's worked example or a doc's rule names a strategy by its id;
    an id the record cites and inference/strategies/ no longer holds is a
    rule the playbook dropped, and a session told to tune it is refused."""
    cited, shipped = _record_and_shipped()
    skills = _skills()
    texts = {"%s skill" % name: skills[name] for name in MUST_NAME}
    texts.update(("docs/" + n, _read("docs", n)) for n in os.listdir(DOCS) if n.endswith(".md"))
    dropped = {}
    for name, text in sorted(texts.items()):
        named = set(re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", text))
        if (named & cited) - shipped:
            dropped[name] = sorted((named & cited) - shipped)
    assert not dropped, dropped


def test_the_tool_reference_is_current(copy_of):
    from door.mcp import tools
    committed = _read("docs", "mcp.md")
    listed = set(re.findall(r"^\| `([a-z_]+)` \|", _section(committed, "tools"), re.M))
    assert listed == set(tools.REGISTRY.names())
    fresh = copy_of("docs/mcp.md")
    tools.REGISTRY.write_docs(fresh)
    with open(fresh, encoding="utf-8") as handle:
        assert _section(handle.read(), "tools") == _section(committed, "tools"), \
            "docs/mcp.md is behind the tools: run `.venv/bin/python -m door.mcp call db_docs`"


# --- the generated sections ------------------------------------------------------------------

def test_the_catalog_document_matches_the_strategy_files(copy_of):
    from inference import catalog
    committed = _read("docs", "inference.md")
    fresh = copy_of("docs/inference.md")
    catalog.write_docs(catalog.load(), fresh)
    with open(fresh, encoding="utf-8") as handle:
        assert _section(handle.read(), "catalog") == _section(committed, "catalog"), (
            "docs/inference.md is behind inference/strategies/: run"
            " `.venv/bin/python -m door.mcp call db_docs`")


@pytest.mark.invariant
def test_the_schema_sections_match_the_live_database(db, copy_of):
    from db.psql import schema
    committed = _read("docs", "db.md")
    fresh = copy_of("docs/db.md")
    schema.generate_docs(db, fresh)
    with open(fresh, encoding="utf-8") as handle:
        text = handle.read()
    assert _section(text, "erd") == _section(committed, "erd"), (
        "docs/db.md's ER diagrams are behind the schema: run"
        " `.venv/bin/python -m door.mcp call db_docs`")
    assert _section(text, "dictionary") == _section(committed, "dictionary"), (
        "docs/db.md's data dictionary is behind the database: run"
        " `.venv/bin/python -m door.mcp call db_docs`")


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
