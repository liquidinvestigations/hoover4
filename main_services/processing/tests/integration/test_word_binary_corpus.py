"""Binary Word text checks over the pinned public file."""

from pathlib import Path
import shutil

import pytest

from tasks.P3_parse_files.word_binary import extract_binary_word_text, is_binary_word


DOCUMENT = Path("/testdata/hoover-testdata/data/disk-files/pdf-doc-txt/sample (1).doc")


def test_word_symbol_text_uses_the_declared_font():
    if not DOCUMENT.exists():
        pytest.skip("public Word fixture is not mounted")
    if not shutil.which("soffice"):
        pytest.skip("LibreOffice is not installed in this exploratory image")
    assert is_binary_word(str(DOCUMENT))
    text = extract_binary_word_text(str(DOCUMENT))
    assert "energy density" in text
    assert "1 erg/cm³ → 10⁻¹ J/m³" in text
    assert "1 erg/cm3 ( 10(1 J/m3" not in text
    assert "\ufffd" not in text
