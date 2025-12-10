# tests/test_wizard.py
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

# Import the wizard function
from swapfont.wizard import wizard


@pytest.fixture
def mock_dependencies():
    """
    Mocks the heavy dependencies (inspect_pdf, process_pdf).
    """
    with (
        patch("swapfont.wizard.inspect_pdf") as mock_inspect,
        patch("swapfont.wizard.process_pdf") as mock_process,
    ):
        yield mock_inspect, mock_process


def test_wizard_no_rules(mock_dependencies, tmp_path):
    mock_inspect, mock_process = mock_dependencies

    # FIX: Use SimpleNamespace/Mock instead of real FontData.
    # This decouples the test from the FontData constructor signature
    # while satisfying the wizard's access to .base_font and .used_char_codes.
    mock_font = SimpleNamespace(base_font="Helvetica", used_char_codes={65})

    mock_inspect.return_value = {"/F1": mock_font}

    input_pdf = tmp_path / "dummy.pdf"
    input_pdf.touch()

    runner = CliRunner()
    result = runner.invoke(wizard, [str(input_pdf)], input="n\n")

    assert result.exit_code == 0
    assert "Found font: /F1" in result.output
    assert "No rules selected" in result.output
    mock_process.assert_not_called()


def test_wizard_successful_flow(mock_dependencies, tmp_path):
    mock_inspect, mock_process = mock_dependencies

    # FIX: Use SimpleNamespace/Mock
    mock_font = SimpleNamespace(base_font="Times-Roman", used_char_codes={12, 65})

    mock_inspect.return_value = {"/F1": mock_font}

    input_pdf = tmp_path / "input.pdf"
    input_pdf.touch()

    replacement_font = tmp_path / "replacement.ttf"
    replacement_font.touch()

    runner = CliRunner()
    input_sequence = f"y\n{replacement_font}\ny\n"

    result = runner.invoke(wizard, [str(input_pdf)], input=input_sequence)

    assert result.exit_code == 0
    assert "Processing..." in result.output

    assert mock_process.call_count == 1
    call_args = mock_process.call_args
    config = call_args[0][2]

    assert len(config.rules) == 1
    rule = config.rules[0]
    assert rule.source_font_name == "/F1"
    assert rule.target_font_file == str(replacement_font)
    assert rule.encoding_map.get("0x0c") == "fi"


def test_wizard_default_output_path(mock_dependencies, tmp_path):
    mock_inspect, mock_process = mock_dependencies
    mock_inspect.return_value = {}

    input_pdf = tmp_path / "myfile.pdf"
    input_pdf.touch()

    runner = CliRunner()
    runner.invoke(wizard, [str(input_pdf)], input="")

    # Test with font found to trigger save message check logic
    mock_font = SimpleNamespace(base_font="A", used_char_codes={65})
    mock_inspect.return_value = {"/F1": mock_font}

    dummy_ttf = tmp_path / "font.ttf"
    dummy_ttf.touch()

    result = runner.invoke(wizard, [str(input_pdf)], input=f"y\n{dummy_ttf}\n")

    expected_output = input_pdf.parent / "myfile_new.pdf"
    assert str(expected_output) in result.output


@pytest.fixture
def mock_deps():
    with (
        patch("swapfont.wizard.inspect_pdf") as mock_insp,
        patch("swapfont.wizard.process_pdf") as mock_proc,
    ):
        yield mock_insp, mock_proc


def test_wizard_no_interactive_flag(mock_deps, tmp_path):
    """Verifies --no-interactive-replace automatically declines replacement."""
    mock_insp, mock_proc = mock_deps

    # Setup font found
    mock_font = SimpleNamespace(font_type="Type1", used_char_codes={65})
    mock_insp.return_value = {"/F1": mock_font}

    input_pdf = tmp_path / "test.pdf"
    input_pdf.touch()

    runner = CliRunner()
    # Run with --no-interactive-replace
    result = runner.invoke(wizard, [str(input_pdf), "--no-interactive-replace"])

    assert result.exit_code == 0
    # Should say skipping because it couldn't ask
    assert "Skipping /F1" in result.output
    mock_proc.assert_not_called()


def test_wizard_auto_yes_prompts_for_path(mock_deps, tmp_path):
    """
    Verifies --yes flag automatically accepts replacement but prompts
    for path if not provided in CLI args.
    """
    mock_insp, mock_proc = mock_deps
    mock_font = SimpleNamespace(font_type="Type1", used_char_codes={65})
    mock_insp.return_value = {"/F1": mock_font}

    input_pdf = tmp_path / "test.pdf"
    input_pdf.touch()
    ttf_path = tmp_path / "arial.ttf"
    ttf_path.touch()

    runner = CliRunner()
    # Provide the path via input because --yes accepts the logic but needs the file
    result = runner.invoke(wizard, [str(input_pdf), "--yes"], input=f"{ttf_path}\n")

    assert result.exit_code == 0
    assert "Processing..." in result.output
    mock_proc.assert_called_once()


def test_wizard_ligature_flags(mock_deps, tmp_path):
    """Verifies --no-ligatures and --accept-ligatures logic."""
    mock_insp, mock_proc = mock_deps

    # Font USES code 12 ('fi' ligature)
    mock_font = SimpleNamespace(font_type="Type1", used_char_codes={12, 65})
    mock_insp.return_value = {"/F1": mock_font}

    input_pdf = tmp_path / "test.pdf"
    input_pdf.touch()
    ttf_path = tmp_path / "arial.ttf"
    ttf_path.touch()

    runner = CliRunner()

    # Case 1: --no-ligatures (Should NOT map code 12)
    cli_args = [
        str(input_pdf),
        "--replace-font",
        "/F1",
        str(ttf_path),
        "--no-ligatures",
        "--yes",  # Avoid prompt for path
    ]
    result = runner.invoke(wizard, cli_args)
    config = mock_proc.call_args[0][2]
    # Ensure map is empty or doesn't contain ligature
    assert "0x0c" not in config.rules[0].encoding_map

    # Case 2: --accept-ligatures (Should map code 12 WITHOUT prompt)
    cli_args_accept = [
        str(input_pdf),
        "--replace-font",
        "/F1",
        str(ttf_path),
        "--accept-ligatures",
        "--yes",
    ]
    result = runner.invoke(wizard, cli_args_accept)
    config = mock_proc.call_args[0][2]
    assert config.rules[0].encoding_map["0x0c"] == "fi"
