import logging

import pikepdf
import pytest
from pikepdf import Dictionary

from swapfont.models import (
    FontData,
    ReplacementConfig,
    ReplacementRule,
    resolve_unicode_name,
)


def test_resolve_unicode_name_logic(caplog):
    """
    Verifies the heuristic logic for resolving font encoding descriptions to Unicode.
    Covers exact matches, ligature fuzzy matching, and failure cases.
    """
    # Case 1: Short string (passthrough)
    assert resolve_unicode_name("A") == "A"

    # Case 2: Exact Unicode Lookup
    assert resolve_unicode_name("LATIN SMALL LETTER A") == "a"
    assert resolve_unicode_name("LATIN-SMALL-LETTER-A") == "a"  # Hyphen handling

    # Case 3: Fuzzy Ligature Lookup (The specific gap)
    # "LATIN SMALL LIGATURE FI" -> unicodedata lookup("LATIN SMALL LIGATURE FI") -> 'ﬁ'
    assert resolve_unicode_name("LATIN SMALL LIGATURE FI") == "\ufb01"

    # Case 4: Complex Fuzzy (Prefix handling)
    # Checks if it tries "LATIN SMALL {clean_val}"
    # "LIGATURE FF" -> tries "LATIN SMALL LIGATURE FF" -> 'ﬀ'
    assert resolve_unicode_name("LIGATURE FF") == "\ufb00"

    # Case 5: Unresolvable (Warning)
    with caplog.at_level(logging.WARNING):
        val = "UNKNOWN CHARACTER DESCRIPTION"
        res = resolve_unicode_name(val)
        assert res == val
        assert "Could not resolve unicode description" in caplog.text


def test_fontdata_embedded_flag_true():
    fd = Dictionary(FontDescriptor=Dictionary(FontFile=True))
    fontdata = FontData("F1", fd)
    assert fontdata.is_embedded is True


def test_fontdata_get_width_fallback():
    fd = Dictionary()
    fontdata = FontData("F2", fd)
    assert fontdata.get_width(10) == 0.0


def make_fake_font_dict(**overrides):
    """
    Minimal pikepdf.Dictionary to simulate a PDF font.
    Supports /Subtype, /BaseFont, /FontDescriptor, /FirstChar, /Widths, /Encoding.
    """
    font_dict = {
        "/Subtype": "/Type1",
        "/BaseFont": "/FakeFont",
        "/FontDescriptor": pikepdf.Dictionary(
            {"/FontFile": None, "/FontFile2": None, "/FontFile3": None}
        ),
        "/FirstChar": 0,
        "/Widths": pikepdf.Array([500, 600, 700]),
        "/Encoding": pikepdf.Dictionary(
            {"/Differences": [0, *[pikepdf.Name("/" + x) for x in ["A", "B", "C"]]]}
        ),
    }
    font_dict.update(overrides)
    return pikepdf.Dictionary(font_dict)


def test_fontdata_initialization_and_widths():
    fd = FontData("/F1", make_fake_font_dict())
    assert fd.source_name == "/F1"
    assert fd.font_type == "/Type1"
    assert fd.base_font == "/FakeFont"
    assert fd.first_char == 0
    assert fd.widths == [500.0, 600.0, 700.0]
    # Check embedded detection (none actually embedded in fake)
    assert fd.is_embedded is False
    # Differences mapping
    assert fd.char_names[0] == "/A"
    assert fd.char_names[1] == "/B"
    assert fd.char_names[2] == "/C"
    # get_width works
    assert fd.get_width(0) == 500.0
    assert fd.get_width(2) == 700.0
    assert fd.get_width(10) == 0.0  # out of range


def test_fontdata_with_missing_metrics():
    fd = FontData(
        "F2",
        make_fake_font_dict(**{"/FirstChar": None, "/Widths": None, "/Encoding": None}),
    )
    # Should not crash
    assert fd.first_char is None or fd.first_char == 0
    assert fd.widths == []


def test_fontdata_embedded_detection():
    fd = FontData(
        "F3",
        make_fake_font_dict(
            **{"/FontDescriptor": pikepdf.Dictionary({"/FontFile": "stream"})}
        ),
    )
    assert fd.is_embedded is True


