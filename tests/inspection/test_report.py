# tests/test_inspector.py
from pathlib import Path
from unittest.mock import MagicMock, patch

from swapfont.inspection.analyzer import (
    _handle_font_operator,
    _handle_text_operator,
    _process_text_token,
    inspect_pdf,
    scan_for_text_content,
)
from swapfont.models import FontData

from ..helpers import create_pdf_file_with_text, create_pdf_object_with_text


def test_handle_font_operator_adds_point_size():
    font_data_map = {"F1": FontData("F1", {})}
    font_name = _handle_font_operator(["F1", 12], font_data_map)
    assert font_name == "F1"
    assert 12 in font_data_map["F1"].point_sizes


def test_handle_font_operator_invalid_operands_returns_none():
    assert _handle_font_operator([], {}) is None


def test_process_text_token_adds_char_codes():
    fd = FontData("F1", {})
    _process_text_token("A", fd, page_num=1)
    code = ord("A")
    assert code in fd.used_char_codes
    assert fd.char_pages[code] == {1}


def test_handle_text_operator_skips_invalid_font():
    font_data_map = {}
    # Should not raise
    _handle_text_operator(["A"], font_data_map, "F1", 1)


def test_scan_for_text_content_calls_scan_page(monkeypatch):
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_pdf.pages = [mock_page]
    font_data_map = {}

    called = {}

    def fake_scan_page(page, font_data_map_inner, page_num):
        called["yes"] = True

    monkeypatch.setattr(
        "swapfont.inspection.analyzer._scan_page_for_text_content",
        fake_scan_page,
    )
    scan_for_text_content(mock_pdf, font_data_map)
    assert "yes" in called


@patch("swapfont.inspection.analyzer.pikepdf.open")
def test_inspect_pdf_opens_pdf(mock_open, monkeypatch):
    fake_pdf = MagicMock()
    fake_page = MagicMock()
    fake_pdf.pages = [fake_page]
    mock_open.return_value = fake_pdf

    monkeypatch.setattr(
        "swapfont.inspection.analyzer.scan_for_text_content",
        lambda pdf, fd_map: None,
    )

    result = inspect_pdf(Path("fake.pdf"))
    assert isinstance(result, dict)


##################################################
# extra tests


def test_inspect_pdf_empty_pdf(tmp_path: Path):
    pdf_path = create_pdf_file_with_text(tmp_path)
    # Should run without exception even if no text/fonts present
    result = inspect_pdf(pdf_path)
    assert isinstance(result, dict)


def test_inspect_pdf_with_text(tmp_path: Path):
    pdf_path = create_pdf_file_with_text(tmp_path, text="Hello World")
    result = inspect_pdf(pdf_path)
    assert isinstance(result, dict)


def test_scan_for_text_content_handles_empty_pdf():
    pdf = create_pdf_object_with_text()
    fd_map = {}
    # Should not raise even with empty content
    scan_for_text_content(pdf, fd_map)
    assert fd_map == {}


def test_scan_for_text_content_with_text(tmp_path: Path):
    pdf = create_pdf_object_with_text(text="abc")
    fd_map = {}
    scan_for_text_content(pdf, fd_map)
    # Text extraction populates fd_map; exact content depends on PDF internals
    assert isinstance(fd_map, dict)


##################################################

from swapfont.inspection.diagnostic import find_font_object


def test_find_font_object(tmp_path):
    pdf_path = create_pdf_file_with_text(tmp_path, text="ABC")
    import pikepdf

    pdf = pikepdf.open(str(pdf_path))

    # Add a fake font resource
    page = pdf.pages[0]
    from pikepdf import Dictionary, Name

    page.Resources = Dictionary(
        {"/Font": Dictionary({"/F1": Dictionary({"/BaseFont": Name("/FakeFont")})})}
    )

    font_obj = find_font_object(pdf, "/F1")
    assert font_obj is not None
    assert font_obj["/BaseFont"] == Name("/FakeFont")

    # Test missing font returns None
    assert find_font_object(pdf, "NONEXISTENT") is None

    pdf.close()


from pikepdf import Pdf

from swapfont.inspection.diagnostic import DiagnosticPDFGenerator


