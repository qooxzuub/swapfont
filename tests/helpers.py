# tests/test_pdf_helpers.py
from io import BytesIO
from pathlib import Path

import pikepdf
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def _generate_pdf(text: str = "", output_path: Path | None = None) -> BytesIO:
    """
    Generate a PDF with optional text content.
    If `output_path` is provided, writes the PDF to disk.
    Returns a BytesIO containing the PDF data.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    if text:
        c.setFont("Helvetica", 12)
        c.drawString(100, 750, text)
    c.showPage()
    c.save()

    buffer.seek(0)
    if output_path:
        with open(output_path, "wb") as f:
            f.write(buffer.getbuffer())
    return buffer


def create_pdf_file_with_text(tmp_path: Path, text: str = "") -> Path:
    """
    Create a minimal on-disk PDF file with optional text content.
    Returns the path to the PDF.
    """
    pdf_path = tmp_path / "test.pdf"
    _generate_pdf(text, output_path=pdf_path)
    return pdf_path


def create_pdf_object_with_text(text: str = "") -> pikepdf.Pdf:
    """
    Create a minimal in-memory PDF object with optional text content.
    Returns the PDF object.
    """
    buffer = _generate_pdf(text)
    pdf = pikepdf.open(buffer)
    return pdf
