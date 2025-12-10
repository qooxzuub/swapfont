from click.testing import CliRunner

from swapfont.inspector_cli import main


def test_inspector_cli_runs(tmp_path):
    # Create a fake file (it doesn't need to be a valid PDF)
    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_text("doesn't matter")

    runner = CliRunner()

    # Run CLI with the fake file and --debug
    result = runner.invoke(main, [str(fake_pdf), "--debug"])

    # We don't care what main_inspector does; we just check that
    # the CLI runs and Click handles the arguments correctly
    # (Click will catch the file existence)
    assert result.exit_code != 2  # 2 is Click usage error
    assert "Usage" not in result.output  # no usage message printed

    # Optionally, check that debug flag triggers some log message
    # if your CLI prints something when debug=True
    # assert "DEBUG" in result.output
