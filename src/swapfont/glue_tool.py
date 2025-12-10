# src/swapfont/glue_tool.py
import json

import click


@click.command(name="glue")
@click.argument("inspector_json", type=click.Path(exists=True))
@click.argument("output_json", type=click.Path())
@click.option(
    "--mapping",
    type=click.Path(exists=True),
    default=None,
    help="JSON file with user mapping: {source_base_font: target_font_file}",
)
def main(inspector_json, output_json, mapping):
    """
    Generate a `swapfont` compatible JSON from a `swapfont-inspector` output,
    only including fonts that the user has provided mappings for.
    """
    # Load inspector JSON
    with open(inspector_json, "r", encoding="utf-8") as f:
        inspector_data = json.load(f)

    # Load user mapping if provided
    user_map = {}
    if mapping:
        with open(mapping, "r", encoding="utf-8") as f:
            user_map = json.load(f)

    rules = []

    for rule in inspector_data.get("rules", []):
        base_font = rule.get("source_base_font")
        source_name = rule.get("source_font_name")

        if not base_font or base_font not in user_map:
            # Skip fonts with no mapping
            continue

        target_file = user_map[base_font]
        target_name = f"/F_New_{source_name.strip('/')}"  # default target font name

        replacement = {
            "source_font_name": source_name,
            "source_base_font": base_font,
            "target_font_file": target_file,
            "target_font_name": target_name,
            "strategy": "scale_to_fit",
            "strategy_options": {"method": "horizontal_scaling"},
            "preserve_unmapped": False,
            "encoding_map": {},
            "width_overrides": {},
        }

        rules.append(replacement)

    output_data = {"rules": rules}

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4)

    click.echo(f"Generated {len(rules)} rules to {output_json}")


if __name__ == "__main__":
    main()
