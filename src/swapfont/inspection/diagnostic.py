# src/swapfont/inspection/diagnostic.py
"""
Module for generating diagnostic PDFs that visualize font usage and metrics.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

import pikepdf

# Models are still needed
from swapfont.models import FontData
from swapfont.utils.pdf_resources import find_resource_recursive

logger = logging.getLogger(__name__)

# ... (Constants remain the same) ...
PAGE_WIDTH = 842
PAGE_HEIGHT = 595
MARGIN = 30
FONT_SIZE = 9
LINE_HEIGHT = 13

SUM_CELL_W = 18
SUM_ROW_H = 10
SUM_FONT_SZ = 7
LABEL_W = 40
BLOCK_H = (SUM_ROW_H * 4) + 8


def find_font_object(pdf: pikepdf.Pdf, font_name: str) -> Any:
    """
    Searches the input PDF for the font object corresponding to the given resource name.
    Wrapper around the new recursive utility for backward compatibility.
    """
    return find_resource_recursive(pdf, "/Font", font_name)


# pylint: disable=too-many-instance-attributes
class DiagnosticPDFGenerator:
    """Helper class to manage state during diagnostic PDF generation."""

    def __init__(self, src_pdf: pikepdf.Pdf, out_pdf: pikepdf.Pdf):
        self.src_pdf = src_pdf
        self.out_pdf = out_pdf
        self.helvetica_font = out_pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/Font"),
                    "/Subtype": pikepdf.Name("/Type1"),
                    "/BaseFont": pikepdf.Name("/Helvetica"),
                }
            )
        )
        self.current_page = None
        self.y_cursor = 0.0
        self.content_stream: List[str] = []
        self.font_resource_cache: Dict[str, Any] = {}

        # Drawing State
        self.active_font = "/Helvetica"
        self.active_size = FONT_SIZE

    def start_new_page(self):
        """Finalizes the current page and creates a new one."""
        if self.current_page is not None and self.content_stream:
            stream_data = "\n".join(self.content_stream).encode(
                "latin1", errors="replace"
            )
            self.current_page.Contents = self.out_pdf.make_stream(stream_data)

        self.current_page = self.out_pdf.add_blank_page(
            page_size=(PAGE_WIDTH, PAGE_HEIGHT)
        )

        self.current_page.Resources = pikepdf.Dictionary(
            {"/Font": pikepdf.Dictionary({"/Helvetica": self.helvetica_font})}
        )

        # Ensure source fonts are available
        for fname, fobj in self.font_resource_cache.items():
            self.current_page.Resources["/Font"][fname] = fobj

        self.y_cursor = PAGE_HEIGHT - MARGIN
        self.content_stream = []

        # Reset state on new page
        self.active_font = "/Helvetica"
        self.active_size = FONT_SIZE

    # ... (The rest of the class methods ensure_space, set_font, draw_text, etc.
    #      remain UNCHANGED from the "monolithic" version you provided last time.
    #      I am not repeating them here to save space, but they are part of the file.)

    # Re-pasting the rest of the file to be safe/complete:

    def ensure_space(self, units: float):
        """Starts a new page if there isn't enough vertical space."""
        if self.y_cursor - units < MARGIN:
            self.start_new_page()

    def set_font(self, font: str, size: float):
        """Updates the active font state."""
        self.active_font = font
        self.active_size = size

    def draw_text(self, text: str, x: float, y: float = None):
        """Draws text at the specified coordinates using active font settings."""
        if y is None:
            y = self.y_cursor

        safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        try:
            safe_text.encode("latin1")
        except UnicodeEncodeError:
            safe_text = safe_text.encode("latin1", errors="replace").decode("latin1")

        self.content_stream.append(
            f"BT {self.active_font} {self.active_size:.4f} Tf {x} {y} Td ({safe_text}) Tj ET"
        )

    def draw_hex_sample(
        self, hex_str: str, x: float, y: float = None, font_data: FontData = None
    ):
        """Draws a visual sample of the character using the specific hex code."""
        if y is None:
            y = self.y_cursor

        tf_size = self.active_size
        tm_d = 1.0

        if (
            font_data
            and hasattr(font_data, "font_matrix")
            and len(font_data.font_matrix) >= 4
        ):
            mat_yy = font_data.font_matrix[3]

            if mat_yy < 0:
                tm_d = -1.0

            design_height = 0.0

            if (
                hasattr(font_data, "type3_design_height")
                and font_data.type3_design_height > 0
            ):
                design_height = font_data.type3_design_height

            elif hasattr(font_data, "font_bbox") and font_data.font_bbox:
                design_height = abs(font_data.font_bbox[3] - font_data.font_bbox[1])

            effective_height = design_height * abs(mat_yy)

            if effective_height < 5.0:
                effective_height = abs(1000.0 * mat_yy)

            if effective_height > 1e-9:
                tf_size = self.active_size / effective_height

        ops = []
        ops.append(f"1 0 0 {tm_d:.2f} {x:.2f} {y:.2f} Tm")

        self.content_stream.append("BT")
        self.content_stream.append(" ".join(ops))
        self.content_stream.append(
            f"{self.active_font} {tf_size:.4f} Tf <{hex_str}> Tj ET"
        )

    def draw_line(self, x1: float, y1: float, x2: float, y2: float):
        """Draws a real graphic line using PDF operators."""
        self.content_stream.append(f"q 0.5 w {x1} {y1} m {x2} {y2} l S Q")

    def finalize(self):
        """Flushes the last page content."""
        if self.current_page is not None and self.content_stream:
            stream_data = "\n".join(self.content_stream).encode(
                "latin1", errors="replace"
            )
            self.current_page.Contents = self.out_pdf.make_stream(stream_data)

    def draw_header(self, cols):
        """Draw Header"""
        headers = [
            ("Code", "code"),
            ("Hex", "hex"),
            ("Width", "width"),
            ("Source", "src"),
            ("Helv", "helv"),
            ("WinAnsi", "win"),
            ("MacRom", "mac"),
            ("Glyph Name", "name"),
            ("Pages Used", "pages"),
        ]

        self.set_font("/Helvetica", FONT_SIZE)
        for label, key in headers:
            self.draw_text(label, cols[key])

        self.y_cursor -= 5
        self.draw_line(MARGIN, self.y_cursor, PAGE_WIDTH - MARGIN, self.y_cursor)
        self.y_cursor -= LINE_HEIGHT

    def draw_summary_table(
        self, sorted_codes: List[int], font_name: str, font_data: FontData
    ):
        """Draws the transposed summary table."""
        self.set_font("/Helvetica", 10)
        self.draw_text("Summary View (Transposed):", MARGIN)
        self.y_cursor -= LINE_HEIGHT

        avail_width = PAGE_WIDTH - MARGIN - MARGIN - LABEL_W
        items_per_row = int(avail_width / SUM_CELL_W)

        chunk_start = 0
        while chunk_start < len(sorted_codes):
            chunk = sorted_codes[chunk_start : chunk_start + items_per_row]

            self.ensure_space(BLOCK_H)

            # Draw Row Labels
            self.set_font("/Helvetica", SUM_FONT_SZ)
            self.draw_text("Code:", MARGIN, y=self.y_cursor)
            self.draw_text("Hex:", MARGIN, y=self.y_cursor - SUM_ROW_H)
            self.draw_text("Source:", MARGIN, y=self.y_cursor - (SUM_ROW_H * 2))
            self.draw_text("Helv:", MARGIN, y=self.y_cursor - (SUM_ROW_H * 3))

            # Draw Data Cells
            current_x = MARGIN + LABEL_W
            for code in chunk:
                hex_s = f"{code:02X}"

                self.set_font("/Helvetica", SUM_FONT_SZ)
                self.draw_text(str(code), current_x, y=self.y_cursor)
                self.draw_text(hex_s, current_x, y=self.y_cursor - SUM_ROW_H)

                self.set_font(font_name, 9)
                self.draw_hex_sample(
                    hex_s,
                    current_x,
                    y=self.y_cursor - (SUM_ROW_H * 2),
                    font_data=font_data,
                )

                self.set_font("/Helvetica", 9)
                self.draw_hex_sample(
                    hex_s, current_x, y=self.y_cursor - (SUM_ROW_H * 3)
                )

                current_x += SUM_CELL_W

            self.y_cursor -= BLOCK_H
            chunk_start += items_per_row

        self.y_cursor -= LINE_HEIGHT

    def draw_detailed_table(
        self, font_name: str, data: FontData, cols: Dict[str, float]
    ):
        """Draws the detailed metrics table."""
        self.set_font("/Helvetica", 10)
        self.draw_text("Detailed Metrics:", MARGIN)
        self.y_cursor -= LINE_HEIGHT

        self.draw_header(cols)

        # Draw Rows
        for code, width in sorted(data.used_char_codes.items()):
            self.ensure_space(LINE_HEIGHT)

            hex_str = f"{code:02X}"
            char_name = data.char_names.get(code, "")
            page_list = sorted(list(data.char_pages[code]))
            page_str = ", ".join(map(str, page_list))
            if len(page_str) > 40:
                page_str = page_str[:37] + "..."

            byte_val = bytes([code])
            char_win = byte_val.decode("cp1252", errors="replace")
            char_mac = byte_val.decode("mac_roman", errors="replace")

            if code < 32:
                char_win = char_mac = " "

            if len(char_win) == 1 and ord(char_win) == code:
                char_win = ""
            if len(char_mac) == 1 and ord(char_mac) == code:
                char_mac = ""

            self.set_font("/Helvetica", FONT_SIZE)
            self.draw_text(str(code), cols["code"])
            self.draw_text(f"0x{hex_str}", cols["hex"])
            self.draw_text(f"{width:.1f}", cols["width"])

            self.set_font(font_name, 12)
            self.draw_hex_sample(hex_str, cols["src"], font_data=data)

            self.set_font("/Helvetica", 12)
            self.draw_hex_sample(hex_str, cols["helv"])

            self.set_font("/Helvetica", FONT_SIZE)
            self.draw_text(char_win, cols["win"])
            self.draw_text(char_mac, cols["mac"])
            self.draw_text(char_name, cols["name"])
            self.draw_text(page_str, cols["pages"])

            self.y_cursor -= LINE_HEIGHT

    def draw_font_section(self, font_name: str, data: FontData):
        """Draws the complete report section for a single font."""
        # 75% Page Threshold Rule
        if self.y_cursor < (PAGE_HEIGHT * 0.25):
            self.start_new_page()
        else:
            self.ensure_space(LINE_HEIGHT * 5)

        if not font_name.startswith("/"):
            font_name = "/" + font_name
        if font_name not in self.font_resource_cache:
            src_font_obj = find_font_object(self.src_pdf, font_name)
            if src_font_obj:
                self.font_resource_cache[font_name] = self.out_pdf.copy_foreign(
                    src_font_obj
                )
                self.current_page.Resources["/Font"][font_name] = (
                    self.font_resource_cache[font_name]
                )

        status = "[Embedded]" if data.is_embedded else "[Unembedded]"

        self.set_font("/Helvetica", 12)
        self.draw_text(f"FONT: {data.source_name}   {status}", MARGIN)
        self.y_cursor -= LINE_HEIGHT

        pages_str = ", ".join(map(str, sorted(list(data.pages_used))[:15]))
        if len(data.pages_used) > 15:
            pages_str += "..."
        sizes_str = ", ".join(map(str, sorted(list(data.point_sizes))))

        self.set_font("/Helvetica", FONT_SIZE)
        self.draw_text(f"Type: {data.font_type} | Base: {data.base_font}", MARGIN + 10)
        self.y_cursor -= LINE_HEIGHT
        self.draw_text(f"Pages: {pages_str} | Sizes: {sizes_str}", MARGIN + 10)
        self.y_cursor -= LINE_HEIGHT * 2

        self.draw_summary_table(sorted(data.used_char_codes.keys()), font_name, data)

        cols = {
            "code": MARGIN + 10,
            "hex": MARGIN + 50,
            "width": MARGIN + 90,
            "src": MARGIN + 140,
            "helv": MARGIN + 190,
            "win": MARGIN + 240,
            "mac": MARGIN + 290,
            "name": MARGIN + 350,
            "pages": MARGIN + 500,
        }
        self.draw_detailed_table(font_name, data, cols)

        self.y_cursor -= LINE_HEIGHT * 2


