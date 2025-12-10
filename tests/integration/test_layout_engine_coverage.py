from unittest.mock import MagicMock

import pytest
from pdfbeaver.utils import extract_string_bytes

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.models import ReplacementConfig


@pytest.fixture
def coverage_engine():
    config = ReplacementConfig(rules=[])
    return LayoutEngine(
        config=config,
        target_font_cache={},
        custom_encoding_maps={},
        source_font_cache={},
        source_pikepdf_fonts={},
    )


def test_fallback_reason_1_no_font_name(coverage_engine):
    """Cover lines 120-122: Missing font name or unsupported op."""
    coverage_engine.current_pdf_font_name = None
    width = coverage_engine.calculate_source_width_fallback("Tj", ["foo"], {})
    assert width == 0.0

    # Also test unsupported op
    coverage_engine.current_pdf_font_name = "/F1"
    width = coverage_engine.calculate_source_width_fallback("BadOp", ["foo"], {})
    assert width == 0.0


def test_fallback_reason_2_missing_font(coverage_engine):
    """Cover lines 128-130: Font name not found in source cache."""
    coverage_engine.current_pdf_font_name = "/F1"
    # source_pikepdf_fonts is empty
    width = coverage_engine.calculate_source_width_fallback("Tj", ["foo"], {})
    assert width == 0.0


def test_fallback_reason_3_incomplete_font_obj(coverage_engine):
    """Cover lines 134-136: Font object missing required metrics."""
    coverage_engine.current_pdf_font_name = "/F1"
    # Missing /Widths
    coverage_engine.source_pikepdf_fonts = {"/F1": {"/FirstChar": 0, "/LastChar": 1}}
    width = coverage_engine.calculate_source_width_fallback("Tj", ["foo"], {})
    assert width == 0.0


def test_target_width_no_wrapper(coverage_engine):
    """Cover lines 203-204: Calculation when no target wrapper is active."""
    coverage_engine.active_wrapper = None
    width = coverage_engine.calculate_target_visual_width("Tj", ["A"])
    # Default fallback in code is 1.0
    assert width == 1.0


def test_target_width_calculation_logic(coverage_engine):
    """Cover lines 216-227: Numeric gaps and mapped characters."""
    mock_wrapper = MagicMock()
    # 1000 units width for 'A'
    mock_wrapper.get_char_width.return_value = 1000
    coverage_engine.active_wrapper = mock_wrapper
    coverage_engine.active_font_size = 12.0

    # Case 1: Numeric item (gap)
    # Item is 1000. Logic: total -= (1000/1000) * 12.0 = -12.0
    width = coverage_engine.calculate_target_visual_width("TJ", [[1000]])
    assert width == -12.0

    # Case 2: String "A" (ord 65)
    # target_char gets 'A'. get_char_width('A') -> 1000.
    # w_pts = (1000/1000) * 12.0 = 12.0
    # total += 12.0
    width = coverage_engine.calculate_target_visual_width("TJ", [["A"]])
    assert width == 12.0


def test_rewrite_operands_extra_args(coverage_engine):
    """Cover lines 305-306: Operators with multiple arguments (like quotes)."""
    # Setup active rule to allow rewriting logic to proceed
    coverage_engine.active_rule = MagicMock()
    # Empty map avoids actual mapping but lets us pass the initial checks
    coverage_engine.active_target_slot_map = {}

    # Simulate a quoted text operator with extra args: (arg1, arg2, text)
    operands = ["SomeString", 10, 20]

    result = coverage_engine.rewrite_text_operands('"', operands)

    # Ensure the extra operands (10, 20) were preserved and appended
    assert len(result) == 3
    assert result[1] == 10
    assert result[2] == 20


def test_extract_string_bytes_unicode_fallback(coverage_engine):
    """Cover lines 334-335: Fallback to UTF-8 when Latin1 fails."""
    # Smiley face cannot be encoded in Latin1
    smiley = "😊"
    result = extract_string_bytes(smiley)
    assert result == smiley.encode("utf-8")


def test_map_source_byte_value_error(coverage_engine):
    """Cover lines 367-368: Handling invalid integer conversion."""
    coverage_engine.active_rule = MagicMock()
    coverage_engine.active_target_slot_map = {}

    # 0x110000 is outside the valid Unicode range, causing chr() to raise ValueError
    target, original = coverage_engine._map_source_byte(0x110000)

    # Should catch ValueError and return None
    assert target is None
    assert original == 0x110000
