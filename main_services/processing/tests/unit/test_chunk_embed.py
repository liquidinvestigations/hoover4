"""Unit tests for the P5 chunk+embed stage: the chunker and the e5 prefix rule.

The chunker's offsets are BYTE offsets into the UTF-8 encoding — the golden property
tested here is that `text.encode("utf-8")[start:end].decode("utf-8")` reproduces the
chunk text exactly, multibyte content included. A character/byte mix-up fails these
tests nowhere except against real multibyte text, so that case comes first.
"""

import pytest

from tasks.P5_chunk_embed.chunking import CHUNK_MAX_BYTES, chunk_page_text
from tasks.P5_chunk_embed.embedding_prefix import embedding_input


class TestChunkPageText:
    def test_empty_and_whitespace_only(self):
        assert chunk_page_text("") == []
        assert chunk_page_text("   \n\t  ") == []

    def test_short_text_is_one_chunk(self):
        text = "  hello world, this is a short page.  "
        chunks = chunk_page_text(text)
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].text == "hello world, this is a short page."
        encoded = text.encode("utf-8")
        assert encoded[chunks[0].index_start:chunks[0].index_end].decode("utf-8") == chunks[0].text

    def test_byte_offsets_roundtrip_multibyte(self):
        # "€" is 3 bytes and "—" is 3 bytes; a character-offset implementation
        # produces offsets that slice these tests' strings at the wrong places.
        text = "€ " * 400 + "tail"
        chunks = chunk_page_text(text, max_bytes=300, overlap_bytes=60)
        assert len(chunks) > 1
        encoded = text.encode("utf-8")
        for chunk in chunks:
            assert encoded[chunk.index_start:chunk.index_end].decode("utf-8") == chunk.text
            assert chunk.index_end - chunk.index_start <= 300

    def test_offsets_are_bytes_not_characters(self):
        text = "€" * 100  # 100 characters, 300 bytes
        chunks = chunk_page_text(text)
        assert chunks[0].index_end == 300  # bytes, not 100 characters

    def test_chunks_cover_the_text_in_order_with_overlap(self):
        words = [f"word{i:04d}" for i in range(500)]
        text = " ".join(words)
        chunks = chunk_page_text(text, max_bytes=600, overlap_bytes=120)
        assert len(chunks) > 3
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        # In order, each starting where the previous one's overlap region lives.
        for prev, cur in zip(chunks, chunks[1:]):
            assert prev.index_start < cur.index_start < prev.index_end
        # The union of chunks mentions every word (nothing dropped at boundaries).
        covered = " ".join(c.text for c in chunks)
        for word in ("word0000", "word0250", "word0499"):
            assert word in covered

    def test_overlap_actually_duplicates_boundary_words(self):
        text = " ".join(f"w{i:03d}" for i in range(200))
        chunks = chunk_page_text(text, max_bytes=200, overlap_bytes=50)
        assert len(chunks) > 1
        # The overlap walk goes back ~overlap_bytes (50 bytes ≈ 10 of these 5-byte
        # words), so chunk 0's tail word reappears near the start of chunk 1.
        first_tail = chunks[0].text.split()[-1]
        assert first_tail in chunks[1].text.split()[:12]

    def test_single_overlong_word_is_its_own_chunk(self):
        # Truncating it would split a word (and maybe a UTF-8 sequence); dropping it
        # would lose text. It becomes a chunk over the byte budget instead.
        text = "start " + "x" * 5000 + " end"
        chunks = chunk_page_text(text, max_bytes=300, overlap_bytes=50)
        assert any(c.text == "x" * 5000 for c in chunks)
        assert chunks[0].text.startswith("start")
        assert chunks[-1].text.endswith("end")

    def test_deterministic(self):
        text = "the same page text " * 100
        first = [(c.index_start, c.index_end) for c in chunk_page_text(text)]
        second = [(c.index_start, c.index_end) for c in chunk_page_text(text)]
        assert first == second

    def test_invalid_budgets_raise(self):
        with pytest.raises(ValueError):
            chunk_page_text("text", max_bytes=0)
        with pytest.raises(ValueError):
            chunk_page_text("text", max_bytes=100, overlap_bytes=100)

    def test_default_budget_fits_e5_small(self):
        # The chunk budget exists so one chunk fits the model's 512-token window;
        # pin the constant so a bump is a deliberate act.
        assert CHUNK_MAX_BYTES == 1200


class TestEmbeddingInput:
    def test_e5_small_prefixes(self):
        assert embedding_input("intfloat/multilingual-e5-small", "passage", "text") == \
            ("passage: text", None)
        assert embedding_input("intfloat/multilingual-e5-small", "query", "text") == \
            ("query: text", None)

    def test_e5_instruct_convention_differs(self):
        # e5-large-instruct: passages go bare, queries go bare plus a task
        # description the SERVER wraps as its instruct template.
        assert embedding_input("intfloat/multilingual-e5-large-instruct", "passage", "text") == \
            ("text", None)
        text, task = embedding_input("intfloat/multilingual-e5-large-instruct", "query", "what is water")
        assert text == "what is water"
        assert task  # a non-empty task description

    def test_unknown_model_refuses(self):
        # Never guess a convention: a wrong prefix degrades retrieval silently.
        with pytest.raises(ValueError):
            embedding_input("sentence-transformers/all-MiniLM-L6-v2", "passage", "text")
        with pytest.raises(ValueError):
            embedding_input("", "passage", "text")

    def test_unknown_kind_refuses(self):
        with pytest.raises(ValueError):
            embedding_input("intfloat/multilingual-e5-small", "document", "text")
