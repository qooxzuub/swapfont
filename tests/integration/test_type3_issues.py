# tests/test_type3_integration.py


import pikepdf
import pytest

from swapfont.models import FontData

# --- Assumed Fixtures ---
# Assuming you have a fixture that returns the path to your test file.
# If not, this needs to be implemented in your conftest.py or test file.


# --- New Fixture ---
@pytest.fixture(scope="session")
def type3_pdf_doc(type3_pdf_path):
    """
    Loads the real-world type3.pdf file for integration testing.
    """
    try:
        pdf = pikepdf.open(type3_pdf_path)
    except Exception as e:
        pytest.skip(f"Could not open or access type3.pdf at path {type3_pdf_path}: {e}")

    yield pdf
    pdf.close()


def test_type3_font_metrics_extraction(type3_pdf_doc):
    """
    Tests successful extraction of design metrics and widths from real-world Type 3 fonts.
    This ensures the replacement routine receives non-zero size information.
    """
    page = type3_pdf_doc.pages[0]
    fonts = page.resources.get("/Font")

    if not fonts:
        pytest.skip("Test PDF 'type3.pdf' contains no font resources on page 1.")

    found_type3 = False

    # Iterate through all font dictionaries on the first page
    for font_name, font_dict in fonts.items():
        if font_dict.get("/Subtype") == pikepdf.Name("/Type3"):
            found_type3 = True

            # Initialize FontData, triggering metric extraction
            fd = FontData(font_name, font_dict)

            # Assertions for successful extraction
            assert (
                fd.type3_design_width > 0.0
            ), f"Type 3 font {font_name} failed to extract positive design width."
            assert (
                fd.type3_design_height > 0.0
            ), f"Type 3 font {font_name} failed to extract positive design height."
            assert (
                len(fd.widths) > 0
            ), f"Type 3 font {font_name} failed to extract any character widths."

    assert found_type3, "Test PDF 'type3.pdf' did not contain any Type 3 fonts to test."
