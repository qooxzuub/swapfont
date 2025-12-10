from pathlib import Path

import pikepdf
import pytest

from swapfont.core import process_pdf
from swapfont.models import ReplacementConfig


def get_cached_font(cache_dir: Path) -> Path:
    """
    Retrieves a real TTF file. Downloads it if not present in the cache.
    """
    font_path = Path(__file__).parent.parent / "fixtures" / "Roboto-Regular.ttf"
    if not font_path.exists():
        pytest.fail(
            f"Test font not found at {font_path}. Please add it to tests/fixtures/"
        )
    return font_path


def test_full_pdf_processing_pipeline(tmp_path, replacement_config_data):
    """
    Tests the complete process_pdf function using real file I/O and real font parsing.
    """
    # --- Setup: Define Paths ---
    input_pdf_path = tmp_path / "input.pdf"
    output_pdf_path = tmp_path / "output.pdf"

    # Get a real, valid binary font file
    font_path = get_cached_font(tmp_path)

    # --- Setup: Create Physical Input PDF ---
    pdf = pikepdf.new()
    page = pdf.add_blank_page()

    # Content: /F1 10 Tf (A) Tj
    content_stream = b"/F1 10 Tf (A) Tj"
    page.Contents = pdf.make_stream(content_stream)

    # Add Resource Dictionary for /F1
    page.Resources = pikepdf.Dictionary(
        {
            "/Font": pikepdf.Dictionary(
                {
                    "/F1": pikepdf.Dictionary(
                        {
                            "/Type": pikepdf.Name("/Font"),
                            "/Subtype": pikepdf.Name("/Type1"),
                            "/BaseFont": pikepdf.Name("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    pdf.save(input_pdf_path)
    pdf.close()

    # --- Configuration ---
    if "rules" in replacement_config_data:
        rule = replacement_config_data["rules"][0]
        rule["target_font_file"] = str(font_path)

        # Use string key "0x41" (Hex for 65) to satisfy Pydantic
        rule["encoding_map"] = {"0x41": "A"}
        rule["preserve_unmapped"] = True
        rule["strategy"] = "hybrid"  # WAS "scale_to_fit"

    config = ReplacementConfig(**replacement_config_data)

    # --- Execution ---
    process_pdf(input_pdf_path, output_pdf_path, config)

    # --- Verification ---
    assert output_pdf_path.exists()

    with pikepdf.open(output_pdf_path) as out_pdf:
        out_page = out_pdf.pages[0]

        # 1. Verify the new font was embedded (check for Subtype /TrueType)
        fonts = out_page.Resources.Font
        # Filter for any font that is NOT the original /F1
        new_fonts = [f for name, f in fonts.items() if name != "/F1"]

        assert len(new_fonts) > 0, "No new font was embedded into the PDF"
        assert new_fonts[0].Subtype == "/TrueType"

        # 2. Verify Content Stream Rewrite
        raw_stream = out_page.Contents.read_bytes()
        # The stream should no longer purely rely on /F1 if replacement occurred.
        # Ideally, we check that the *new* font name (e.g. /F1_0 or /F_New) is in the stream.
        # Since the name is auto-generated, we can just check it's NOT just the old stream.
        assert raw_stream != content_stream
