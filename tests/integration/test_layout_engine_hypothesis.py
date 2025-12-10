from unittest.mock import MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pdfbeaver.utils import extract_string_bytes

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.models import ReplacementConfig, ReplacementRule

# --- Strategies ---


@st.composite
def pdf_text_strings(draw):
    """Generates strings that might appear in PDF text objects."""
    # We exclude surrogates to avoid encoding issues during simple tests
    return draw(
        st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1)
    )


@st.composite
def pdf_tj_operands(draw):
    """Generates operands for Tj (single string)."""
    text = draw(pdf_text_strings())
    return [text]


@st.composite
def pdf_TJ_operands(draw):
    """Generates operands for TJ (list of strings and numbers)."""
    elements = draw(
        st.lists(
            st.one_of(
                pdf_text_strings(),
                st.floats(min_value=-100, max_value=100),
                st.integers(min_value=-100, max_value=100),
            ),
            min_size=1,
        )
    )
    return [elements]


# --- Fixtures ---


@pytest.fixture
def empty_engine():
    config = ReplacementConfig(rules=[])
    return LayoutEngine(
        config=config,
        target_font_cache={},
        custom_encoding_maps={},
        source_font_cache={},
        source_pikepdf_fonts={},
    )


# --- Tests ---


def test_extract_string_bytes_robustness(empty_engine):
    """Tests that extract_string_bytes handles various input types correctly."""
    # 1. Bytes
    assert extract_string_bytes(b"hello") == b"hello"

    # 2. String (Latin1)
    assert extract_string_bytes("hello") == b"hello"

    # 3. String (Unicode fallback)
    # Euro sign \u20ac is not in latin1, should fallback to utf-8
    utf8_char = "\u20ac"
    assert extract_string_bytes(utf8_char) == utf8_char.encode("utf-8")

    # 4. Object with as_bytes (mocking pikepdf.String behavior)
    mock_str = MagicMock()
    mock_str.as_bytes.return_value = b"mocked"
    assert extract_string_bytes(mock_str) == b"mocked"

    # 5. Fallback for unknown types (e.g., int)
    assert extract_string_bytes(5) == b"5"


@given(st.one_of(pdf_tj_operands(), pdf_TJ_operands()))
def test_rewrite_operands_passthrough(operands):
    """
    Refactoring Invariant: If no active rule is set, rewrite_text_operands
    must return operands unchanged.
    """
    # Fix: Instantiate engine INSIDE the test for Hypothesis compatibility
    config = ReplacementConfig(rules=[])
    engine = LayoutEngine(
        config=config,
        target_font_cache={},
        custom_encoding_maps={},
        source_font_cache={},
        source_pikepdf_fonts={},
    )

    # Try with both Tj and TJ operator names
    result_tj = engine.rewrite_text_operands("Tj", operands)
    assert result_tj == operands

    result_TJ = engine.rewrite_text_operands("TJ", operands)
    assert result_TJ == operands


def test_set_active_font_map_inversion(empty_engine):
    """
    Tests the logic that inverts custom_encoding_maps (Char<->Slot)
    and handles mixed key types.
    """
    # Setup
    config = ReplacementConfig(
        rules=[
            ReplacementRule(
                source_font_name="/F1",
                source_base_font="Arial",
                target_font_file="Target.ttf",
                target_font_name="/F_New",
            )
        ]
    )

    # Scenario 1: Map is Slot (int) -> Char (str) [Standard Config]
    encoding_map_1 = {10: "A", 11: "B"}

    engine = LayoutEngine(
        config=config,
        target_font_cache={"Target.ttf": MagicMock()},  # Mock wrapper
        custom_encoding_maps={"Target.ttf": encoding_map_1},
        source_font_cache={},
        source_pikepdf_fonts={},
    )

    # Act
    engine.set_active_font("/F1", 12.0)

    # Assert: Engine should invert to Char -> Slot
    assert engine.active_target_slot_map == {"A": 10, "B": 11}

    # Scenario 2: Mixed Input (lines 86-89 coverage)
    # Map contains both Char -> Slot and Slot -> Char
    engine.custom_encoding_maps["Target.ttf"] = {"C": 12, 13: "D"}
    engine.set_active_font("/F1", 12.0)
    assert engine.active_target_slot_map == {"C": 12, "D": 13}


