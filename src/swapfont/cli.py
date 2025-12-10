# src/swapfont/cli.py
"""
Main CLI entry point for swapfont.
Unifies all sub-tools (run, inspect, wizard, glue) into a single binary.
"""

import json
import logging
from pathlib import Path

import click

# Import the core logic for the 'run' command
from .core import process_pdf
from .models import ReplacementConfig

# Import the entry points of the other tools
# We use try/except to handle cases where these files might not be fully migrated yet,
# allowing the main tool to still function.
try:
    from .glue_tool import main as glue_cmd
    from .inspector_cli import main as inspect_cmd
    from .wizard import wizard as wizard_cmd
except ImportError as e:
    # Fallback for development if modules are missing
    logging.warning("Could not import subcommands: %s", e)
    inspect_cmd = None
    wizard_cmd = None
    glue_cmd = None

logger = logging.getLogger(__name__)


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging.")
def main(debug):
    """
    swapfont: A toolkit for replacing fonts in PDFs.

    Use one of the subcommands below to interact with the tool.
    """
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] %(funcName)s - %(message)s",
        force=True,  # Ensure we override any existing handlers
    )


@main.command(name="run")
@click.argument("input_pdf", type=click.Path(exists=True, path_type=Path))
@click.argument("config_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Output PDF path")
def run_command(input_pdf, config_json, output):
    """
    Execute a font replacement using a config file.

    INPUT_PDF: Path to source PDF.
    CONFIG_JSON: Path to mapping configuration.
    """
    if not output:
        output = input_pdf.with_name(f"{input_pdf.stem}_replaced.pdf")

    logger.info("Loading configuration from %s", config_json)
    try:
        with open(config_json, "r", encoding="utf-8") as f:
            raw_config = json.load(f)

        logger.info("raw_config loaded")
        config = ReplacementConfig(**raw_config)

        process_pdf(input_pdf, output, config)
        logger.info("Done.")

    except Exception as e:
        logger.error("Failed to process PDF: %s", e)
        raise click.Abort()


# Register the subcommands from other modules
if inspect_cmd:
    main.add_command(inspect_cmd, name="inspect")

if wizard_cmd:
    main.add_command(wizard_cmd, name="wizard")

if glue_cmd:
    main.add_command(glue_cmd, name="glue")


if __name__ == "__main__":
    main()
