from unittest.mock import MagicMock

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.models import ReplacementConfig, ReplacementRule


def test_type3_scale_factor_reset():
    """
    Regression Test:
    Ensures that the Type 3 scaling factor (e.g. 0.5) is reset to 1.0
    when switching to a subsequent standard font.

    Use Case:
    1. Processing a Type 3 font sets 'current_type3_scale_factor' to 0.5.
    2. Processing the next font (Standard) should reset this to 1.0.
    3. If buggy, the Standard font would be squashed to 0.5 size.
    """
    # 1. Setup Configuration with two rules
    rule_type3 = ReplacementRule(
        source_font_name="/Type3Font",
        source_base_font="T3",
        target_font_file="Target.ttf",
        target_font_name="Target",
        encoding_map={},
    )
    rule_standard = ReplacementRule(
        source_font_name="/StandardFont",
        source_base_font="Std",
        target_font_file="Target.ttf",
        target_font_name="Target",
        encoding_map={},
    )
    config = ReplacementConfig(rules=[rule_type3, rule_standard])

    # 2. Mock Source Fonts
    # Type 3 Font: Defines a 50% scaling factor
    mock_t3_source = MagicMock()
    mock_t3_source.is_type3 = True
    mock_t3_source.type3_design_height = 0.5

    # Standard Font: Normal Type 1/TrueType (No special attributes)
    mock_std_source = MagicMock()
    mock_std_source.is_type3 = False

    source_cache = {"/Type3Font": mock_t3_source, "/StandardFont": mock_std_source}

    # 3. Initialize Engine
    engine = LayoutEngine(
        config=config,
        target_font_cache={"Target.ttf": MagicMock()},
        custom_encoding_maps={},
        source_font_cache=source_cache,
        source_pikepdf_fonts={},
    )

    # 4. Step 1: Activate Type 3 Font
    # Input Size: 10.0 -> Expected Output: 5.0 (10 * 0.5)
    name1, size1 = engine.set_active_font("/Type3Font", 10.0)

    assert size1 == 5.0, "Type 3 font should be scaled by 0.5"
    assert (
        engine.current_type3_scale_factor == 0.5
    ), "Engine state should track Type 3 scale"

    # 5. Step 2: Activate Standard Font
    # Input Size: 10.0 -> Expected Output: 10.0 (Reset to 1.0)
    # IF REGRESSION EXISTS: This will return 5.0
    name2, size2 = engine.set_active_font("/StandardFont", 10.0)

    assert size2 == 10.0, (
        f"Regression Detected: Standard font size expected 10.0, got {size2}. "
        "The Type 3 scale factor was not reset!"
    )
    assert (
        engine.current_type3_scale_factor == 1.0
    ), "Engine state should be reset to 1.0"
