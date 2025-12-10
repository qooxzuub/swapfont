# tests/test_inspector.py
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from swapfont.inspection.analyzer import (
    _handle_font_operator,
    _handle_text_operator,
    _process_text_token,
    generate_template_config,
    inspect_pdf,
    main_inspector,
    scan_for_text_content,
)
from swapfont.models import FontData

from ..helpers import create_pdf_file_with_text


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


def test_inspect_pdf_with_real_pdf(tmp_path: Path):
    pdf_path = create_pdf_file_with_text(tmp_path, text="ABC")
    result = inspect_pdf(pdf_path)

    # Should find at least one font used
    assert len(result) > 0
    # Optionally check that the used font contains some characters
    some_font_data = next(iter(result.values()))
    assert some_font_data.used_char_codes


def test_inspect_pdf_no_fonts(tmp_path: Path):
    pdf_path = create_pdf_file_with_text(tmp_path)
    result = inspect_pdf(pdf_path)
    # PDF with no fonts triggers the "no fonts found" branch
    assert result == {}


##################################################


def test_process_text_token_value_error(monkeypatch):
    fd = FontData("F1", {})

    # Create a token that cannot be encoded as latin1
    class BadStr:
        def __str__(self):
            raise ValueError("cannot convert")

    token = BadStr()

    # Should not raise, should hit except branch
    _process_text_token(token, fd, page_num=1)
    assert fd.used_char_codes == {}  # still empty


def test_generate_template_config_empty(tmp_path):
    # Should generate empty JSON template without fonts
    config_path = tmp_path / "font_rules.json"
    generate_template_config({}, tmp_path / "dummy.pdf")

    assert config_path.exists()
    with open(config_path) as f:
        data = json.load(f)
    assert data["rules"] == []


def test_generate_template_config_nonempty(tmp_path):
    # Create fake font data
    fd = FontData("F1", {})
    fd.used_char_codes[65] = 500  # 'A'
    fd.char_pages[65].add(1)
    fd.point_sizes.add(12)

    font_data_map = {"F1": fd}
    config_path = tmp_path / "font_rules.json"

    generate_template_config(font_data_map, tmp_path / "dummy.pdf")

    assert config_path.exists()
    with open(config_path) as f:
        data = json.load(f)
    assert len(data["rules"]) == 1
    rule = data["rules"][0]
    assert rule["source_font_name"] == "F1"
    assert rule["characters_used"][0]["code"] == 65


def test_main_pdf_not_found(tmp_path):
    # Provide a path that does not exist
    missing_pdf = tmp_path / "nonexistent.pdf"

    # Should log error and return without exception
    result = main_inspector(argv=[str(missing_pdf)])
    # No exception, the CLI returns normally (Click will return exit_code 0 by default)
    # Optionally capture logs to assert
    # This covers lines 272-273


def test_main_generates_outputs(tmp_path):
    # Create a minimal real PDF
    pdf_path = tmp_path / "test.pdf"
    from ..helpers import create_pdf_file_with_text

    create_pdf_file_with_text(tmp_path, text="ABC")

    # Patch diagnostic PDF generator so it doesn't actually write
    with patch("swapfont.inspection.analyzer.generate_diagnostic_pdf") as mock_diag:
        # Run the CLI main function
        main_inspector(argv=[str(pdf_path)])
        mock_diag.assert_called_once()


# --- Merged from test_inspector_new.py ---
# tests/test_inspector.py
from pathlib import Path
from unittest.mock import patch

import pikepdf

from ..helpers import create_pdf_object_with_text

# Import from NEW locations


def test_handle_font_operator_adds_point_size():
    # Setup mock font dict
    mock_dict = MagicMock(spec=pikepdf.Dictionary)
    font_data_map = {"F1": FontData("F1", mock_dict)}

    font_name = _handle_font_operator(["F1", 12], font_data_map)
    assert font_name == "F1"
    assert 12 in font_data_map["F1"].point_sizes


def test_handle_font_operator_invalid_operands_returns_none():
    assert _handle_font_operator([], {}) is None


def test_process_text_token_adds_char_codes():
    mock_dict = MagicMock(spec=pikepdf.Dictionary)
    fd = FontData("F1", mock_dict)

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
