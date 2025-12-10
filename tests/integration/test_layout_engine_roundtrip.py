import math
from unittest.mock import MagicMock

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from swapfont.handlers import calculate_scale_percent
from swapfont.models import ReplacementConfig

from ..conftest import build_test_editor


@given(
    st.floats(min_value=1.0, max_value=1000.0),  # Source Width
    st.floats(min_value=1.0, max_value=1000.0),  # Target Width
)
def test_layout_scaling_invariant(source_width, target_width):
    """
    Invariant: The calculated scale percentage, when applied to the target width,
    should roughly equal the source width.
    """
    config = ReplacementConfig(rules=[])

    # Use StreamEditor as the entry point for logic testing
    editor, layout_engine = build_test_editor([], config=config)

    # Mock internal calculation methods
    layout_engine.calculate_target_visual_width = MagicMock(return_value=target_width)
    layout_engine.calculate_source_width_fallback = MagicMock(return_value=source_width)

    # Mock position extraction to simulate source width distance
    editor._extract_source_pos = MagicMock(
        side_effect=[
            np.array([0.0, 0.0, 1.0]),
            np.array([source_width, 0.0, 1.0]),  # Euclidean distance = source_width
        ]
    )
    editor.last_source_pos = np.array([0.0, 0.0, 1.0])

    scale = calculate_scale_percent(
        "Tj", [], {}, {}, editor.last_source_pos, layout_engine
    )

    # If scale hit the clamping limits (50% or 200%), invariant won't hold
    if scale == 50.0 or scale == 200.0:
        return

    effective_width = target_width * (scale / 100.0)
    # Use loose tolerance because of float precision and engine internals
    assert math.isclose(effective_width, source_width, rel_tol=0.01)
