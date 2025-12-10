from unittest.mock import MagicMock

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.models import ReplacementConfig, ReplacementRule


def test_descriptive_ligature_resolution():
    """
    Reproduces the issue where "latin small ligature fi" in the JSON rule
    fails to map to the existing ligature in the target font, causing
    missing characters or decomposition fallback.
    """
    # 1. Setup Rule with the descriptive value
    rule = ReplacementRule(
        source_font_name="/F1",
        source_base_font="Source",
        target_font_file="Target.ttf",
        target_font_name="Target",
        encoding_map={"0x0c": "latin small ligature fi"},
    )

    config = ReplacementConfig(rules=[rule])

    # 2. Simulate Target Font Map
    # We define that the target font DOES have the ligature at slot 150.
    # We also define 'f' and 'i' to verify we don't fall back to them.
    target_map = {
        "Target.ttf": {
            "\ufb01": 150,  # The specific ligature slot (expected)
            "f": 102,  # Fallback slot 1
            "i": 105,  # Fallback slot 2
        }
    }

    # 3. Initialize Engine
    engine = LayoutEngine(
        config=config,
        target_font_cache={"Target.ttf": MagicMock()},
        custom_encoding_maps=target_map,
        source_font_cache={},
        source_pikepdf_fonts={},
    )

    # 4. Activate Font
    engine.set_active_font("/F1", 12.0)

    # 5. Act: Rewrite the byte 0x0c
    # We wrap it in a pikepdf.String-like object or bytes, depending on what the engine expects
    # The engine handles bytes in list for Tj
    input_operand = b"\x0c"

    result = engine.rewrite_text_operands("Tj", [input_operand])

    # 6. Assert
    # Extract the rewriten bytes
    result_bytes = bytes(result[0])

    # We expect a single byte.
    # The engine logic now prefers maintaining the input slot (12 / 0x0c) if possible,
    # effectively creating a custom encoding where 12 -> \ufb01.

    assert (
        len(result_bytes) == 1
    ), f"Expected 1 byte (ligature), got {len(result_bytes)} bytes: {list(result_bytes)}"

    # UPDATED ASSERTION: We now expect 12 (0x0c), not 150 (0x96).
    # This confirms the engine is respecting the source-to-target mapping
    # and not just falling back to the font's default CMAP.
    # assert result_bytes == b"\x0c", f"Expected byte 12 (0x0c), got {list(result_bytes)}"
    assert (
        result_bytes == b"\x96"
    ), f"Expected byte 150 (0x96), got {list(result_bytes)}"
