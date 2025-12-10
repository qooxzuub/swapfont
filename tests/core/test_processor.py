from unittest.mock import MagicMock

import pikepdf
import pytest
from pdfbeaver.editor import StreamEditor

from swapfont.core import process_pdf
from swapfont.font_utils import FontWrapper
from swapfont.handlers import create_font_replacer_handler
from swapfont.models import ReplacementConfig, ReplacementRule, StrategyOptions

from ..conftest import build_test_editor


def _create_mock_state(fontsize=10.0, tx=0, ty=0):
    tstate = MagicMock()
    tstate.fontsize = fontsize
    tstate.matrix = [1, 0, 0, 1, tx, ty]
    tstate.char_spacing = 0
    tstate.word_spacing = 0
    tstate.scaling = 100
    tstate.leading = 0
    tstate.rise = 0

    # Mock the pdfminer font object (used if LayoutEngine relies on tstate.font)
    mock_font = MagicMock()
    # Return 1000 (1/1000 units)
    mock_font.get_width.return_value = 1000.0
    tstate.font = mock_font

    return {"tstate": tstate, "ctm": [1, 0, 0, 1, 0, 0]}


@pytest.fixture
def mock_font_metrics():
    metrics = MagicMock()
    metrics.get_char_width.return_value = 1000.0  # 1 em
    return metrics


@pytest.fixture
def strict_replacement_rule():
    return ReplacementRule(
        source_font_name="/F1",
        target_font_file="dummy.ttf",
        target_font_name="/F_New",
        strategy="scale_to_fit",
        strategy_options=StrategyOptions(
            min_scale=1.0, max_scale=1000.0  # Allow massive scaling
        ),
    )


@pytest.fixture
def mock_source_cache():
    return {}


def make_editor_params(config, target_cache, source_cache, source_pikepdf_fonts):
    # We need to import the real classes since we aren't using StreamEditor to build them

    from swapfont.engines.layout_engine import LayoutEngine
    from swapfont.tracker import (
        FontedStateTracker,
    )

    # Create REAL engines with the test config
    layout_engine = LayoutEngine(
        config,
        target_cache,
        custom_encoding_maps={},
        source_font_cache=source_cache,
        source_pikepdf_fonts=source_pikepdf_fonts,
    )

    # Create REAL tracker (mocking underlying device calls if needed, but safe here)
    tracker = FontedStateTracker(target_cache, {})

    # Create REAL handler linked to real engines
    handler = create_font_replacer_handler(layout_engine)

    return handler, tracker


def test_text_replacement_scaling_real_objects():
    """
    Verifies that the StreamEditor correctly injects Tz (scaling) commands
    using real LayoutEngine logic.
    """
    rule = ReplacementRule(
        source_font_name="/F1",
        target_font_file="target.ttf",
        target_font_name="F_New",
        strategy="scale_to_fit",
        strategy_options=StrategyOptions(max_scale=1000.0),
    )
    config = ReplacementConfig(rules=[rule])

    # Target Cache
    mock_target_wrapper = MagicMock()
    # Target char width is 500 units (half of source)
    mock_target_wrapper.get_char_width.return_value = 500
    target_cache = {"target.ttf": mock_target_wrapper}

    # Source Cache
    mock_source_data = MagicMock()
    mock_source_data.is_type3 = False
    source_cache = {"/F1": mock_source_data}

    # FIX: Populate source_pikepdf_fonts
    # The fallback calculation looks up the font here to get widths.
    # We provide a dictionary acting like a PDF Font object.
    mock_pikepdf_font = {
        "/Type": "/Font",
        "/Subtype": "/TrueType",
        "/FirstChar": 0,
        "/LastChar": 255,
        # Widths array: Make 'A' (65) have width 1000
        "/Widths": [1000] * 256,
        "/FontMatrix": [0.001, 0, 0, 0.001, 0, 0],  # Standard 1/1000 scaling
    }
    source_pikepdf_fonts = {"/F1": mock_pikepdf_font}

    # Mock Iterator Steps
    # We keep tx=0 so StreamEditor uses the fallback calculation (which uses the fonts above)
    step_tf = {
        "operator": "Tf",
        "operands": [pikepdf.Name("/F1"), 10],
        "state": _create_mock_state(10),
    }
    step_tj = {
        "operator": "Tj",
        "operands": [pikepdf.String("A")],
        "state": _create_mock_state(10),
    }

    # Mock Iterator Steps (Keep this mocked)
    step_tf = {
        "operator": "Tf",
        "operands": [pikepdf.Name("/F1"), 10],
        "state": _create_mock_state(10),
        "raw_bytes": b"/F1 10 Tf",
    }
    step_tj = {
        "operator": "Tj",
        "operands": [pikepdf.String("A")],
        "state": _create_mock_state(10),
        "raw_bytes": b"(A) Tj",
    }

    mock_iterator = MagicMock()
    mock_iterator.__iter__.return_value = [step_tf, step_tj]

    handler, tracker = make_editor_params(
        config, target_cache, source_cache, source_pikepdf_fonts
    )
    # Initialize Editor with injected dependencies
    editor = StreamEditor(
        source_iterator=mock_iterator, handler=handler, tracker=tracker, optimizer=None
    )

    # Execute
    output_stream = editor.process()

    # Assert
    # Source Width: 1000 units * 10pt = 10.0
    # Target Width: 500 units * 10pt = 5.0
    # Expected Scale: 200%
    assert b"200 Tz" in output_stream


