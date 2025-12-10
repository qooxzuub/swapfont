from unittest.mock import MagicMock

import pytest

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.models import ReplacementConfig, ReplacementRule


def test_replacement_rule_parsing_scaling_param():
    """
    Verifies that the replacement rule model correctly parses the
    'fontsize_scaling_percentage' field, defaulting to 100.0 if missing.
    """
    # Case 1: Default (Missing field)
    data_default = {"source_font_name": "/F1", "target_font_file": "arial.ttf"}
    rule = ReplacementRule(**data_default)
    assert rule.fontsize_scaling_percentage == 100.0

    # Case 2: Explicit value (e.g. 95%)
    data_custom = {
        "source_font_name": "/F1",
        "target_font_file": "arial.ttf",
        "fontsize_scaling_percentage": 95.0,
    }
    rule = ReplacementRule(**data_custom)
    assert rule.fontsize_scaling_percentage == 95.0

    # Case 3: JSON-like float input
    data_json = {
        "source_font_name": "/F1",
        "target_font_file": "arial.ttf",
        "fontsize_scaling_percentage": 120.5,
    }
    rule = ReplacementRule(**data_json)
    assert rule.fontsize_scaling_percentage == 120.5


def test_layout_engine_applies_scaling_percentage():
    """
    Verifies that LayoutEngine.set_active_font applies the user-defined
    scaling percentage to the calculated font size.
    """
    # 1. Setup Rules
    rule_normal = ReplacementRule(
        source_font_name="/Normal",
        target_font_file="dummy.ttf",
        fontsize_scaling_percentage=100.0,
    )
    rule_shrink = ReplacementRule(
        source_font_name="/Shrink",
        target_font_file="dummy.ttf",
        fontsize_scaling_percentage=50.0,  # Should halve the size
    )
    rule_grow = ReplacementRule(
        source_font_name="/Grow",
        target_font_file="dummy.ttf",
        fontsize_scaling_percentage=200.0,  # Should double the size
    )

    config = ReplacementConfig(rules=[rule_normal, rule_shrink, rule_grow])

    # 2. Setup Mocks
    mock_wrapper = MagicMock()
    target_cache = {"dummy.ttf": mock_wrapper}

    # Engine instance
    engine = LayoutEngine(
        config=config,
        target_font_cache=target_cache,
        custom_encoding_maps={},
        source_font_cache={},
        source_pikepdf_fonts={},
    )

    # 3. Test Normal (100%)
    # Input: 12pt -> Output: 12pt
    name, size = engine.set_active_font("/Normal", 12.0)
    assert size == 12.0

    # 4. Test Shrink (50%)
    # Input: 12pt -> Output: 6pt
    name, size = engine.set_active_font("/Shrink", 12.0)
    assert size == 6.0

    # 5. Test Grow (200%)
    # Input: 10pt -> Output: 20pt
    name, size = engine.set_active_font("/Grow", 10.0)
    assert size == 20.0


def test_layout_engine_scaling_combines_with_type3_scaling():
    """
    Verifies that the manual scaling percentage stacks multiplicatively
    with the automatic Type 3 design height scaling.
    """
    # Rule requests 90% scaling
    rule = ReplacementRule(
        source_font_name="/Type3Font",
        target_font_file="dummy.ttf",
        fontsize_scaling_percentage=90.0,
    )
    config = ReplacementConfig(rules=[rule])

    # Setup Type 3 Source Data
    # Simulate a Type 3 font that is effectively 0.5 height of a normal font
    mock_source_data = MagicMock()
    mock_source_data.is_type3 = True
    mock_source_data.type3_design_height = 0.5

    source_cache = {"/Type3Font": mock_source_data}
    target_cache = {"dummy.ttf": MagicMock()}

    engine = LayoutEngine(
        config=config,
        target_font_cache=target_cache,
        custom_encoding_maps={},
        source_font_cache=source_cache,
        source_pikepdf_fonts={},
    )

    # Calculation:
    # Input Size: 20.0
    # Type 3 Scale: 0.5  -> Intermediate: 10.0
    # User Scale: 90% (0.9) -> Final: 9.0

    name, size = engine.set_active_font("/Type3Font", 20.0)

    assert size == 9.0
