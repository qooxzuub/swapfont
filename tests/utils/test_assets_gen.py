import os

import pikepdf
from pikepdf import Name, Operator


def create_dummy_pdf():
    """Creates a minimal valid PDF with one page and one text stream."""
    pdf = pikepdf.new()

    # Create a minimal content stream: /F1 12 Tf (Hello) Tj
    # Note: We are using standard 14 fonts logic here just to make it valid
    content_stream = [
        ([Name("/F1"), 120], Operator("Tf")),
        ([pikepdf.String("ABC")], Operator("Tj")),  # "A" will be 0x41
    ]

    pdf.add_blank_page(page_size=(500, 500))
    page = pdf.pages[0]

    # FIX: Use make_stream and assign to Contents
    stream_data = pikepdf.unparse_content_stream(content_stream)
    page.Contents = pdf.make_stream(stream_data)

    # Add a dummy resource dict so the code finds /F1
    # In a real PDF, this would point to a font dict
    page.Resources = pikepdf.Dictionary(
        {
            "/Font": pikepdf.Dictionary(
                {
                    "/F1": pikepdf.Dictionary(
                        {
                            "/Type": Name("/Font"),
                            "/Subtype": Name("/Type1"),
                            "/BaseFont": Name("/Helvetica"),
                        }
                    )
                }
            )
        }
    )

    pdf.save("test_input.pdf")
    print("Generated test_input.pdf")


def create_dummy_config():
    """Creates the JSON config."""
    import json

    # We need a real TTF for the tool to run.
    # We will point to a system font or you must provide one.
    # Assuming linux/mac environment commonly has DejaVu or Arial.
    # IF THIS FAILS, CHANGE THIS PATH TO A VALID TTF ON YOUR SYSTEM.
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    if not os.path.exists(font_path):
        print(
            f"WARNING: Could not find {font_path}. Please edit test_config.json with a valid .ttf path."
        )
        font_path = "REPLACE_WITH_VALID_TTF.ttf"

    config = {
        "rules": [
            {
                "source_font_name": "/F1",
                "target_font_file": font_path,
                "target_font_name": "/F_New",
                "strategy": "scale_to_fit",
                "encoding_map": {"0x41": "B"},  # Replace A with B
                "width_overrides": {"0x41": 1000},  # Pretend 'A' was very wide
            }
        ]
    }

    with open("test_config.json", "w") as f:
        json.dump(config, f, indent=2)
    print("Generated test_config.json")


if __name__ == "__main__":
    create_dummy_pdf()
    create_dummy_config()