def test_replacement_rule_defaults():
    rule = ReplacementRule(
        source_font_name="/F1", target_font_file="dummy.ttf", target_font_name="/F_New"
    )
    assert rule.strategy == "scale_to_fit"
    assert rule.encoding_map == {}


def test_replacement_rule_validation():
    """
    Verifies that the ReplacementRule validator correctly handles
    and resolves encoding descriptions.
    """
    # Case 1: Valid resolution
    rule = ReplacementRule(
        source_font_name="Source",
        target_font_file="Target.ttf",
        encoding_map={"0x0c": "latin small ligature fi"},
    )
    # The validator should have resolved this to the unicode char
    assert rule.encoding_map["0x0c"] == "\ufb01"

    # Case 2: Unknown description (Fallback to literal)
    rule_unknown = ReplacementRule(
        source_font_name="Source",
        target_font_file="Target.ttf",
        encoding_map={"0x0d": "this is not a character name"},
    )
    # Should warn but keep the literal string
    assert rule_unknown.encoding_map["0x0d"] == "this is not a character name"


def test_replacement_rule_normalize_keys():
    rule = ReplacementRule(
        source_font_name="/F1",
        target_font_file="fake.ttf",
        target_font_name="/F_New",
        strategy="scale_to_fit",
        # Fixed: Keys must be strings for JSON/Pydantic compatibility
        encoding_map={"1": "A", "0x02": "B"},
        width_overrides={"3": 500.0},
    )
    # We just ensure it constructs without error
    assert rule.encoding_map["1"] == "A"


def test_replacement_config_list():
    rule = ReplacementRule(
        source_font_name="/F1",
        target_font_file="fake.ttf",
        target_font_name="/F_New",
        strategy="scale_to_fit",
        encoding_map={},
        width_overrides={},
    )
    # Fixed: Using 'rules' instead of 'rules' to match model definition
    config = ReplacementConfig(rules=[rule])
    assert len(config.rules) == 1


# tests/test_models.py


# ... other imports


@pytest.fixture
def empty_font_dict():
    """A minimal font dictionary, correctly attached to the PDF object."""
    return pikepdf.Dictionary(
        {
            "/Type": pikepdf.Name("/Font"),
            "/Subtype": pikepdf.Name("/Type0"),
            "/BaseFont": pikepdf.Name("/Arial"),
        }
    )


@pytest.fixture
def type3_font_dict():
    """A minimal Type 3 font dictionary."""
    return pikepdf.Dictionary(
        {
            "/Type": pikepdf.Name("/Font"),
            "/Subtype": pikepdf.Name("/Type3"),
            "/BaseFont": pikepdf.Name("/CustomType3"),
        }
    )


## Error Handling Tests for FontData Initialization


def test_fontdata_missing_width_error(empty_font_dict):
    """Covers lines 102-105 (MissingWidth ValueError/TypeError)."""
    descriptor = pikepdf.Dictionary({"/MissingWidth": pikepdf.Name("/NotANumber")})
    empty_font_dict["/FontDescriptor"] = descriptor

    # The error should be swallowed, and missing_width should remain 0.0
    fd = FontData("/F1", empty_font_dict)
    assert fd.missing_width == 0.0


def test_fontdata_fontbbox_descriptor_error(empty_font_dict):
    """Covers lines 109-115 (FontBBox descriptor ValueError/TypeError)."""
    descriptor = pikepdf.Dictionary(
        {"/FontBBox": pikepdf.Array([1, 2, 3, pikepdf.Name("/BadValue")])}
    )
    empty_font_dict["/FontDescriptor"] = descriptor

    # The error should be swallowed, and font_bbox should remain None
    fd = FontData("/F1", empty_font_dict)
    assert fd.font_bbox is None


def test_fontdata_fontbbox_type3_error(type3_font_dict):
    """Covers lines 121-129 (Type 3 FontBBox ValueError/TypeError)."""
    type3_font_dict["/FontBBox"] = pikepdf.Array([1, 2, 3, pikepdf.Name("/BadValue")])

    # The error should be swallowed, and font_bbox should remain None
    fd = FontData("/F1", type3_font_dict)
    assert fd.font_bbox is None


