# src/swapfont.inspection.analyzer.py
"""PDF font inspector logic"""

import argparse
import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import pikepdf
from pikepdf import Array

# Import the core FontData model and constants from the separate models module
from ..models import TEXT_SHOWING_OPERATORS, FontData

# Import the new diagnostic generation function
from .diagnostic import generate_diagnostic_pdf

# Logger is set up later in main_inspector
logger = logging.getLogger(__name__)

# --- Inspection Logic ---


def scan_for_text_content(pdf: pikepdf.Pdf, font_data_map: Dict[str, FontData]):
    """
    Scans all text-showing operators (Tj, TJ, ', ") across all pages
    to populate the set of used character codes for each font.
    """
    for i, page in enumerate(pdf.pages):
        page_num = i + 1
        logger.debug("Scanning page %d", page_num)

        try:
            _scan_page_for_text_content(page, font_data_map, page_num)
        except (pikepdf.PdfError, ValueError, TypeError) as e:
            logger.error("Failed to process content stream on page %d: %s", i + 1, e)


def _scan_page_for_text_content(
    page: pikepdf.Page, font_data_map: Dict[str, FontData], page_num: int
):
    fonts = page.Resources.get("/Font", {})
    if not fonts:
        return

    tokens = pikepdf.parse_content_stream(page)
    active_font_name = None

    for operands, operator in tokens:
        op_str = str(operator)

        if op_str == "Tf":
            active_font_name = _handle_font_operator(operands, font_data_map)
        elif op_str in TEXT_SHOWING_OPERATORS:
            _handle_text_operator(operands, font_data_map, active_font_name, page_num)


def _handle_font_operator(
    operands: List[Any], font_data_map: Dict[str, FontData]
) -> Optional[str]:
    """Process 'Tf' operator: track active font and record point size."""
    try:
        font_name = str(operands[0])
        if font_name in font_data_map:
            size = float(operands[1])
            font_data_map[font_name].point_sizes.add(size)
        return font_name
    except (ValueError, IndexError):
        return None


def _handle_text_operator(
    operands: List[Any],
    font_data_map: Dict[str, FontData],
    active_font_name: Optional[str],
    page_num: int,
):
    """Process text showing operators and update FontData usage."""
    if not active_font_name or active_font_name not in font_data_map:
        return

    font_data = font_data_map[active_font_name]
    font_data.pages_used.add(page_num)

    token_list = (
        operands[0] if isinstance(operands[0], (Array, list)) else [operands[0]]
    )

    for token in token_list:
        _process_text_token(token, font_data, page_num)


def _process_text_token(token: Any, font_data: FontData, page_num: int):
    """Convert token to bytes and update font data structures."""
    if isinstance(token, (int, float, Decimal)):
        return  # skip kerning values

    try:
        source_bytes = str(token).encode("latin1")
    except ValueError as exc:
        logger.debug(
            "Could not convert token to string in %s stream: %r (Type: %s) - %s",
            font_data.source_name,
            token,
            type(token),
            exc,
        )
        return

    for byte_val in source_bytes:
        code = int(byte_val)
        if code not in font_data.used_char_codes:
            font_data.used_char_codes[code] = font_data.get_width(code)
        font_data.char_pages[code].add(page_num)


def inspect_pdf(input_path: Path) -> Dict[str, FontData]:
    """
    Main inspection function: opens PDF, extracts font resources, and scans content.
    """
    logger.info("Starting inspection of %s", input_path.name)

    # 1. Gather all Font Resources from all pages
    # Open the PDF specifically for resource gathering
    pdf = pikepdf.open(str(input_path))
    try:
        font_data_map = _gather_fonts_from_pdf(pdf)
    finally:
        pdf.close()

    # 2. Scan content streams to find *used* character codes
    # Re-open PDF to reset it for content scanning (preserving original behavior)
    pdf = pikepdf.open(str(input_path))
    try:
        scan_for_text_content(pdf, font_data_map)
    finally:
        pdf.close()

    # 3. Filter and Report
    final_map = _filter_unused_fonts(font_data_map)
    _report_inspection_results(len(final_map))

    return final_map


def _gather_fonts_from_pdf(pdf: pikepdf.Pdf) -> Dict[str, FontData]:
    """Iterates through pages to collect all unique font resources."""
    font_data_map: Dict[str, FontData] = {}

    for page in pdf.pages:
        _collect_fonts_from_page(page, font_data_map)

    return font_data_map


def _collect_fonts_from_page(page: pikepdf.Page, font_data_map: Dict[str, FontData]):
    """Collects fonts from a single page's resources."""
    if "/Font" not in page.Resources:
        return

    for font_name, font_dict in page.Resources["/Font"].items():
        font_name_str = str(font_name)

        if font_name_str in font_data_map:
            continue

        font_data_map[font_name_str] = _initialize_font_data(font_name_str, font_dict)


