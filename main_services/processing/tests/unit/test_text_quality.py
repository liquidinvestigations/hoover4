"""The non-linguistic text filter that stands between extraction and the GPU.

Two failure directions, and they are not symmetric. A **false negative** puts an image's
pixel rows into vector search, where a passage of noise is close to everything: live,
`search_collections("Eiffel Tower height")` returned an `.xpm` colour table and an `.eml`'s
base64 as its top two hits, and the chat transcript rendered them. A **false positive**
costs one passage its semantic searchability. The bytes stay in `text_content` and the
keyword index still finds them.

So the negatives here (real documents that must survive) are the tests that matter most,
and they are deliberately awkward: prose in three languages, a numeric table, a document
that quotes a hash, and text that is mostly hex letters because it is about a café.
"""

import pytest

from tasks.text_quality import is_linguistic, non_linguistic_reason


def _repeat(unit: str, n: int) -> str:
    return "".join(unit for _ in range(n))


class TestNonLinguisticIsCaught:
    def test_a_base64_attachment_body(self):
        """Verbatim shape of an `.eml` attachment as the parser hands it over."""
        text = _repeat(
            "pZWpNM8HYDWCnMqI2YQWMuI8XJjloQzf5CkHieLmhzg+BSaTuBpegi29+qQ9PMn2XML6CCd1\r\n",
            8,
        )
        assert not is_linguistic(text)
        assert "encoded" in non_linguistic_reason(text)

    def test_xpm_pixel_rows(self):
        """Character-per-pixel image data: the run that reached the chat transcript."""
        text = _repeat(". 5 6 c 0 @ . . X O O # & 5 6 5 m b ", 12)
        assert not is_linguistic(text)
        assert "single characters" in non_linguistic_reason(text)

    def test_an_xbm_byte_dump_despite_looking_like_letters(self):
        """`0xFB` is 67 % "letters" by `str.isalpha`, so a letter-ratio rule alone lets a
        whole bitmap through. 300 chunks of this were being embedded."""
        text = _repeat("0xFB, 0xFF, 0xBF, 0xDE, 0x7F, 0xEE, 0xEF, 0xBB, ", 12)
        assert not is_linguistic(text)
        assert "numeric literals" in non_linguistic_reason(text)

    def test_svg_path_data(self):
        text = _repeat('d="M18028 2348 c5 -5 16 -8 23 -6 8 3 3 7 -10 11 -17 4 -21 3 -13 -5z" ', 6)
        assert not is_linguistic(text)

    def test_a_wall_of_punctuation_and_symbols(self):
        text = _repeat("|-+-|=#=|~~~|***|///|===|<<>>|%%%|@@@|^^^|:::|;;;|,,,|...|", 6)
        assert not is_linguistic(text)


class TestRealDocumentsSurvive:
    """A false positive here silently removes a real passage from semantic search."""

    @pytest.mark.parametrize(
        "text",
        [
            # English.
            "During its construction, the Eiffel Tower surpassed the Washington Monument "
            "to become by far the tallest human-made structure in the world, a title it "
            "held for 41 years until the Chrysler Building was finished in 1930.",
            # Romanian with diacritics. The corpus this pipeline was built for.
            "Prin multipol electric se înţelege o porţiune de circuit electric cu borne "
            "de acces, dar fără cuplaje magnetice cu exteriorul. De regulă multipolul se "
            "consideră pasiv, adică nu are surse proprii şi funcţionează liniar.",
            # Chinese: no spaces, so it reads as few long tokens, never many short ones.
            "埃菲尔铁塔是法国巴黎的一座铁制格架塔，位于战神广场，於一八八九年建成，"
            "高三百三十公尺，是世界上最著名的地標之一，每年吸引數百萬遊客前來參觀遊覽。",
        ],
    )
    def test_prose_is_kept(self, text):
        assert is_linguistic(text), non_linguistic_reason(text)

    def test_a_numeric_table_in_a_real_document_is_kept(self):
        """Rows of figures with their labels are a document, not a byte dump."""
        text = (
            "Regiune Populaţie Suprafaţă Densitate\n"
            "Bucureşti 1,883,425 228.00 8,260\n"
            "Cluj 691,106 6,674.00 103\n"
            "Timiş 683,540 8,697.00 78\n"
            "Iaşi 772,348 5,476.00 141\n"
            "Constanţa 684,082 7,071.00 96\n"
            "Total national figures for the reporting year, as published by the institute.\n"
        )
        assert is_linguistic(text), non_linguistic_reason(text)

    def test_a_document_that_quotes_a_hash_is_kept(self):
        """One long token is a citation; a page of them is a dump."""
        text = (
            "The release was published with the checksum "
            "fbd8cb078ac24ba9a4649cddc32d85f953eddb5cb378fbb19fc607df1dd18c92 so that "
            "recipients could verify the archive before extracting it, and the signature "
            "was countersigned by the maintainer on the same day as the announcement."
        )
        assert is_linguistic(text), non_linguistic_reason(text)

    def test_prose_built_from_hex_letters_is_kept(self):
        """`cafe`, `faced`, `bead` and friends all parse as hexadecimal. The numeric rule
        must be about token *shape*, not about which letters appear."""
        text = (
            "The cafe faced a decade of debate: a bead of coffee, a dab of cocoa, a "
            "faded facade, and a bad decaf. Each accede added a decade to the deed, and "
            "the cafe faced the decade with a decaf and a bead of cocoa on the facade."
        )
        assert is_linguistic(text), non_linguistic_reason(text)


class TestJudgementBoundaries:
    def test_short_text_is_never_judged(self):
        """No distribution to measure, and a heading like "3.1 A" trips every rule."""
        assert is_linguistic("3.1 A")
        assert is_linguistic("0xFB, 0xFF, 0xBF")
        assert is_linguistic("")

    def test_whitespace_only_text_does_not_divide_by_zero(self):
        assert non_linguistic_reason(" " * 400) is None

    def test_the_reason_names_the_rule_that_fired(self):
        """A dropped chunk that cannot be explained is a dropped chunk nobody trusts."""
        reason = non_linguistic_reason(_repeat("0xFB, 0xFF, 0xBF, 0xDE, ", 20))
        assert reason and "%" in reason
