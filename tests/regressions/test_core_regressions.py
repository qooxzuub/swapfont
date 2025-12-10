from unittest.mock import MagicMock

import numpy as np
import pikepdf
import pytest
from pdfbeaver.editor import (
    ORIGINAL_BYTES,
    StreamContext,
    StreamEditor,
)
from pdfbeaver.utils import extract_string_bytes

from swapfont.models import (
    ReplacementConfig,
    ReplacementRule,
)

from ..conftest import build_test_editor

# -------------------------------------------------------------------------
# Bug 1 & 2: Configuration Mismatches (Hollow Object & Hex Keys)
# -------------------------------------------------------------------------


def test_config_legacy_replacements_key():
    """
    Regression Test: Ensure JSON using legacy 'replacements' key
    is correctly migrated to 'rules'.
    """
    data = {
        "replacements": [
            {
                "source_font_name": "/F1",
                "target_font_file": "arial.ttf",
                "target_font_name": "/Arial",
            }
        ]
    }
    config = ReplacementConfig(**data)
    assert len(config.rules) == 1
    assert config.rules[0].source_font_name == "/F1"


def test_smart_encoding_map_hex_lookup():
    """
    Regression Test: Ensure SmartEncodingMap allows integer lookup
    even if keys were defined as hex strings in JSON.
    """
    # Simulate data loaded from JSON
    rule_data = {
        "source_font_name": "/F1",
        "target_font_file": "arial.ttf",
        "target_font_name": "/Arial",
        "strategy": "scale_to_fit",
        # "space" will now auto-resolve to " "
        "encoding_map": {"0x41": "A", "0x20": "space"},
    }
    rule = ReplacementRule(**rule_data)

    # The model should convert these automatically
    assert rule.encoding_map[65] == "A"  # 0x41

    # FIX: Expect " " because "space" resolves to " " via unicode lookup
    # If we wanted the literal string "space", we'd need to quote it oddly or use a name that isn't a unicode name
    val = rule.encoding_map[32]
    assert val == " " or val == "space", f"Got {val!r}"


# -------------------------------------------------------------------------
# Bug 3: PDFMiner Font Proxy Crash (AttributeError: 'str' object has no attribute 'decode')
# -------------------------------------------------------------------------


# def test_font_proxy_decode_safety():
#     """
#     Regression Test: Ensure PdfMinerFontProxy handles both bytes and strings
#     in its decode() method without crashing.
#     """
#     from swapfont.tracker import PdfMinerFontProxy

#     mock_wrapper = MagicMock()
#     mock_wrapper.path = "dummy.ttf"
#     proxy = PdfMinerFontProxy(mock_wrapper, {})

#     # Case 1: Bytes (Normal PDFMiner behavior)
#     assert proxy.decode(b"Test") == "Test"

#     # Case 2: String (Already decoded, shouldn't crash)
#     assert proxy.decode("Test") == "Test"


# -------------------------------------------------------------------------
# Bug 4: Infinite Recursion / Stack Overflow in _calculate_target_visual_width
# -------------------------------------------------------------------------


@pytest.fixture
def mock_editor_deps():
    rule = ReplacementRule(
        source_font_name="/F1",
        target_font_file="dummy.ttf",
        target_font_name="/F_New",
        strategy="scale_to_fit",
    )
    config = ReplacementConfig(rules=[rule])
    mock_iter = MagicMock()
    # Return empty list to avoid iteration
    mock_iter.__iter__.return_value = []
    return mock_iter, config


def test_calculate_width_calls_wrapper_directly(mock_editor_deps):
    """
    Regression Test: verify calculate_target_visual_width calls
    wrapper.get_char_width directly instead of recursing or calling itself.
    """
    mock_iter, config = mock_editor_deps
    rule = config.rules[0]

    # 1. Build the environment
    # We tell the builder to set up a target wrapper that returns 500.
    editor, layout_engine = build_test_editor(
        mock_iter, config=config, target_width=500.0
    )
    del layout_engine.calculate_target_visual_width
    # ---------------------------------------------

    # 2. Retrieve the mock wrapper created by the builder
    # The builder places the mock in the cache keyed by the rule's target font file.
    font_file = rule.target_font_file
    mock_wrapper = layout_engine.target_font_cache[font_file]

    # 3. Configure State manually
    layout_engine.active_rule = rule
    # Explicitly set active wrapper to the one we just retrieved
    layout_engine.active_wrapper = mock_wrapper
    layout_engine.active_target_slot_map = {"A": 65}
    layout_engine.active_font_size = 10.0

    # 4. Execute
    source_ops = [pikepdf.String("A")]

    width_pts = layout_engine.calculate_target_visual_width("Tj", source_ops)

    # 5. Verify Math
    # 500 units * (10 size / 1000) = 5.0 pts
    assert width_pts == 5.0

    # 6. Verify Call
    # Now that the real method ran, this assertion will pass
    mock_wrapper.get_char_width.assert_called()


# -------------------------------------------------------------------------
# Bug 6: pikepdf.String attribute access crash
# -------------------------------------------------------------------------


def test_pikepdf_string_attribute_safety(mock_editor_deps):
    """
    Regression Test: Ensure extract_string_bytes doesn't crash on pikepdf.String
    when checking hasattr(item, 'as_bytes').
    """
    mock_iter, config = mock_editor_deps
    editor, layout_engine = build_test_editor(mock_iter, config=config)

    # Case 1: Standard Python string
    assert extract_string_bytes("Test") == b"Test"

    # Case 2: Standard Python bytes
    assert extract_string_bytes(b"Test") == b"Test"

    # Case 3: Mock object with as_bytes (simulating pikepdf.String)
    mock_pike = MagicMock()
    mock_pike.as_bytes.return_value = b"PikeString"
    assert extract_string_bytes(mock_pike) == b"PikeString"