def test_text_replacement_logic(
    mock_font_metrics, strict_replacement_rule, mock_source_cache
):
    """
    Verifies the replacement math using a STRICT scaling rule.
    Source Width = 10.0. Target Width = 5.0.
    Expected Scaling (Tz) = 200%.
    """
    mock_font_data = MagicMock()
    mock_font_data.get_width.return_value = 1000.0
    mock_font_data.type3_design_height = 0
    mock_font_data.is_type3 = False

    mock_source_cache["/F1"] = mock_font_data
    mock_source_cache["F1"] = mock_font_data

    loaded_fonts = {"dummy.ttf": mock_font_metrics}
    encoding_maps = {"dummy.ttf": {65: "A"}}
    config = ReplacementConfig(rules=[strict_replacement_rule])

    step_tf = {
        "operator": "Tf",
        "operands": [pikepdf.Name("/F1"), 10],
        "state": _create_mock_state(10, tx=0),
    }
    step_tj = {
        "operator": "Tj",
        "operands": [pikepdf.String("A")],
        # Advance the cursor to 10.0 ( Start 0 + Width 10 )
        "state": _create_mock_state(10, tx=10),
    }

    mock_iterator = MagicMock()
    mock_iterator.__iter__.return_value = [step_tf, step_tj]

    # Imports needed for manual setup
    from pdfbeaver.editor import StreamEditor

    from swapfont.engines.layout_engine import LayoutEngine
    from swapfont.tracker import (
        FontedStateTracker,
    )

    # 2. Instantiate engines explicitly to keep references
    layout_engine = LayoutEngine(
        config,
        target_font_cache=loaded_fonts,
        custom_encoding_maps=encoding_maps,
        source_font_cache=mock_source_cache,
        source_pikepdf_fonts={},
    )
    tracker = FontedStateTracker(loaded_fonts, encoding_maps)

    # 3. Create Handler
    handler = create_font_replacer_handler(layout_engine)

    # 4. Configure Mocks directly on the engine instance
    # We need to ensure the target width calculation returns 5.0 (half of source 10.0)
    # Target char width 500 units * 10pt = 5.0 pts
    mock_font_metrics.get_char_width.return_value = 500

    def side_effect_set_active_font(name, size):
        # 1. Activate the rule
        layout_engine.active_rule = strict_replacement_rule

        # 2. Update critical internal state needed for calculate_target_visual_width
        layout_engine.active_font_size = size
        layout_engine.active_wrapper = mock_font_metrics  # The target font wrapper

        return ("F_New", 10.0)

    # Apply mock to the variable we hold
    layout_engine.set_active_font = MagicMock(side_effect=side_effect_set_active_font)
    layout_engine.rewrite_text_operands = MagicMock(side_effect=lambda op, ops: ops)

    # 5. Create Editor with injected dependencies
    editor = StreamEditor(
        source_iterator=mock_iterator, handler=handler, tracker=tracker, optimizer=None
    )

    output_stream = editor.process()

    # Check for Tz scaling: 10 source / 5 target = 2 = 200%
    assert b"200 Tz" in output_stream


