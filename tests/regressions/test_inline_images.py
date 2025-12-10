import pytest
from pdfbeaver.editor import StreamEditor

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.handlers import create_font_replacer_handler
from swapfont.models import (
    ReplacementConfig,
    ReplacementRule,
)
from swapfont.tracker import (
    FontedStateTracker,
)

# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def minimal_editor_tracker():
    """Returns a StreamEditor initialized with empty dependencies, and its tracker"""
    config = ReplacementConfig(rules=[])
    tracker = FontedStateTracker({}, {})
    layout = LayoutEngine(config, {}, {}, {}, {})
    handler = create_font_replacer_handler(layout)
    return StreamEditor([], handler, tracker), layout


# -------------------------------------------------------------------------
# Test Block 2: Font Key Normalization (The "Font Not Found" Fix)
# -------------------------------------------------------------------------


def test_font_key_normalization(minimal_editor_tracker):
    """
    Verifies that set_active_font handles both "/F1" and "F1".
    """
    config = ReplacementConfig(
        rules=[
            ReplacementRule(
                source_font_name="/F1",
                target_font_file="dummy.ttf",
                target_font_name="/NewFont",
            )
        ]
    )

    # We test the LayoutEngine behavior via the editor's engine instance
    editor, engine = minimal_editor_tracker
    engine.config = config

    # Case 1: Config has "/F1".

    # Case 2: Input is raw string "F1" (no slash)
    engine.set_active_font("F1", 10.0)
    # Check if rule matched
    assert engine.active_rule is not None
    assert engine.active_rule.source_font_name == "/F1"

    # Case 3: Input is raw string "/F1" (with slash)
    engine.set_active_font("/F1", 10.0)
    assert engine.active_rule is not None
    assert engine.active_rule.source_font_name == "/F1"

    # Case 4: Non-matching font
    engine.set_active_font("/Arial", 10.0)
    assert engine.active_rule is None