def _initialize_font_data(font_name: str, font_dict: Any) -> FontData:
    """Creates a FontData object and performs initial Type 3 checks."""
    current_font_data = FontData(font_name, font_dict)

    # Access CharProcs to trigger any necessary loading/validation
    # matching the behavior of the original code
    if "/CharProcs" in font_dict:
        cp = font_dict["/CharProcs"]
        keys = list(cp.keys())
        if keys:
            _ = cp[keys[0]].read_bytes()

    return current_font_data


def _filter_unused_fonts(font_data_map: Dict[str, FontData]) -> Dict[str, FontData]:
    """Returns a dictionary containing only fonts that have used characters."""
    return {name: data for name, data in font_data_map.items() if data.used_char_codes}


def _report_inspection_results(count: int):
    """Logs the final results of the inspection."""
    if count == 0:
        logger.warning("No fonts with used characters were found in the PDF.")
    logger.info("Inspection complete. Found %d used fonts.", count)


# --- Output Generation ---


def generate_template_config(font_data_map: Dict[str, FontData], input_path: Path):
    """
    Generates a configuration template and saves it as a JSON file.
    """
    output_dir = input_path.parent
    config_path = output_dir / "font_rules.json"

    template_data = {
        "description": f"Configuration template for replacing fonts in {input_path.name}",
        "rules": [],
    }

    if not font_data_map:
        _write_empty_template(config_path, template_data)
        return

    for font_name, data in font_data_map.items():
        rule = _create_rule_template(font_name, data)
        template_data["rules"].append(rule)

    _write_config_file(config_path, template_data)
    logger.info(
        "Review 'characters_used' in the template to understand what glyphs must be included in your target font."
    )


def _write_empty_template(path: Path, data: Dict[str, Any]):
    """Writes an empty template file and logs it."""
    logger.info("No replacement rules generated as no used fonts were found.")
    _write_config_file(path, data)
    logger.info("Generated empty configuration template: %s", path.name)


def _write_config_file(path: Path, data: Dict[str, Any]):
    """Helper to write the JSON config file."""
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    logger.info("Generated configuration template: %s", path.name)


def _create_rule_template(font_name: str, data: FontData) -> Dict[str, Any]:
    """Constructs a single rule dictionary for the template."""
    char_details = []
    for code, width in sorted(data.used_char_codes.items()):
        char_details.append(
            {
                "code": code,
                "hex": f"0x{code:02x}",
                "width": round(width, 3),
                "name": data.char_names.get(code, "N/A"),
                "pages": sorted(list(data.char_pages[code])),
            }
        )

    return {
        "source_font_name": font_name,
        "source_base_font": data.base_font,
        "source_type": data.font_type,
        "is_embedded": data.is_embedded,
        "point_sizes": sorted(list(data.point_sizes)),
        "target_font_file": "",
        "target_font_name": "",
        "characters_used": char_details,
    }


# --- Main Execution ---


def main_inspector(argv=None, debug_flag=False):
    """
    Main command-line entry point. Accepts an optional list of arguments
    and a pre-processed debug flag from the CLI wrapper.
    """
    _configure_logging(debug_flag)

    args = _parse_arguments(argv)
    if not args:
        return

    input_path: Path = args.INPUT_PDF

    if not input_path.is_file():
        logger.error("Error: Input PDF file not found at %s", input_path)
        return

    # 3. Run Inspection and Output
    font_data = inspect_pdf(input_path)
    generate_template_config(font_data, input_path)

    # --- GENERATE DIAGNOSTIC PDF ---
    generate_diagnostic_pdf(input_path, font_data)

    logger.info("Inspection complete. Use the generated files to configure swapfont.")


def _configure_logging(debug_flag: bool):
    """Sets up the basic logging configuration."""
    log_level = logging.DEBUG if debug_flag else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] %(funcName)s - %(message)s",
    )


def _parse_arguments(argv):
    """Parses command line arguments."""
    if argv is not None:
        if not isinstance(argv, list) and isinstance(argv, Path):
            argv = [str(argv)]
        elif not isinstance(argv, list):
            argv = [str(argv)]

    parser = argparse.ArgumentParser(
        description="PDF Font Inspector: Extracts source font data and generates a configuration template and a visual diagnostic PDF to aid in font replacement setup.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "INPUT_PDF", type=Path, help="Path to source PDF containing fonts."
    )

    return parser.parse_args(argv)


if __name__ == "__main__":
    main_inspector()
