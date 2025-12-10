import logging

import pikepdf
from pikepdf import Dictionary

from swapfont.core import _update_page_resources

# Import modules to test
from swapfont.models import (
    ReplacementConfig,
    ReplacementRule,
    resolve_unicode_name,
)


# --- 1. Models: Fuzzy Logic Coverage ---
def test_resolve_unicode_name_fuzzy_branches(caplog):
    """
    Covers lines 54-61 in models.py: Fuzzy matching for LIGATURE descriptions.
    """
    # 1. Exact "LIGATURE" match (Branch 1)
    # "LATIN SMALL LIGATURE FI" -> "LATIN SMALL LIGATURE FI" (stripped) -> \ufb01
    assert resolve_unicode_name("LATIN SMALL LIGATURE FI") == "\ufb01"

    # 2. "LIGATURE" in name but standard lookup fails (Branch 2 entry)
    # "LATIN SMALL LIGATURE UNKNOWNTHING" -> Matches "LIGATURE" check
    # Inner try/except catches KeyError
    with caplog.at_level(logging.WARNING):
        res = resolve_unicode_name("LATIN SMALL LIGATURE UNKNOWNTHING")
        assert res == "LATIN SMALL LIGATURE UNKNOWNTHING"


# --- 2. Core: Defensive Resource Creation ---
def test_update_page_resources_creates_missing_dicts():
    """
    Covers lines 206-217 in core.py: Creating missing /Resources and /Font dicts.
    """
    # 1. Create a raw pikepdf page with NO resources
    pdf = pikepdf.new()
    page = pdf.add_blank_page()
    del page.Resources  # Ensure it is gone

    # 2. Setup minimal config to trigger the loop
    rule = ReplacementRule(
        source_font_name="/Test",
        target_font_file="dummy.ttf",
        target_font_name="/NewTest",
    )
    config = ReplacementConfig(rules=[rule])

    # 3. Mock embedded objects
    embedded_objs = {"dummy.ttf": Dictionary()}

    # Execute
    _update_page_resources(page, config, embedded_objs)

    # Assert
    assert "/Resources" in page
    assert "/Font" in page.Resources
    assert "/NewTest" in page.Resources["/Font"]
