"""The wiki's markup, reduced to text: the six parsers all read through these.
Pure - no network, no database, so the pull-request gate covers them."""

import re
from datetime import date

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


def test_a_date_reads_day_or_month_first_and_needs_a_year():
    date_re = re.compile(markup.DATE)
    for text in ("6 October 2026", "October 6, 2026", "october 6 2026"):
        match = date_re.fullmatch(text)
        assert match and markup.parse_date(match.groups(), match.group(5)) == date(2026, 10, 6)
    yearless = date_re.fullmatch("February 18")
    assert yearless and markup.parse_date(yearless.groups(), yearless.group(5)) is None
    # a year the text gives elsewhere, as the far end of a season's run does
    assert markup.parse_date(yearless.groups(), "2025") == date(2025, 2, 18)
    impossible = date_re.fullmatch("30 February 2026")
    assert impossible and markup.parse_date(impossible.groups(), impossible.group(5)) is None


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


def test_a_section_body_ends_at_the_next_heading_of_any_depth():
    dive = "=== Dive heroes ==="
    text = dive + "\n* [[Winston]]\n=== Brawl heroes ===\n* [[Reinhardt]]\n"
    assert markup.section_body(text, len(dive)) == "\n* [[Winston]]\n"
    season = "=== Season 1 ==="
    text = season + "\n(4 October 2022 - 6 December 2022)\n==References==\n"
    assert markup.section_body(text, len(season)) == "\n(4 October 2022 - 6 December 2022)\n"
    # no heading after it: the body runs to the end
    poke = "=== Poke heroes ==="
    assert markup.section_body(poke + "\n* [[Ana]]", len(poke)) == "\n* [[Ana]]"


def test_a_top_level_section_body_keeps_its_subsections():
    gameplay = "== Gameplay =="
    text = gameplay + "\nA route.\n=== Docks ===\nA pier.\n== Strategy ==\nHold.\n"
    assert markup.section_body(text, len(gameplay), top_level=True) == (
        "\nA route.\n=== Docks ===\nA pier.\n")
    assert markup.section_body(text, len(gameplay)) == "\nA route.\n"


def test_a_file_a_citation_and_a_wikitable_are_each_matched_whole():
    # a caption may hold a link of either kind; Image: is File:'s other name
    caption = "[[Image:Push.png|thumb|The [[Push]] robot, [https://example.org its page]]]"
    assert markup.FILE_LINK_RE.sub("", "a%sb" % caption) == "ab"
    assert markup.FILE_LINK_RE.sub("", "a[[File:x.png|20px]]b") == "ab"
    # a citation self-closed with two slashes closes itself, and swallows no prose
    cited = 'a<ref name = "PE2015"//> b<ref>[[Source]]</ref>c'
    assert markup.REF_RE.sub("", cited) == "a bc"
    assert markup.REF_RE.sub("", "<references/>") == "<references/>"
    assert markup.TABLE_RE.findall("x\n{|\n| cell\n|}\ny") == ["{|\n| cell\n|}"]


def test_a_link_is_read_innermost_first_and_gives_its_target():
    # a file's caption may hold the link a parser wants
    assert markup.LINK_RE.findall("[[File:x.png|thumb|[[Hazard]]]] [[Ana|the sniper]]") == [
        "Hazard", "Ana"]
    assert markup.LINK_RE.findall("{{flag|kr}} [[Busan]]") == ["Busan"]
