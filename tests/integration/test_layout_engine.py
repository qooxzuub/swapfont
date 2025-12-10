from unittest.mock import MagicMock

import pytest

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.models import ReplacementConfig


@pytest.fixture
def engine():
    config = MagicMock(spec=ReplacementConfig)
    config.rules = []
    engine = LayoutEngine(config, {}, {}, {}, {})
    engine.current_pdf_font_name = "MockFont"
    return engine


def test_calculate_source_width_basic(engine):
    """Verifies source width calculation using mocked pdfminer state."""
    mock_font = MagicMock()
    # FIX: side_effect ensures it returns a float, not a Mock object
    mock_font.get_width.side_effect = lambda x: 600.0

    tstate = MagicMock()
    tstate.font = mock_font
    tstate.fontsize = 12.0
    tstate.charspace = 0
    tstate.wordspace = 0
    tstate.scaling = 100
    tstate.matrix = [1, 0, 0, 1, 0, 0]
    engine.source_pikepdf_fonts = {
        "/MockFont": {
            "/Widths": [600] * 256,
            "/FirstChar": 0,
            "/LastChar": 255,
        }
    }

    state = {"tstate": tstate, "ctm": [1, 0, 0, 1, 0, 0]}
    operands = [b"A"]
    width = engine.calculate_source_width_fallback("Tj", operands, state)

    # Width = (600/1000) * 12.0 = 0.6 * 12 = 7.2
    assert width == pytest.approx(7.2)


def test_calculate_source_width_tj_complex(engine):
    """Verifies source width calculation with TJ array and spacing."""
    mock_font = MagicMock()
    mock_font.get_width.side_effect = lambda x: 500.0

    tstate = MagicMock()
    tstate.font = mock_font
    tstate.fontsize = 10.0
    tstate.charspace = 0
    tstate.wordspace = 0
    tstate.scaling = 100
    tstate.matrix = [1, 0, 0, 1, 0, 0]
    engine.source_pikepdf_fonts = {
        "/MockFont": {
            "/Widths": [500] * 256,
            "/FirstChar": 0,
            "/LastChar": 255,
        }
    }

    state = {"tstate": tstate, "ctm": [1, 0, 0, 1, 0, 0]}

    # "A" (500) - 100 units (move left) - "B" (500)
    operands = [[b"A", 100, b"B"]]

    width = engine.calculate_source_width_fallback("TJ", operands, state)

    # Glyphs: (500/1000 + 500/1000) * 10 = 10.0
    # Spacing: -(100/1000) * 10 = -1.0
    # Total: 9.0
    assert width == pytest.approx(9.0)
