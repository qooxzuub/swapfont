import os
import sys
from pathlib import Path

# Add the project root (the directory containing 'src') to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "...")))


from unittest.mock import MagicMock

import pikepdf
import pytest
from pdfbeaver.editor import StreamEditor

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.handlers import create_font_replacer_handler
from swapfont.models import (
    FontData,
    ReplacementConfig,
    ReplacementRule,
    StrategyOptions,
)
from swapfont.tracker import FontedStateTracker


def build_test_editor(iterator, config=None, source_width=1000.0, target_width=500.0):
    """
    Builder function that hides the complexity of Dependency Injection.
    Returns a configured StreamEditor and its LayoutEngine (for assertion checking).
    """
    # 1. Defaults
    if not config:
        config = ReplacementConfig(
            rules=[
                ReplacementRule(
                    source_font_name="/F1",
                    target_font_name="F_New",
                    strategy="scale_to_fit",
                    target_font_file="new.ttf",
                )
            ]
        )

    # 2. Mocks
    mock_metrics = MagicMock()
    mock_metrics.get_char_width.return_value = target_width

    mock_source = MagicMock()
    mock_source.get_width.return_value = source_width
    source_cache = {"/F1": mock_source}

    loaded_fonts = {"dummy.ttf": mock_metrics}
    encoding_maps = {"dummy.ttf": {65: "A"}}

    # 3. Engines
    tracker = FontedStateTracker(loaded_fonts, encoding_maps)

    layout = LayoutEngine(
        config, loaded_fonts, encoding_maps, source_cache, source_pikepdf_fonts={}
    )

    layout.active_wrapper = MagicMock()
    # 4. Critical Logic Mocks (The "Boilerplate" we want to hide)
    layout.set_active_font = MagicMock(return_value=("F_New", 10.0))
    layout.rewrite_text_operands = MagicMock(side_effect=lambda op, ops: ops)
    # We mock this to ensure math isolation, using the requested target_width
    target_pts = target_width * (10.0 / 1000.0)  # Convert units to pts at 10pt size
    layout.calculate_target_visual_width = MagicMock(return_value=target_pts)
    dummy_rule = MagicMock()
    dummy_rule.strategy_options = {"min_scale": 50.0, "max_scale": 200.0}
    layout.active_rule = MagicMock()
    layout.active_rule.strategy_options = {}  # Empty dict is valid

    # 5. Assembly
    handler = create_font_replacer_handler(layout)
    editor = StreamEditor(iterator, handler, tracker, optimizer=None)

    return editor, layout


@pytest.fixture
def mock_font_metrics():
    """
    Provides a mock FontWrapper object with a fixed width
    so math tests are deterministic.
    """
    mock = MagicMock()
    # Set a default width (e.g. 500 units) so comparisons don't crash
    mock.get_string_width.return_value = 500.0
    return mock


@pytest.fixture
def mock_source_cache():
    """
    Provides a dictionary mimicking the source_font_cache
    required by StreamEditor.
    """
    mock_fd = MagicMock(spec=FontData)
    # Set a default source width (e.g. 1000 units)
    mock_fd.get_width.return_value = 1000.0
    mock_fd.is_type3 = False
    mock_fd.type3_design_height = 0
    return {"/F1": mock_fd}


@pytest.fixture
def create_pdf_context():
    """
    Fixture that returns a factory function.
    The factory creates a minimal pikepdf Page with the given content stream.
    Keeps the PDF document alive to prevent 'Object inside closed PDF' errors.
    """
    created_pdfs = []

    def _create(content_stream_bytes: bytes):
        # Create a new PDF in memory
        pdf = pikepdf.new()
        created_pdfs.append(pdf)

        # Add a blank page
        page = pdf.add_blank_page(page_size=(100, 100))

        # Set the content stream
        page.Contents = pdf.make_stream(content_stream_bytes)

        return page

    yield _create

    for pdf in created_pdfs:
        pdf.close()


@pytest.fixture
def strict_replacement_rule():
    """
    Returns a ReplacementRule configured for STRICT scaling (No hybrid spacing).
    Useful for verifying exact Tz (Horizontal Scaling) calculations.
    """
    options = StrategyOptions(max_scale=1000.0, min_scale=1.0)

    return ReplacementRule(
        source_font_name="/F1",
        target_font_file="dummy.ttf",
        target_font_name="/F_New",
        strategy="scale_to_fit",
        hybrid_max_char_spacing=0.0,  # FORCE PURE SCALING
        preserve_unmapped=False,
        encoding_map={"0x41": "B"},
        width_overrides={"0x41": 1000.0},
        strategy_options=options,
    )


@pytest.fixture
def simple_replacement_rule():
    """
    Returns a standard ReplacementRule with default settings (Hybrid Mode).
    Used for general integration tests.
    """
    return ReplacementRule(
        source_font_name="/F1",
        target_font_file="dummy.ttf",
        target_font_name="/F_New",
        strategy="scale_to_fit",
        # Default hybrid settings allow some character spacing
        hybrid_max_char_spacing=0.5,
        preserve_unmapped=False,
        encoding_map={"0x41": "B"},
        width_overrides={"0x41": 1000.0},
    )


@pytest.fixture
def mock_font_embedding(mocker):
    """
    Mocks the font_embedding module to prevent real TTF loading in integration tests.
    Targets the module path directly to avoid import path issues.
    """
    return mocker.patch("swapfont.font_embedding")


@pytest.fixture
def replacement_config_data():
    """
    Provides a raw dictionary structure for creating a replacement config file.
    Used by integration tests that load config from disk.
    """
    return {
        "rules": [
            {
                "source_font_name": "/F1",
                "target_font_file": "dummy.ttf",
                "target_font_name": "/F_New",
                "strategy": "scale_to_fit",
                "preserve_unmapped": False,
                "encoding_map": {"0x41": "B"},
                "width_overrides": {"0x41": 1000.0},
            }
        ]
    }


@pytest.fixture(scope="module")
def temp_pdf_doc():
    """Fixture to create a minimal PDF object for stream/dict creation."""
    pdf = pikepdf.Pdf.new()
    yield pdf
    pdf.close()


def create_mock_stream(content: str, pdf_document: pikepdf.Pdf) -> pikepdf.Stream:
    # This is the new, fixed implementation
    content_bytes = content.encode("latin1")
    return pdf_document.make_stream(content_bytes)


@pytest.fixture(scope="session")
def type3_pdf_path(tmp_path_factory):
    """
    Placeholder: Should return the Path object pointing to type3.pdf.
    (Implement necessary logic to copy or locate the file here.)
    """
    # For a real project, this would copy type3.pdf from a static location
    # to a temporary directory for testing.
    # Since I cannot access your filesystem, I will rely on an existing
    # path fixture if you have one, or assume a working path replacement.

    # --- Assuming a path exists via another fixture or setup for now ---
    return Path(__file__).parent / "fixtures" / "type3.pdf"
