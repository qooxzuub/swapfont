# src/swapfont/wizard.py
"""Interactive tool for relatively user friendly PDF font replacement"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click

from swapfont.core import process_pdf
from swapfont.inspection.analyzer import inspect_pdf
from swapfont.models import ReplacementConfig, ReplacementRule


@click.command()
@click.argument("input_pdf", type=click.Path(exists=True))
@click.option("-o", "--output", type=click.Path(), help="Output PDF file path")
@click.option(
    "--replace-font",
    multiple=True,
    type=(str, str),
    help="Specify (FONT_NAME, TTF_PATH) for replacement",
)
@click.option(
    "--yes", is_flag=True, help="Automatically say YES to replacing all fonts"
)
@click.option(
    "--no-interactive-replace",
    is_flag=True,
    help="Automatically say NO to replacing fonts unless provided via --replace-font",
)
@click.option(
    "--no-replace-all",
    is_flag=True,
    help="Automatically refuse all font rules, even CLI-specified",
)
@click.option(
    "--no-ligatures",
    is_flag=True,
    help="Disable ligature detection and mapping entirely",
)
@click.option(
    "--accept-ligatures",
    is_flag=True,
    help="Automatically accept ligature mappings without prompting",
)
def wizard(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    input_pdf,
    output,
    replace_font,
    yes,
    no_interactive_replace,
    no_replace_all,
    no_ligatures,
    accept_ligatures,
):
    """
    Interactive wizard to replace fonts in a PDF.
    """
    logging.basicConfig(level=logging.WARNING)
    input_path = Path(input_pdf)

    if output is None:
        output = _configure_output_path(input_path)

    click.echo(f"Inspecting {input_path}...")
    font_data_map = inspect_pdf(input_path)

    if not font_data_map:
        click.echo("No fonts found in PDF.")
        return

    # Process CLI replacements into a dictionary
    cli_replacements = _prepare_replacements_map(replace_font)

    # Main Rule Generation Logic
    rules = _generate_rules(
        font_data_map,
        cli_replacements,
        yes,
        no_interactive_replace,
        no_ligatures,
        accept_ligatures,
    )

    if no_replace_all or not rules:
        click.echo("No rules selected. No fonts replaced. Exiting.")
        return

    # Execute Processing
    config = ReplacementConfig(rules=rules)
    click.echo("Processing...")
    process_pdf(input_path, Path(output), config)
    click.echo(f"Done! Saved to {output}")


def _configure_output_path(input_path: Path) -> str:
    """Generates a default output filename."""
    # Changed suffix to _new.pdf to match test expectation
    return str(input_path.with_name(f"{input_path.stem}_new.pdf"))


def _prepare_replacements_map(
    replace_font_options: Tuple[Tuple[str, str], ...],
) -> Dict[str, str]:
    """Converts the tuple of CLI options into a dictionary."""
    return dict(replace_font_options)


def _generate_rules(
    font_data_map,
    cli_replacements,
    auto_yes,
    no_interactive,
    no_ligatures,
    accept_ligatures,
) -> List[ReplacementRule]:
    # pylint: disable=too-many-arguments, too-many-positional-arguments
    """Iterates through found fonts and generates replacement rules."""
    rules = []

    for font_name, data in font_data_map.items():
        font_type = getattr(data, "font_type", "Unknown")
        click.echo(f"\nFound font: {font_name} (Type: {font_type})")

        # Determine replacement path
        ttf_path = _get_replacement_path(
            font_name, cli_replacements, auto_yes, no_interactive
        )

        if not ttf_path:
            click.echo(f"Skipping {font_name}.")
            continue

        # Handle Ligatures
        enc_map = _handle_ligatures(data, no_ligatures, accept_ligatures)

        # Create Rule
        rule = ReplacementRule(
            source_font_name=font_name,
            target_font_file=str(ttf_path),
            target_font_name=f"/New_{font_name[1:]}",
            strategy="scale_to_fit",
            encoding_map=enc_map,
        )
        rules.append(rule)

    return rules


def _get_replacement_path(
    font_name: str,
    cli_replacements: Dict[str, str],
    auto_yes: bool,
    no_interactive: bool,
) -> Optional[str]:
    """
    Determines the path to the replacement font file.
    Returns None if the user skips or no path is available.
    """
    # 1. Check strict CLI mapping
    if font_name in cli_replacements:
        return cli_replacements[font_name]

    # 2. Check Auto-Yes mode
    if auto_yes:
        # In auto-yes mode, we must prompt for path if not provided via CLI
        return click.prompt(
            f"Replacement TTF for {font_name}", type=click.Path(exists=True)
        )

    # 3. Check No-Interactive mode
    if no_interactive:
        return None

    # 4. Interactive Prompt
    if not click.confirm(f"Replace font {font_name}?"):
        return None

    return click.prompt("Path to replacement TTF file", type=click.Path(exists=True))


def _handle_ligatures(
    font_data,
    no_ligatures: bool,
    accept_ligatures: bool,
) -> Dict[str, str]:
    """
    Detects ligatures in the source font usage and returns an encoding map.
    """
    enc_map = {}

    if no_ligatures:
        return enc_map

    used_codes = getattr(font_data, "used_char_codes", set())

    # Check for 'fi' ligature (code 12 in standard TeX OT1)
    if 12 in used_codes:
        if accept_ligatures:
            enc_map["0x0c"] = "fi"
        elif click.confirm("Detected potential 'fi' ligature (code 12). Map to 'fi'?"):
            enc_map["0x0c"] = "fi"

    return enc_map
