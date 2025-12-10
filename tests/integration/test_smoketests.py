import shutil
import subprocess
import sys
from pathlib import Path

import pikepdf
import pytest

# Define paths relative to the project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
PDF_DIR = PROJECT_ROOT / "pdfs"
RULES_DIR = PROJECT_ROOT / "rules"

# PERSISTENT OUTPUT DIRECTORY
ARTIFACTS_DIR = PROJECT_ROOT / "test_artifacts"


@pytest.fixture(scope="session", autouse=True)
def setup_artifacts_dir():
    """
    Ensures the 'test_artifacts' directory exists.
    """
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    return ARTIFACTS_DIR


def run_command(cmd_list):
    """
    Helper to run a command and verify it exits with 0.
    Explicitly prints stdout/stderr so pytest can capture or display them.
    """
    # capture_output=True grabs the streams into result.stdout/stderr
    # They do NOT go to the real terminal automatically.
    result = subprocess.run(cmd_list, capture_output=True, text=True, cwd=PROJECT_ROOT)

    # Manually print the captured output to the Python streams.
    # This allows pytest to control visibility:
    #   pytest       -> Hidden (captured)
    #   pytest -s    -> Visible (passed through)
    #   pytest -rP   -> Visible in report for Passed tests
    if result.stdout:
        print(f"\n[{cmd_list[0]} STDOUT]:\n{result.stdout}")

    if result.stderr:
        print(f"\n[{cmd_list[0]} STDERR]:\n{result.stderr}", file=sys.stderr)

    if result.returncode != 0:
        pytest.fail(
            f"Command failed with {result.returncode}.\nSee stderr above for details."
        )

    return result


@pytest.mark.skipif(not (PDF_DIR / "5.pdf").exists(), reason="Test PDFs not found")
def test_e2e_type3_replacement():
    """
    Runs: swapfont pdfs/5.pdf rules/94b.json
    ARTIFACT: test_artifacts/output_type3.pdf
    """
    input_pdf = PDF_DIR / "5.pdf"
    rule_file = RULES_DIR / "94b.json"
    output_pdf = ARTIFACTS_DIR / "output_type3.pdf"

    cmd = [
        "swapfont",
        "run",
        str(input_pdf),
        str(rule_file),
        "--output",
        str(output_pdf),
    ]

    run_command(cmd)

    assert output_pdf.exists()

    # Structural Verification: Check if /F_New font was added
    with pikepdf.open(output_pdf) as pdf:
        font_found = False
        for page in pdf.pages:
            if "/Resources" in page and "/Font" in page["/Resources"]:
                fonts = page["/Resources"]["/Font"]
                for font_name in fonts.keys():
                    if "/foobarfont" == str(font_name):
                        font_found = True
                        break
            if font_found:
                parsed_contents = pikepdf.parse_content_stream(page)
                found_foobarfont_in_page = False
                for operands, command in parsed_contents:
                    if str(command) == "Tf" and "foobarfont" in str(operands):
                        found_foobarfont_in_page = True
                        fontsize = float(operands[1])
                        assert 9 < fontsize < 12

        assert (
            font_found
        ), "The output PDF does not contain the expected replaced font embedded"

        assert (
            found_foobarfont_in_page
        ), "The output PDF does not contain the expected replaced font in its page"


@pytest.mark.skipif(
    not (PDF_DIR / "Worksheet1.pdf").exists(), reason="Test PDFs not found"
)
def test_e2e_type1_replacement():
    """
    Runs: swapfont pdfs/Worksheet1.pdf rules/ws.json
    ARTIFACT: test_artifacts/output_ws.pdf
    """
    input_pdf = PDF_DIR / "Worksheet1.pdf"
    rule_file = RULES_DIR / "ws.json"
    output_pdf = ARTIFACTS_DIR / "output_ws.pdf"

    cmd = [
        "swapfont",
        "run",
        str(input_pdf),
        str(rule_file),
        "--output",
        str(output_pdf),
    ]

    run_command(cmd)

    assert output_pdf.exists()

    with pikepdf.open(output_pdf) as pdf:
        assert len(pdf.pages) > 0


def test_wizard_script_execution():
    """
    Runs the custom 'swapfont-wizard-test' script.
    """
    cmd_name = "swapfont-wizard-test"

    if not shutil.which(cmd_name):
        pytest.skip(f"{cmd_name} not found in PATH")

    run_command([cmd_name])