def test_fontdata_fontmatrix_error(empty_font_dict):
    """Covers lines 136-141 (FontMatrix ValueError/TypeError/IndexError)."""
    # 1. Non-numeric value
    empty_font_dict["/FontMatrix"] = pikepdf.Array(
        [1, 0, 0, 1, 0, pikepdf.Name("/BadValue")]
    )
    fd = FontData("/F1", empty_font_dict)
    assert fd.font_matrix == [0.001, 0, 0, 0.001, 0, 0]  # Check default is maintained

    # 2. Wrong length
    empty_font_dict["/FontMatrix"] = pikepdf.Array([1, 0, 0, 1, 0])
    fd = FontData("/F2", empty_font_dict)
    assert fd.font_matrix == [0.001, 0, 0, 0.001, 0, 0]  # Check default is maintained


def test_fontdata_widths_error(empty_font_dict):
    """Covers lines 160-161 (Widths ValueError/TypeError)."""
    empty_font_dict["/FirstChar"] = 32
    # Invalid element in the /Widths array
    empty_font_dict["/Widths"] = pikepdf.Array([100, 200, pikepdf.Name("/BadValue")])

    # The error should be swallowed, and widths should be empty
    fd = FontData("/F1", empty_font_dict)
    assert fd.widths == []
    assert fd.first_char == 32


## Type 3 Metrics Extraction Tests


def test_type3_metrics_missing_charprocs(type3_font_dict):
    """Covers line 192 (Missing /CharProcs key)."""
    # /CharProcs is not present in the fixture by default.
    fd = FontData("/F1", type3_font_dict)
    # The function should return immediately. No assertion needed other than no crash.


def test_type3_metrics_empty_charprocs(type3_font_dict):
    """Covers line 198 (Empty /CharProcs or not dict-like)."""
    # 1. Empty dict
    type3_font_dict["/CharProcs"] = pikepdf.Dictionary()
    fd = FontData("/F1", type3_font_dict)
    assert fd.type3_design_height == 0.0

    # 2. Non-dict-like object (e.g., a simple array)
    type3_font_dict["/CharProcs"] = pikepdf.Array()
    fd = FontData("/F2", type3_font_dict)
    assert fd.type3_design_height == 0.0


def test_type3_metrics_malformed_stream_error(
    type3_font_dict, temp_pdf_doc
):  # <-- Inject temp_pdf_doc
    """Covers lines 229-230 (ValueError/IndexError/AttributeError during stream parsing)."""

    # 1. Inject the font dictionary into the PDF to give it context (including the .pdf reference)
    font_dict_in_pdf = temp_pdf_doc.make_indirect(type3_font_dict)

    char_procs = pikepdf.Dictionary()

    # Stream 1: Malformed stream (missing args before d1) -> IndexError
    stream_data_bad_index = b"100 0 d1"
    # FIX: Use the PDF object reference from the now-contextualized font_dict
    char_procs[pikepdf.Name("/C1")] = pikepdf.Stream(
        temp_pdf_doc, stream_data_bad_index
    )

    # Stream 2: Malformed stream (non-numeric args) -> ValueError
    stream_data_bad_value = b"100 0 /Bad 100 200 d1"
    char_procs[pikepdf.Name("/C2")] = pikepdf.Stream(
        temp_pdf_doc, stream_data_bad_value
    )

    font_dict_in_pdf["/CharProcs"] = char_procs

    # The errors should be caught, and valid_samples should be 0, leading to a height of 0.0
    # Use the contextualized dictionary for FontData initialization
    fd = FontData("/F1", font_dict_in_pdf)
    assert fd.type3_design_height == 0.0


## Fallback Width Test


