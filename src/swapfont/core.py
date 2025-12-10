# src/swapfont/core.py
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import pikepdf
from pdfbeaver import ProcessingOptions, modify_page
from pikepdf import Name

from swapfont.engines.layout_engine import LayoutEngine
from swapfont.font_embedding import embed_truetype_font
from swapfont.font_utils import FontWrapper
from swapfont.handlers import create_font_replacer_handler
from swapfont.inspection.analyzer import inspect_pdf
from swapfont.models import ReplacementConfig
from swapfont.tracker import FontedStateTracker

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Holds the shared state and configuration for the processing pipeline."""

    config: ReplacementConfig
    target_font_cache: Dict[str, Any]
    custom_encoding_maps: Dict[str, Any]
    source_font_cache: Dict[str, Any]


def process_pdf(input_path: Path, output_path: Path, config: ReplacementConfig) -> None:
    """Main entry point for processing a PDF."""
    logger.info("Processing %s -> %s", input_path, output_path)

    # 1. Analyze Source Fonts
    # We must inspect the PDF to get metrics for the fonts we are replacing.
    logger.info("Analyzing source font metrics...")
    try:
        source_font_cache = inspect_pdf(input_path)
    except (pikepdf.PdfError, ValueError) as e:
        # Catch only operational errors (malformed PDF, parse failure).
        # Logic errors must crash.
        logger.warning("Failed to inspect source PDF metrics: %s", e)
        source_font_cache = {}

    # 2. Initialize Context
    context = PipelineContext(
        config=config,
        target_font_cache={},
        custom_encoding_maps={},
        source_font_cache=source_font_cache,
    )

    # 3. Pre-load Metrics & Initialize Maps
    for rule in config.rules:
        fname = rule.target_font_file

        if fname not in context.target_font_cache:
            try:
                context.target_font_cache[fname] = FontWrapper(fname)
                logger.debug("Loaded target font: %s", fname)
            except (OSError, ValueError) as e:
                logger.error("Failed to load target font %s: %s", fname, e)
                continue

        if fname not in context.custom_encoding_maps:
            context.custom_encoding_maps[fname] = {}

        _register_required_characters(rule, context.custom_encoding_maps[fname])

    # 4. Open PDF & Process
    with pikepdf.open(input_path, allow_overwriting_input=True) as pdf:

        embedded_objects = _embed_required_fonts(
            pdf, config, context.target_font_cache, context.custom_encoding_maps
        )

        global_visited = set()

        for i, page in enumerate(pdf.pages):
            logger.debug("Processing page %d", i + 1)
            source_pikepdf_fonts = _extract_page_fonts(page)

            try:
                _process_single_page(
                    pdf, page, context, source_pikepdf_fonts, global_visited
                )

                _update_page_resources(page, config, embedded_objects)

            except pikepdf.PdfError as e:
                # Catch only PDF processing errors (e.g. malformed stream).
                logger.error("Error processing page %d: %s", i + 1, e, exc_info=True)

        pdf.save(output_path)
        logger.info("Processing complete.")


def _extract_page_fonts(page: pikepdf.Page) -> Dict[str, Any]:
    """Helper to extract font objects from page resources."""
    fonts = {}
    resources = getattr(page, "Resources", {})
    if "/Font" in resources:
        for name, font_obj in resources["/Font"].items():
            fonts[name] = font_obj
    return fonts


def _process_single_page(
    pdf: pikepdf.Pdf,
    page: pikepdf.Page,
    ctx: PipelineContext,
    source_pikepdf_fonts: Dict[str, Any],
    visited_streams: set,
) -> None:
    """Orchestrates the replacement pipeline using the high-level API."""
    layout_engine = LayoutEngine(
        ctx.config,
        ctx.target_font_cache,
        ctx.custom_encoding_maps,
        ctx.source_font_cache,
        source_pikepdf_fonts,
    )

    handler = create_font_replacer_handler(layout_engine)

    options = ProcessingOptions(
        optimize=True,
        recurse_xobjects=True,
        tracker_class=FontedStateTracker,
        tracker_kwargs={
            "target_font_cache": ctx.target_font_cache,
            "custom_encoding_maps": ctx.custom_encoding_maps,
        },
        visited_streams=visited_streams,
    )

    modify_page(pdf, page, handler, options)


def _register_required_characters(rule, font_encoding_map: Dict[str, int]):
    """Populates the encoding map with high-bit characters required by the rule."""
    for mapping_target in rule.encoding_map.values():
        for char in mapping_target:
            if 32 <= ord(char) <= 126:
                continue
            if char not in font_encoding_map:
                font_encoding_map[char] = -1


def _embed_required_fonts(
    pdf: pikepdf.Pdf,
    config: ReplacementConfig,
    metrics_cache: Dict[str, Any],
    encoding_maps: Dict[str, Dict[str, int]],
) -> Dict[str, pikepdf.Object]:
    """Embeds fonts into the PDF and patches their encodings."""
    embedded_objects = {}

    for rule in config.rules:
        fname = rule.target_font_file

        if fname not in embedded_objects:
            logger.info("Embedding font file %s", fname)

            needed_chars = [c for c, slot in encoding_maps[fname].items()]
            next_slot = 128
            for char in sorted(needed_chars):
                encoding_maps[fname][char] = next_slot
                next_slot += 1

            slot_map = {slot: char for char, slot in encoding_maps[fname].items()}

            font_obj = embed_truetype_font(pdf, fname, slot_map)
            embedded_objects[fname] = font_obj

            if needed_chars:
                logger.info("Patching encoding for %s", fname)
                _patch_font_encoding(
                    font_obj,
                    needed_chars,
                    encoding_maps[fname],
                    metrics_cache[fname],
                )

    return embedded_objects


def _update_page_resources(pike_page, config, embedded_objects):
    """Adds the new font references to the page resources."""
    if "/Resources" not in pike_page:
        pike_page.Resources = pikepdf.Dictionary()

    if "/Font" not in pike_page.Resources:
        pike_page.Resources["/Font"] = pikepdf.Dictionary()

    fonts_dict = pike_page.Resources["/Font"]

    for rule in config.rules:
        if rule.target_font_file in embedded_objects:
            target_name = rule.target_font_name
            if not target_name.startswith("/"):
                target_name = "/" + target_name

            fonts_dict[target_name] = embedded_objects[rule.target_font_file]


def _patch_font_encoding(font_obj, needed_chars, encoding_map, metrics):
    """Modifies the PDF font object to define a custom encoding."""
    differences = []
    for char in sorted(needed_chars):
        glyph_name = metrics.cmap.get(ord(char))
        if not glyph_name:
            continue
        slot = encoding_map[char]
        differences.append(slot)
        differences.append(Name("/" + glyph_name))

    encoding_dict = pikepdf.Dictionary(
        {
            "/Type": Name("/Encoding"),
            "/BaseEncoding": Name("/WinAnsiEncoding"),
            "/Differences": pikepdf.Array(differences),
        }
    )
    font_obj["/Encoding"] = encoding_dict
