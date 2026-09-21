"""The wiki's markup, reduced to text: the six parsers all read through these.
Pure - no network, no database, so the pull-request gate covers them."""

from db.data.wiki import markup


def test_a_template_reduces_to_the_words_it_shows():
    # {{tt|shown|tooltip}} shows the first; {{proj|hitscan}} the last
    assert markup.wikitext_to_text("{{tt|150|per shot}} damage") == "150 damage"
    assert markup.wikitext_to_text("{{proj|beam|hitscan}}") == "hitscan"
    assert markup.wikitext_to_text("{{hero|Ana}} sleeps") == "Ana sleeps"
    # nested: the innermost reduces first, and the result reduces again
    assert markup.wikitext_to_text("{{tt|{{proj|a|hitscan}}|why}}") == "hitscan"
    # a named parameter is not a shown word
    assert markup.wikitext_to_text("{{tt|90|note=over 3 s}}") == "90"


def test_an_unclosed_template_loses_its_braces_and_keeps_its_words():
    assert markup.wikitext_to_text("{{tt|90 over 3 seconds") == "tt|90 over 3 seconds"
    assert markup.wikitext_to_text("") == "" and markup.wikitext_to_text(None) == ""


def test_links_comments_breaks_and_tags_come_out_as_prose():
    assert markup.wikitext_to_text("[[Ana|the sniper]] heals") == "the sniper heals"
    assert markup.wikitext_to_text("[[Nano Boost]] is an ultimate") \
        == "Nano Boost is an ultimate"
    assert markup.wikitext_to_text("before<!-- a note -->after") == "beforeafter"
    assert markup.wikitext_to_text("one<br>two") == "one; two"
    assert markup.wikitext_to_text("<b>bold</b> text") == "bold text"
    assert markup.tidy("  spaced   out  ; ") == "spaced out"
    assert markup.tidy("'''loud''' and ''soft''") == "loud and soft"
    assert markup.tidy("see https://example.org/x now") == "see now"


def test_a_cargo_field_is_read_as_rendered_html():
    assert markup.html_to_text("120<br/>per second") == "120; per second"
    assert markup.html_to_text("<span class='x'>90</span> hp") == "90 hp"
    assert markup.html_to_text("[[File:Icon.png|20px]]damage") == "damage"
    assert markup.html_to_text("") == ""


def test_an_ability_type_splits_on_either_spelling_the_wiki_uses():
    assert markup.split_type("Weapon;;Hip Fire") == ("Weapon", "Hip Fire")
    assert markup.split_type("Weapon (Hip Fire)") == ("Weapon", "Hip Fire")
    assert markup.split_type("Ultimate Ability;;Mech") == ("Ultimate Ability", "Mech")
    assert markup.split_type("Ability") == ("Ability", None)
    assert markup.split_type("  Weapon ()  ") == ("Weapon", None)
    assert markup.split_type("") == ("", None) and markup.split_type(None) == ("", None)


def test_a_template_body_splits_on_its_own_pipes_only():
    block = "{{Ability details|name=Sleep Dart|damage={{tt|5|and a nap}}|link=[[Ana|her]]}}"
    [found] = list(markup.find_templates(block, r"Ability[ _]details"))
    assert found == block
    params = markup.parse_params(found)
    assert params["name"] == "Sleep Dart"
    assert params["damage"] == "{{tt|5|and a nap}}"       # the nested pipe is not a split
    assert params["link"] == "[[Ana|her]]"
    # the key is lowercased and spaces become underscores; an unnamed part is dropped
    assert markup.parse_params("{{X|first|Ability Name = Fade}}") == {"ability_name": "Fade"}


def test_find_templates_yields_each_top_level_block():
    text = "{{Ability details|a=1}} prose {{Ability_details|b={{tt|2|two}}}} more"
    found = list(markup.find_templates(text, r"Ability[ _]details"))
    assert len(found) == 2
    assert markup.parse_params(found[0]) == {"a": "1"}
    assert markup.parse_params(found[1])["b"] == "{{tt|2|two}}"