def test_text_array_kerning_preservation():
    # 1. Data Setup (The "What")
    step_tf = {
        "operator": "Tf",
        "operands": [pikepdf.Name("/F1"), 10],
        "state": _create_mock_state(10, tx=0),
        "raw_bytes": b"/F1 10 Tf",
    }
    # Simulate cursor moving 20 units (Source Width)
    tj_array = [pikepdf.String("A"), -50, pikepdf.String("A")]
    step_tj = {
        "operator": "TJ",
        "operands": [pikepdf.Array(tj_array)],
        "state": _create_mock_state(10, tx=20),
        "raw_bytes": b"[(A)-50(A)]TJ",
    }

    mock_iter = MagicMock()
    mock_iter.__iter__.return_value = [step_tf, step_tj]

    # 2. Build (The "How" is hidden)
    # We specify: Source is effectively 20 wide (via state), Target logic expects 10 wide.
    # Note: We configure the builder to return a layout engine that thinks target is 10.0 pts.
    editor, layout_engine = build_test_editor(
        mock_iter, source_width=1000, target_width=1000
    )
    # Override the specific calculation mock for this precise math test
    layout_engine.calculate_target_visual_width.return_value = 10.0

    # 3. Execute
    output = editor.process()

    # 4. Assert (Source 20 / Target 10 = 200%)
    assert b"200 Tz" in output


# def test_text_array_kerning_preservation(
#     mock_font_metrics, strict_replacement_rule, mock_source_cache
# ):
#     """
#     Verifies that kerning arrays are preserved and scaling is applied correctly.
#     """
#     # 1. Setup Source Font Data
#     mock_font_data = MagicMock()
#     mock_font_data.get_width.return_value = 1000.0
#     mock_font_data.type3_design_height = 0
#     mock_font_data.is_type3 = False
#     mock_source_cache["/F1"] = mock_font_data

#     # 2. Setup Config & Caches
#     loaded_fonts = {"dummy.ttf": mock_font_metrics}
#     encoding_maps = {"dummy.ttf": {65: "A"}}
#     config = ReplacementConfig(rules=[strict_replacement_rule])

#     # 3. Define Iterator Steps
#     # Step A: Set Font
#     step_tf = {
#         "operator": "Tf",
#         "operands": [pikepdf.Name("/F1"), 10],
#         "state": _create_mock_state(10, tx=0),
#     }

#     # Step B: Show Text (Array with Kerning)
#     # CRITICAL FIX: The state 'tx' must advance to represent the source width.
#     # We simulate a source width of 20 units (Start 0 -> End 20).
#     tj_array = [pikepdf.String("A"), -50, pikepdf.String("A")]
#     step_tj = {
#         "operator": "TJ",
#         "operands": [pikepdf.Array(tj_array)],
#         "state": _create_mock_state(10, tx=20),
#     }

#     mock_iterator = MagicMock()
#     mock_iterator.__iter__.return_value = [step_tf, step_tj]

#     # 4. Initialize Engines & Dependencies
#     from swapfont.engines.layout_engine import LayoutEngine
#     from swapfont.tracker import FontedStateTracker
#     from swapfont.handlers import create_font_replacer_handler
#     from pdfbeaver.editor import StreamEditor

#     # Create engines manually to hold references for mocking
#     layout = LayoutEngine(
#         config,
#         target_font_cache=loaded_fonts,
#         custom_encoding_maps=encoding_maps,
#         source_font_cache=mock_source_cache,
#         source_pikepdf_fonts={},
#     )
#     tracker = FontedStateTracker(loaded_fonts, encoding_maps)

#     # 5. Configure Layout Engine Mocks
#     # Mock A: set_active_font must return (Name, Size) to prevent handler crash
#     layout.set_active_font = MagicMock(return_value=("F_New", 10.0))

#     # Mock B: Ensure active_rule is truthy so handler proceeds
#     layout.active_rule = strict_replacement_rule

#     # Mock C: Rewrite operands (pass-through)
#     layout.rewrite_text_operands = MagicMock(side_effect=lambda op, ops: ops)

#     # Mock D: Force Target Width to 10.0
#     # Math: Source Width (20.0) / Target Width (10.0) = 2.0 (200% Scale)
#     layout.calculate_target_visual_width = MagicMock(return_value=10.0)

#     # 6. Create Handler & Editor
#     handler = create_font_replacer_handler(layout, tracker)

#     editor = StreamEditor(
#         source_iterator=mock_iterator,
#         handler=handler,
#         tracker=tracker,
#         optimizer=None
#     )

#     # 7. Execute
#     output_stream = editor.process()

#     # 8. Verify
#     # We expect '200 Tz' because 20.0 / 10.0 * 100 = 200.0
#     assert b"200 Tz" in output_stream


# --- Merged from test_core_edge_cases.py ---


