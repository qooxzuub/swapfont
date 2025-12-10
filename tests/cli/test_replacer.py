import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from swapfont.cli import main  # your Click command


@pytest.fixture
def tmp_files(tmp_path):
    """Set up temporary input PDF and config JSON."""
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_text("fake PDF content")  # dummy content

    config_json = tmp_path / "config.json"
    config_json.write_text(json.dumps({"rules": []}))

    output_pdf = tmp_path / "output.pdf"
    return input_pdf, config_json, output_pdf


def test_cli_loads_config_and_process_pdf(tmp_files):
    input_pdf, config_json, output_pdf = tmp_files

    runner = CliRunner()

    with (
        patch("swapfont.cli.process_pdf") as mock_process,
        patch("swapfont.cli.ReplacementConfig") as mock_config,
    ):
        mock_config.return_value = MagicMock()

        # Simulate CLI invocation
        result = runner.invoke(
            main,
            ["run", str(input_pdf), str(config_json), "-o", str(output_pdf)],
        )

        # CLI ran successfully
        assert result.exit_code == 0

        # ReplacementConfig was instantiated from JSON
        mock_config.assert_called_once()

        # process_pdf was called with expected arguments
        mock_process.assert_called_once()


def test_cli_default_output(tmp_files):
    input_pdf, config_json, output_pdf = tmp_files

    # The CLI should auto-generate output path if -o is omitted
    runner = CliRunner()

    with (
        patch("swapfont.cli.process_pdf") as mock_process,
        patch("swapfont.cli.ReplacementConfig") as mock_config,
    ):
        mock_config.return_value = MagicMock()

        result = runner.invoke(main, ["run", str(input_pdf), str(config_json)])

        assert result.exit_code == 0

        # process_pdf should be called with output path auto-generated
        args, kwargs = mock_process.call_args
        auto_output = input_pdf.with_name(f"{input_pdf.stem}_replaced.pdf")
        assert args[1] == auto_output