def test_diagnostic_pdf_generator_methods(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    from ..helpers import create_pdf_file_with_text

    create_pdf_file_with_text(tmp_path, text="ABC")

    src_pdf = Pdf.open(str(pdf_path))
    out_pdf = Pdf.new()

    gen = DiagnosticPDFGenerator(src_pdf, out_pdf)

    # Basic page creation
    gen.start_new_page()
    assert gen.current_page is not None

    # Drawing operations
    gen.set_font("/Helvetica", 12)
    gen.draw_text("Hello World", 100, 100)
    gen.draw_hex_sample("41", 150, 150)
    gen.draw_line(0, 0, 100, 100)

    # Space handling triggers new page
    gen.y_cursor = 10
    gen.ensure_space(50)
    assert gen.current_page is not None

    # finalize flushes last page
    gen.finalize()

    # draw_header, draw_summary_table, draw_detailed_table
    fd = FontData("F1", {})
    fd.used_char_codes = {65: 500}
    fd.char_names = {65: "A"}
    fd.char_pages = {65: {1}}
    fd.pages_used = {1}
    fd.point_sizes = {12}
    fd.is_embedded = True
    fd.font_type = "Type1"
    fd.base_font = "Base"
    gen.draw_header(
        {
            "code": 0,
            "hex": 0,
            "width": 0,
            "src": 0,
            "helv": 0,
            "win": 0,
            "mac": 0,
            "name": 0,
            "pages": 0,
        }
    )
    gen.draw_summary_table([65], "F1", fd)
    gen.draw_detailed_table(
        "F1",
        fd,
        {
            "code": 0,
            "hex": 0,
            "width": 0,
            "src": 0,
            "helv": 0,
            "win": 0,
            "mac": 0,
            "name": 0,
            "pages": 0,
        },
    )
    gen.draw_font_section("F1", fd)

    # Cleanup
    src_pdf.close()


from swapfont.inspection.diagnostic import generate_diagnostic_pdf


def test_generate_diagnostic_pdf(tmp_path):
    from ..helpers import create_pdf_file_with_text

    pdf_path = create_pdf_file_with_text(tmp_path, text="ABC")

    # Minimal FontData to pass
    fd = FontData("F1", {})
    fd.used_char_codes = {65: 500}
    fd.char_names = {65: "A"}
    fd.char_pages = {65: {1}}
    fd.pages_used = {1}
    fd.point_sizes = {12}
    fd.is_embedded = True
    fd.font_type = "Type1"
    fd.base_font = "Base"

    font_map = {"F1": fd}

    generate_diagnostic_pdf(pdf_path, font_map)

    # Verify output file exists
    diag_pdf_path = tmp_path / f"{pdf_path.stem}_diagnostic.pdf"
    assert diag_pdf_path.exists()


# --- Merged from test_diagnostic_math.py ---

import pytest


# Mock the Diagnostic class to isolate draw_hex_sample
class MockDiagnostic(DiagnosticPDFGenerator):
    def __init__(self):
        # Minimal init to support draw_hex_sample
        self.content_stream = []
        self.active_size = 12.0  # Target size = 12pt
        self.y_cursor = 100.0
        self.active_font = "/F1"


@pytest.fixture
def diag_tool():
    return MockDiagnostic()


def get_tf_operator(content_stream):
    """
    Helper to parse the last appended stream line and find '... Tf'.
    Example line: '/F1 0.6000 Tf <A1> Tj ET'
    Returns: 0.6000 (float)
    """
    last_op = content_stream[-1]
    parts = last_op.split()
    if "Tf" in parts:
        idx = parts.index("Tf")
        return float(parts[idx - 1])
    return None


class TestDiagnosticMath:

    def test_render_standard_font(self, diag_tool):
        """
        Case A: Standard Type 1.
        Matrix: 0.001. Design Height: N/A (Standard).
        Target: 12pt.
        Expected Scale: 12.0 (Standard behavior)
        """
        font_data = MagicMock(spec=FontData)
        font_data.font_matrix = [0.001, 0, 0, 0.001, 0, 0]
        font_data.type3_design_height = 0.0
        font_data.font_bbox = [0, -200, 1000, 800]

        diag_tool.draw_hex_sample("A", 50, font_data=font_data)

        scale = get_tf_operator(diag_tool.content_stream)
        assert scale == 12.0

    def test_render_type3_correct_scaling(self, diag_tool):
        """
        Case B: The 'Fixed' Type 3.
        Matrix: 1.0 (Identity).
        Design Height: 20.0 (Parsed from d1).
        Target: 12pt.
        Expected Scale: 12 / 20 = 0.6
        """
        font_data = MagicMock(spec=FontData)
        font_data.font_matrix = [1.0, 0, 0, 1.0, 0, 0]
        font_data.type3_design_height = 20.0  # <--- The critical value

        diag_tool.draw_hex_sample("A", 50, font_data=font_data)

        scale = get_tf_operator(diag_tool.content_stream)
        assert scale == pytest.approx(0.6, rel=1e-3)

    def test_render_type3_fallback_sanity_check(self, diag_tool):
        """
        Case C: Lazy BBox failure.
        Matrix: 1.0.
        Design Height: 1.0 (Suspiciously small, likely normalized).
        Target: 12pt.
        Expected Scale: Fallback to 1000-unit logic.
        12 / 1000 = 0.012
        """
        font_data = MagicMock(spec=FontData)
        font_data.font_matrix = [1.0, 0, 0, 1.0, 0, 0]
        font_data.type3_design_height = 1.0  # Suspiciously small

        diag_tool.draw_hex_sample("A", 50, font_data=font_data)

        scale = get_tf_operator(diag_tool.content_stream)
        assert scale == pytest.approx(0.012, rel=1e-3)

    def test_orientation_flip(self, diag_tool):
        """
        Case D: Inverted Matrix (common in Type 3).
        Matrix Y: -1.0.
        We check if the Tm operator includes a negative Y scale (-1.0).
        """
        font_data = MagicMock(spec=FontData)
        font_data.font_matrix = [1.0, 0, 0, -1.0, 0, 0]
        font_data.type3_design_height = 20.0

        diag_tool.draw_hex_sample("A", 50, font_data=font_data)

        # Check the Tm operator (the line before Tf)
        # Expected: "1 0 0 -1.00 50.00 100.00 Tm"
        tm_op = diag_tool.content_stream[-2]
        assert "-1.00" in tm_op