def test_type3_scaling_logic(empty_engine):
    """Tests that Type 3 scaling factors are applied when source font is Type 3."""
    # Setup rule
    # Fix: Added target_font_name
    rule = ReplacementRule(
        source_font_name="/T3",
        source_base_font="Type3",
        target_font_file="T.ttf",
        target_font_name="/F_New",
    )
    empty_engine.config.rules = [rule]

    # Setup Source Cache with Type 3 data
    mock_source_data = MagicMock()
    mock_source_data.is_type3 = True
    mock_source_data.type3_design_height = 0.5  # Scale factor

    empty_engine.source_font_cache = {"/T3": mock_source_data}

    # Act
    font_name, font_size = empty_engine.set_active_font("/T3", 10.0)

    # Assert
    assert empty_engine.current_type3_scale_factor == 0.5
    assert font_size == 5.0  # 10.0 * 0.5


def test_calculate_source_width_fallback_logic():
    """
    Tests the width calculation logic with mocked PDF structures.
    Covers lines 111-196, including TJ gap math and heuristics.
    """
    engine = LayoutEngine(
        ReplacementConfig(rules=[]), {}, {}, {}, source_pikepdf_fonts={}
    )

    # Mock font object
    widths = [500, 600]
    font_obj = {
        "/FirstChar": 65,
        "/LastChar": 66,
        "/Widths": widths,
        "/FontMatrix": [0.001, 0, 0, 0.001, 0, 0],
    }

    engine.source_pikepdf_fonts = {"/F1": font_obj}
    engine.current_pdf_font_name = "F1"

    # State dict mock
    tstate_mock = MagicMock()
    tstate_mock.fontsize = 10.0
    tstate_mock.matrix = [1, 0, 0, 1, 0, 0]  # Identity text matrix
    ctm = [1, 0, 0, 1, 0, 0]  # Identity CTM

    state_dict = {"tstate": tstate_mock, "ctm": ctm}

    # Case 1: "Tj" with "A"
    width = engine.calculate_source_width_fallback("Tj", ["A"], state_dict)
    assert width == 5.0

    # Case 2: "TJ" with ["A", 100, "B"]
    width = engine.calculate_source_width_fallback("TJ", [["A", 100, "B"]], state_dict)
    assert width == 10.0

    # Case 3: Heuristic check (coverage for lines 193-194)
    font_obj["/Widths"] = [0, 0]
    width = engine.calculate_source_width_fallback("Tj", ["A"], state_dict)
    assert width == 5.0


def test_rewrite_text_operands_logic():
    """
    Tests the actual rewriting of text bytes and structural integrity.
    Covers lines 281-325.
    """
    # Setup
    # Fix: Added target_font_name
    rule = ReplacementRule(
        source_font_name="/F1",
        source_base_font="A",
        target_font_file="T.ttf",
        target_font_name="/F_New",
    )

    # Map 'A' (65) -> Slot 10
    map_dict = {"A": 10}

    engine = LayoutEngine(
        ReplacementConfig(rules=[rule]),
        target_font_cache={"T.ttf": MagicMock()},
        custom_encoding_maps={"T.ttf": map_dict},
        source_font_cache={},
        source_pikepdf_fonts={},
    )

    engine.set_active_font("/F1", 10.0)

    # Case 1: Tj rewrite
    result = engine.rewrite_text_operands("Tj", ["A"])
    assert bytes(result[0]) == b"\n"  # \x0a

    # Case 2: Unmapped char 'B'
    result = engine.rewrite_text_operands("Tj", ["B"])
    assert bytes(result[0]) == b"B"

    # Case 3: TJ rewrite (Mixed list)
    result = engine.rewrite_text_operands("TJ", [["A", 50, "B"]])
    arr = result[0]
    assert bytes(arr[0]) == b"\n"
    assert arr[1] == 50
    assert bytes(arr[2]) == b"B"