@pytest.fixture
def mock_core_deps(mocker):
    """
    Mocks external dependencies used in core.py to isolate logic.
    """
    mocker.patch("swapfont.core.embed_truetype_font", return_value=pikepdf.Dictionary())

    # Mock FontWrapper and its cleanup
    mock_wrapper = MagicMock(spec=FontWrapper)
    mock_wrapper.cmap = {65: "A", 12: "fi"}
    mock_wrapper.ttfont = MagicMock()
    mock_wrapper.ttfont.close = MagicMock()

    mocker.patch("swapfont.core.FontWrapper", return_value=mock_wrapper)

    return mocker


def test_process_pdf_page_corruption_handling(mock_core_deps, tmp_path, mocker):
    """
    Tests exception handling during stream processing.
    Verifies that if one page fails, the loop continues.
    """
    # Setup Input PDF with 2 pages
    input_pdf_path = tmp_path / "input.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.add_blank_page()
    pdf.save(input_pdf_path)
    pdf.close()

    # --- FIX: Mock modify_page instead of StreamEditor ---
    # core.py calls `modify_page` directly. We can mock it to raise errors.
    mock_modify = mocker.patch("swapfont.core.modify_page")

    # Configure side effects:
    # 1. Page 1 -> Raises PdfError ("Corrupt Stream")
    # 2. Page 2 -> Succeeds (returns None)
    mock_modify.side_effect = [pikepdf.PdfError("Corrupt Stream"), None]

    config = ReplacementConfig(rules=[])

    # Execution
    # This will run the loop in core.process_pdf
    # It calls mock_modify for each page
    process_pdf(input_pdf_path, tmp_path / "output.pdf", config)

    # Verification
    # It should have tried to process both pages
    assert mock_modify.call_count == 2


# --- Merged from test_core_gaps.py ---

from pikepdf import Dictionary, Name

from swapfont.core import _patch_font_encoding, _update_page_resources


def test_patch_font_encoding_generates_correct_structures():
    """
    Verifies that _patch_font_encoding correctly creates the PDF /Encoding dictionary
    and populates the /Differences array based on the provided metrics and map.
    """
    # Setup
    font_obj = Dictionary()
    needed_chars = ["f", "i"]

    # Map chars to slots (e.g., 'f' -> 100, 'i' -> 101)
    encoding_map = {"f": 100, "i": 101}

    # Mock FontWrapper metrics (cmap: ord(char) -> glyph_name)
    mock_metrics = MagicMock()
    mock_metrics.cmap = {ord("f"): "f_glyph", ord("i"): "i_glyph"}

    # Execute
    _patch_font_encoding(font_obj, needed_chars, encoding_map, mock_metrics)

    # Assert
    assert "/Encoding" in font_obj
    enc_dict = font_obj["/Encoding"]
    assert enc_dict["/Type"] == "/Encoding"
    assert enc_dict["/BaseEncoding"] == "/WinAnsiEncoding"

    # Verify Differences Array: [100, /f_glyph, 101, /i_glyph]
    diffs = enc_dict["/Differences"]
    # Note: Order depends on sorted(needed_chars), so 'f' comes before 'i'
    assert diffs[0] == 100
    assert diffs[1] == Name("/f_glyph")
    assert diffs[2] == 101
    assert diffs[3] == Name("/i_glyph")


def test_update_page_resources_handles_missing_dicts():
    """
    Verifies that _update_page_resources robustly creates /Resources and /Font
    dictionaries if they are missing from the page.
    """
    # Setup Page with NO resources
    pike_page = MagicMock()
    # Simulate attribute access for Resources (pikepdf uses attribute access or item access)
    pike_page.Resources = Dictionary()

    # Ensure it's empty
    if "/Font" in pike_page.Resources:
        del pike_page.Resources["/Font"]

    # Setup Config
    rule = ReplacementRule(
        source_font_name="/Old",
        target_font_file="dummy.ttf",
        target_font_name="/NewFont",
    )
    config = ReplacementConfig(rules=[rule])

    # Setup Embedded Objects
    mock_font_obj = Dictionary({"/Type": "/Font"})
    embedded_objects = {"dummy.ttf": mock_font_obj}

    # Execute
    _update_page_resources(pike_page, config, embedded_objects)

    # Assert
    assert "/Font" in pike_page.Resources
    assert "/NewFont" in pike_page.Resources["/Font"]
    assert pike_page.Resources["/Font"]["/NewFont"] == mock_font_obj