def test_get_width_fallback_missing_width(empty_font_dict):
    """Covers line 251 (Fallback to self.missing_width)."""

    # Set up a font with a positive missing width but no width array
    fd = FontData("/F1", empty_font_dict)

    # Manually set the missing width (as we tested the extraction failure earlier)
    fd.missing_width = 150.0
    fd.widths = [100.0]  # Widths array exists
    fd.first_char = 32  # Starts at ' '

    # Request a code outside the defined width array (e.g., code 100)
    # 100 is not 32, and the index 100-32=68 is out of bounds (length 1)
    width = fd.get_width(100)

    # Should fall back to missing_width (line 251)
    assert width == 150.0


# --- Merged from test_models_extra.py ---
# tests/test_models_extra.py

from fontTools.ttLib import TTLibError
from pikepdf import Name

from swapfont.models import (
    StrategyOptions,
)


# --- 108-119: Differences array processing ---
def test_fontdata_differences_array_processing():
    diff_array = [65, Name("/A"), 66, Name("/B")]
    encoding_dict = Dictionary({"/Differences": diff_array})

    font_dict = Dictionary(
        {
            "/Encoding": encoding_dict,
            "/FirstChar": 0,
            "/LastChar": 1,
            "/Widths": [500, 600],
        }
    )

    fd = FontData("font_diff_test", font_dict)
    assert fd.char_names[65] == "/A"
    assert fd.char_names[66] == "/B"


# --- 148-150: get_width fallback ---
def test_fontdata_get_width_fallback():
    font_dict = Dictionary(
        {"/FirstChar": 10, "/LastChar": 12, "/Widths": [100, 200, 300]}
    )
    fd = FontData("font_width_test", font_dict)

    # valid width
    assert fd.get_width(10) == 100
    # beyond last_char returns 0
    assert fd.get_width(50) == 0


# tests/test_models_extra.py


# --- 30-33: simulate exception reading font_dict keys ---
def test_fontdata_safe_access_exception(monkeypatch):
    class BadDict(dict):
        def get(self, key, default=None):
            raise TTLibError("boom")

    font_dict = BadDict()
    monkeypatch.setattr(FontData, "_check_embedded", lambda self, fd: None)
    monkeypatch.setattr(FontData, "_extract_metrics", lambda self, fd: None)
    fd = FontData("bad_font", font_dict)
    assert fd.font_type == "Error"
    assert fd.base_font == "Error"


# # --- 70-71: simulate exception in _check_embedded ---
# def test_fontdata_check_embedded_exception(monkeypatch):
#     class BadDict(dict):
#         def get(self, key, default=None):
#             raise RuntimeError("boom")

#     font_dict = BadDict()
#     fd = FontData("embedded_test", font_dict)
#     # No exception propagates, is_embedded stays False
#     assert not fd.is_embedded


# --- 122-138: Encoding is Name or unknown ---
def test_fontdata_encoding_name_and_unknown():
    # Name type
    font_dict_name = Dictionary({"/Encoding": Name("/WinAnsiEncoding")})
    fd_name = FontData("font_name", font_dict_name)

    # Unknown type
    font_dict_unknown = Dictionary({"/Encoding": 12345})
    fd_unknown = FontData("font_unknown", font_dict_unknown)


# --- 150: get_width fallback ---
def test_fontdata_get_width_fallback():
    font_dict = Dictionary(
        {"/FirstChar": 10, "/LastChar": 12, "/Widths": [100, 200, 300]}
    )
    fd = FontData("font_width_test", font_dict)
    # code beyond widths returns 0
    assert fd.get_width(50) == 0


def test_strategy_options_defaults():
    so = StrategyOptions()
    assert so.max_scale == 105.0
    assert so.min_scale == 95.0


def test_replacement_rule_flattened_access():
    rule = ReplacementRule(
        source_font_name="/S",
        target_font_file="t.ttf",
        target_font_name="/T",
        hybrid_max_char_spacing=0.5,
    )
    assert rule.hybrid_max_char_spacing == 0.5


def test_replacement_rule_normalize_keys():
    # Fixed: Keys must be strings
    rule = ReplacementRule(
        source_font_name="/F1",
        target_font_file="dummy.ttf",
        target_font_name="/F_New",
        strategy="scale_to_fit",
        encoding_map={"1": "A", "0x02": "B"},
        width_overrides={"3": 100},
    )
    assert rule.encoding_map["1"] == "A"
