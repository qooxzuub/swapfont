import logging
from pathlib import Path

import click

from swapfont.core import process_pdf

# Import your existing logic
from swapfont.inspection.analyzer import inspect_pdf
from swapfont.models import ReplacementConfig, ReplacementRule


@click.command()
@click.option("-o", "--output", type=click.Path())
def wizard(output):
    """Interactive wizard for replacing fonts."""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    input_pdf = "pdfs/type3.pdf"
    input_path = Path(input_pdf)
    if not output:
        output = input_path.parent / f"{input_path.stem}_new.pdf"

    click.echo("Scanning PDF...")
    # 1. Inspect
    fonts = inspect_pdf(input_path)

    rules = []

    # 2. Interact
    for font_name, data in fonts.items():
        click.echo(f"\nFound Font: {font_name} (Base: {data.base_font})")
        if str(font_name) == "/R20":
            ttf_path = "fonts/test.ttf"
            # if click.confirm("Do you want to replace this font?"):
            #     ttf_path = click.prompt(
            #         "Path to replacement TTF file", type=click.Path(exists=True)
            #     )

            # Auto-detect encoding issues?
            enc_map = {}

            rule = ReplacementRule(
                source_font_name=font_name,
                target_font_file=str(ttf_path),
                target_font_name=f"/New_{font_name[1:]}",
                strategy="scale_to_fit",
                encoding_map=enc_map,
            )
            rules.append(rule)

    if not rules:
        click.echo("No rules selected. Exiting.")
        return

    # 3. Process
    config = ReplacementConfig(rules=rules)
    click.echo("Processing...")
    process_pdf(input_path, Path(output), config)
    click.echo(f"Done! Saved to {output}")


if __name__ == "__main__":
    wizard()
