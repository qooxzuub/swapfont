# **swapfont**
> **A PDF font replacer**
<img align="right" width="100" src="https://raw.githubusercontent.com/qooxzuub/swapfont/main/.github/assets/swapfont.svg">

[![PyPI](https://img.shields.io/pypi/v/swapfont)](https://pypi.org/project/swapfont/)
[![CI](https://github.com/qooxzuub/swapfont/actions/workflows/ci.yml/badge.svg)](https://github.com/qooxzuub/swapfont/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/qooxzuub/swapfont/graph/badge.svg)](https://codecov.io/gh/qooxzuub/swapfont)
[![Documentation Status](https://readthedocs.org/projects/swapfont/badge/?version=latest)](https://swapfont.readthedocs.io/en/latest/?badge=latest)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/swapfont)](https://pypi.org/project/swapfont/)

`swapfont` is a unified toolkit for analyzing and replacing legacy fonts (such as bitmapped Type 3 fonts) in PDF files with modern TrueType or OpenType fonts.

It performs a **direct vector replacement** by rewriting PDF content streams. It automatically adjusts horizontal character scaling (Tz) to ensure the original visual layout—including text reflow and spacing—is preserved, even when the new font has significantly different metrics.

## **Features**

* **Interactive Wizard:** A "dashboard" style CLI to quickly identify and replace fonts without writing config files.
* **Content Stream Rewriting:** Replaces font names and character codes in text-showing operators (`Tj`, `'`, `"`).
* **Layout Preservation:** Calculates `Tz` scaling to squash or stretch new text to fit the original bounding box (defaulting to a liberal 50%–200% range to ensure fit).
* **Kerning Preservation:** Converts complex spacing arrays (`[ (A) 50 (V) ] TJ`) into explicit positioning (`Td`) if necessary to maintain exact spacing.
* **TrueType Font Embedding:** Embeds the target font file into the resulting PDF.

## **Installation**

```bash
pip install swapfont
```

## **Quick Start (The Wizard)**

The easiest way to use `swapfont` is the interactive wizard. It scans your PDF and lets you pick replacements font-by-font.

```bash
swapfont wizard input.pdf
```

_Note: the interactive wizard is a work in progress, and the user interface is not yet particularly pleasant._

## **CLI Reference**

`swapfont` is a single binary with multiple subcommands.

### **1. Run (The Core Replacer)**
Executes a replacement using a configuration file. Ideally used for automation pipelines.

```bash
swapfont run input.pdf config.json [-o output.pdf]
```

### **2. Inspect**
Analyzes a PDF to identify unembedded or Type 3 fonts and generates a "skeleton" configuration file for you to edit.

```bash
swapfont inspect input.pdf
```

### **3. Glue**
An intermediate tool to generate a `swapfont` compatible JSON from the inspector's output, filtering only for the fonts you provide mappings for.

```bash
swapfont glue inspector_output.json output_config.json --mapping mapping.json
```

## **Configuration (config.json)**

For automated pipelines (using `swapfont run`), you define replacements in a JSON file.

### **Example Configuration**

```json
{
  "description": "Standard replacement of Type 3 fonts with local TrueType files.",
  "rules": [
    {
      "source_font_name": "/R136",
      "target_font_file": "fonts/Roboto-Regular.ttf",
      "target_font_name": "Roboto-Regular"
    },
    {
      "source_font_name": "/R20",
      "target_font_file": "fonts/Arial.ttf",
      "target_font_name": "ArialMT",
      "strategy_options": {
          "min_scale": 50.0,
          "max_scale": 150.0
      }
    }
  ]
}
```

### **Replacement Rule Details**

| Field | Type | Description |
| :--- | :--- | :--- |
| `source_font_name` | String | The internal name of the font in the PDF's resources (e.g., `/F1`, `/R136`). |
| `target_font_file` | String | The path to the replacement TrueType/OpenType font file. |
| `target_font_name` | String | The new internal name to use in the PDF resources (e.g., `/F_NEW_ROB`). |
| `strategy` | Literal | **`scale_to_fit`** (Default): Calculates `Tz` scaling to match the original width. |
| `strategy_options` | Object | Defines the limits for horizontal scaling.<br>• **`min_scale`**: Minimum allowed scaling % (Default: 50.0)<br>• **`max_scale`**: Maximum allowed scaling % (Default: 200.0) |
| `encoding_map` | Dictionary | **Advanced:** Maps source character codes (e.g., `"0x41"`) to target characters (e.g., `"A"`). Essential for Type 3 fonts with non-standard encodings. |

## **Advanced Usage: The Inspection Workflow**

If you have a complex PDF and don't know the font names:

1.  **Inspect:** Run `swapfont inspect document.pdf`. This generates a report and a `font_rules.json` template.
2.  **Edit:** Open `font_rules.json`. Fill in `target_font_file` for the fonts you want to replace. Remove the blocks for fonts you want to keep.
3.  **Run:** Execute `swapfont run document.pdf font_rules.json`.