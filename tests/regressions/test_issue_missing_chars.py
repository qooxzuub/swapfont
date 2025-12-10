from unittest.mock import MagicMock

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.models import ReplacementConfig, ReplacementRule


def test_repro_rule_encoding_map_ignored():
    """
    Reproduction Case:
    User defines 'encoding_map' in the JSON rule, but LayoutEngine
    currently ignores it, causing characters to be unmapped (or mapped to defaults).
    """
    # 1. Setup a Rule with an explicit encoding map
    # We want to map 'A' (65) to slot 10.
    rule = ReplacementRule(
        source_font_name="/F1",
        source_base_font="SourceFont",
        target_font_file="Target.ttf",
        target_font_name="/F_New",
        # This is where the user puts the map in the JSON
        encoding_map={"A": 10},
    )

    config = ReplacementConfig(rules=[rule])

    # 2. Initialize Engine
    engine = LayoutEngine(
        config=config,
        target_font_cache={"Target.ttf": MagicMock()},
        custom_encoding_maps={},
        source_font_cache={},
        source_pikepdf_fonts={},
    )

    # 3. Activate the font
    engine.set_active_font("/F1", 12.0)

    # 4. Attempt to rewrite "A"
    # Expected: "A" -> \x0a (10)
    # Actual (Bug): "A" -> "A" (because map is ignored)
    result = engine.rewrite_text_operands("Tj", ["A"])

    # pikepdf.String behaves like a str. We inspect the string value.
    # The map sends "A" to 10, which corresponds to the string "\n".
    result_val = str(result[0])

    # This assertion will FAIL if the engine ignores rule.encoding_map
    assert (
        result_val == "\n"
    ), f"Expected '\\n' (mapped), but got {result_val!r} (unmapped)"
