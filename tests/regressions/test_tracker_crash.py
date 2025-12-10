# tests/integration/test_real_tracker_crash.py
import pytest
from pdfbeaver.editor import StreamEditor

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.handlers import create_font_replacer_handler
from swapfont.models import (
    ReplacementConfig,
)
from swapfont.tracker import (
    FontedStateTracker,
)


def test_inline_image_crash_on_real_tracker():
    """
    Demonstrates that passing 'EI' (End Inline Image) to a REAL FontedStateTracker
    crashes if we don't handle it in the editor.

    This test verifies the fix in `_update_output_state`.
    """
    # 1. Setup a Real Editor (no Mocks for the tracker)
    # We pass empty caches/config as we don't need font replacement, just stream parsing.
    config = ReplacementConfig(rules=[])
    tracker = FontedStateTracker({}, {})
    layout = LayoutEngine(config, {}, {}, {}, {})
    handler = create_font_replacer_handler(layout)
    editor = StreamEditor([], handler, tracker)

    # 2. Feed it the dangerous "EI" operator
    editor.source_iter = [
        # This will trigger _update_output_state("EI", [])
        {"operator": "EI", "operands": [], "state": {}, "raw_bytes": b"EI"},
    ]

    # 3. Process
    # WITHOUT the fix, this raises TypeError: do_EI() missing argument...
    # WITH the fix, it returns successfully.
    try:
        editor.process()
    except TypeError as e:
        pytest.fail(f"Tracker crashed on EI operator: {e}")
