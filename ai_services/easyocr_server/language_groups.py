"""The EasyOCR language groups that the image installs and that `/health` reports.

One group is one Reader: EasyOCR builds one recognition model for each Reader and
cannot mix scripts in one. The automatic OCR planner of the worker sends one group, or
one code of a group, in each request.

The worker keeps the same groups in `EASY_SCRIPT_GROUPS` of
`main_services/processing/tasks/automatic_ocr.py`, with `ch_tra` for the `HanT` model
hint. The image build context holds only this folder, so the worker cannot import this
file. `tests/test_language_groups.py` fails when the two definitions differ.

The groups follow the language lists of `easyocr/config.py` in the easyocr package.
The planner reads the reported list as the installed capability, and the list is part
of the identity of each automatic OCR plan. A change to it selects every applied file
for the OCR processing update again.
"""

INSTALLED_GROUPS = {
    "Latin": ("en", "af", "az", "bs", "cs", "cy", "da", "de", "es", "et", "fr", "ga", "hr", "hu", "id", "is", "it", "ku", "la", "lt", "lv", "mi", "ms", "mt", "nl", "no", "oc", "pi", "pl", "pt", "ro", "rs_latin", "sk", "sl", "sq", "sv", "sw", "tl", "tr", "uz", "vi"),
    "Cyrillic": ("ru", "rs_cyrillic", "be", "bg", "uk", "mn", "abq", "ady", "kbd", "ava", "dar", "inh", "che", "lbe", "lez", "tab", "tjk"),
    "Arabic": ("ar", "fa", "ug", "ur"),
    "Devanagari": ("hi", "mr", "ne", "bh", "mai", "ang", "bho", "mah", "sck", "new", "gom", "sa", "bgc"),
    "Bengali": ("bn", "as", "mni"),
    "Han": ("ch_sim",),
    "HanT": ("ch_tra",),
    "Japanese": ("ja",),
    "Hangul": ("ko",),
    "Tamil": ("ta",),
    "Telugu": ("te",),
    "Kannada": ("kn",),
    "Thai": ("th",),
}

#: Codes that easyocr 1.7.2 lists but cannot load. The package has no character file for
#: `sa`, `bgc` and `mni`, and a Reader raises FileNotFoundError. The published Tamil model
#: has another output size than the Tamil character file, and a Reader of `ta` raises
#: RuntimeError. They stay in the groups so that the reported list, and with it the plan
#: identity, does not change.
UNLOADABLE = frozenset({"sa", "bgc", "mni", "ta"})

#: The language sets that the image build loads, so that their weights are in the image.
#: A Reader of `en` alone uses the English model, and a Reader of another Latin set uses
#: the Latin model, so `en` is a separate set.
BAKED_READERS = tuple(loadable for loadable in (
    tuple(code for code in codes if code not in UNLOADABLE) for codes in INSTALLED_GROUPS.values())
    if loadable) + (("en",),)


def installed_languages() -> list:
    """Every code of the installed groups, sorted. The planner reads this list."""
    return sorted({code for codes in INSTALLED_GROUPS.values() for code in codes})


def loadable_languages() -> list:
    """The installed codes whose models the image holds, sorted."""
    return [code for code in installed_languages() if code not in UNLOADABLE]
