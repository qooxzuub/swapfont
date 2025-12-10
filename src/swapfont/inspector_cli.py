# src/swapfont.inspection.analyzer_cli.py
"""CLI for PDF font inspector"""

from pathlib import Path

import click

from swapfont.inspection.analyzer import main_inspector


@click.command(context_settings={"help_option_names": ["-h", "--help"]}, name="inspect")
@click.argument("input_pdf", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable DEBUG level logging for verbose output.",
)
def main(input_pdf: Path, debug: bool):
    """
    Analyzes a PDF to identify unembedded fonts and generate a replacement configuration.
    """
    # Pass the input_pdf Path object AND the debug flag value to main_inspector
    # The debug flag is now handled by click and passed directly as a boolean.
    # No try/except here; let errors propagate.
    main_inspector(argv=input_pdf, debug_flag=debug)


if __name__ == "__main__":
    main()