def generate_diagnostic_pdf(input_path: Path, font_data_map: Dict[str, FontData]):
    """
    Creates a new PDF with diagnostic tables showing metrics, usage, and visual samples.
    """
    output_path = input_path.parent / f"{input_path.stem}_diagnostic.pdf"
    logger.info("Generating diagnostic PDF: %s", output_path.name)

    src_pdf = pikepdf.open(str(input_path))
    out_pdf = pikepdf.Pdf.new()

    for page in src_pdf.pages:
        out_pdf.pages.append(page)

    gen = DiagnosticPDFGenerator(src_pdf, out_pdf)
    gen.start_new_page()

    gen.set_font("/Helvetica", 14)
    gen.draw_text(f"--- PDF Font Inspector Report: {input_path.name} ---", MARGIN)
    gen.y_cursor -= LINE_HEIGHT * 2

    gen.set_font("/Helvetica", 10)
    gen.draw_text(
        f"Analyzed {len(font_data_map)} fonts with active text content.", MARGIN
    )
    gen.y_cursor -= LINE_HEIGHT * 2

    # Draw Sections
    for font_name, data in font_data_map.items():
        gen.draw_font_section(font_name, data)

    gen.finalize()
    out_pdf.save(output_path)

    src_pdf.close()
    out_pdf.close()