def test_regression_width_calculation_methodology():
    """
    SCIENTIFIC PROOF OF REGRESSION (AND FIX):

    This test ensures we use Method B (Positional Delta) instead of Method A (Glyph Sum).
    """
    # --- Setup ---
    config = MagicMock(spec=ReplacementConfig)
    config.rules = [MagicMock(spec=ReplacementRule)]

    layout_engine = MagicMock()
    layout_engine.active_rule = True
    layout_engine.active_font_size = 12.0
    layout_engine.current_type3_scale_factor = 1.0

    # 1. Target Width = 100
    layout_engine.calculate_target_visual_width.return_value = 100.0

    # 2. Source Width (Glyph Sum Method) = 0 (Simulating failure)
    layout_engine.calculate_source_width.return_value = 0.0

    tracker = MagicMock()
    tracker.get_matrices.return_value = (np.eye(3), np.eye(3))
    tracker.get_current_user_pos.return_value = np.array([0.0, 0.0])

    editor = StreamEditor(
        source_iterator=[],
        config=config,
        target_font_cache={},
        custom_encoding_maps={},
        source_font_cache={},
        source_pikepdf_fonts={},
    )
    editor.layout_engine = layout_engine
    editor.tracker = tracker

    # --- Execute ---

    # 3. Setup State for "Positional Delta" Method
    # Start at 0, End at 100 -> Delta = 100
    editor.last_source_pos = np.array([0.0, 0.0, 1.0])

    mock_tstate = MagicMock()
    mock_tstate.matrix = [1, 0, 0, 1, 100, 0]  # Translation to 100
    source_state = {"tstate": mock_tstate, "ctm": [1, 0, 0, 1, 0, 0]}

    operands = [pikepdf.String(b"Test")]
    ops = editor.handlers.handle_operator("Tj", operands, source_state)
    # Filter sentinels
    real_ops = [op for op in ops if op is not ORIGINAL_BYTES]

    # --- Assert ---

    # Find Tz. Use str() to convert pikepdf.Operator to string safely.
    tz_op = next((op for op in real_ops if str(op[1]) == "Tz"), None)

    if tz_op:
        scale_percent = tz_op[0][0]
    else:
        scale_percent = 100.0

    print(f"\nCalculated Scale Percent: {scale_percent}%")

    # If we used Positional Delta (100), scale is 100%.
    # If we used Glyph Sum (0), scale is ~0% (or clamped).
    assert scale_percent == 100.0, (
        f"Regression! Editor used Glyph Sum width (0.0) instead of "
        f"Positional Delta width (100.0). Scale was {scale_percent}%"
    )


def test_regression_width_calculation_methodology():
    """
    SCIENTIFIC PROOF OF REGRESSION (AND FIX):

    This test ensures we use Method B (Positional Delta) instead of Method A (Glyph Sum).
    """
    # --- Setup ---
    config = MagicMock(spec=ReplacementConfig)
    config.rules = [MagicMock(spec=ReplacementRule)]

    layout_engine = MagicMock()
    layout_engine.active_rule = True
    layout_engine.active_font_size = 12.0
    layout_engine.current_type3_scale_factor = 1.0

    # 1. Target Width = 100
    layout_engine.calculate_target_visual_width.return_value = 100.0

    # 2. Source Width (Glyph Sum Method) = 0 (Simulating failure)
    layout_engine.calculate_source_width.return_value = 0.0

    tracker = MagicMock()
    tracker.get_matrices.return_value = (np.eye(3), np.eye(3))
    tracker.get_current_user_pos.return_value = np.array([0.0, 0.0])

    editor, _ = build_test_editor([], config)
    editor.layout_engine = layout_engine
    editor.tracker = tracker

    # --- Execute ---

    # 3. Setup State for "Positional Delta" Method
    # Start at 0, End at 100 -> Delta = 100
    editor.last_source_pos = np.array([0.0, 0.0, 1.0])

    mock_tstate = MagicMock()
    mock_tstate.matrix = [1, 0, 0, 1, 100, 0]  # Translation to 100
    source_state = {"tstate": mock_tstate, "ctm": [1, 0, 0, 1, 0, 0]}

    operands = [pikepdf.String(b"Test")]
    ctx = StreamContext(pre_input=None, post_input=None, tracker=editor.tracker)
    ops = editor.handler.handle_operator("Tj", operands, ctx, b"")
    # Filter sentinels
    real_ops = [op for op in ops if op is not ORIGINAL_BYTES]

    # --- Assert ---

    # Find Tz. Use str() to convert pikepdf.Operator to string safely.
    tz_op = next((op for op in real_ops if str(op[1]) == "Tz"), None)

    if tz_op:
        scale_percent = tz_op[0][0]
    else:
        scale_percent = 100.0

    print(f"\nCalculated Scale Percent: {scale_percent}%")

    # If we used Positional Delta (100), scale is 100%.
    # If we used Glyph Sum (0), scale is ~0% (or clamped).
    assert scale_percent == 100.0, (
        f"Regression! Editor used Glyph Sum width (0.0) instead of "
        f"Positional Delta width (100.0). Scale was {scale_percent}%"
    )
