from unittest.mock import MagicMock

from swapfont.models import FontData

from ..conftest import create_mock_stream

# # Helper to create a mock glyph stream
# def create_mock_stream(content_str: str):
#     mock_stream = MagicMock()
#     # Simulate read_bytes returning latin1 encoded bytes
#     mock_stream.read_bytes.return_value = content_str.encode("latin1")
#     return mock_stream


class TestType3Parsing:

    def test_parsing_single_glyph_height(self, temp_pdf_doc):
        """
        Verifies that a single glyph with 'd1' sets the height correctly.
        Stream: 38 0 5 0 36 20 d1 -> lly=0, ury=20 -> Height 20
        """
        # Setup Mock CharProcs
        mock_char_procs = MagicMock(spec=dict)
        mock_char_procs.keys.return_value = ["/G1"]
        mock_char_procs.__getitem__.side_effect = lambda k: create_mock_stream(
            "38 0 5 0 36 20 d1 0.01 cm", temp_pdf_doc
        )
        # Emulate len() behavior on the mock dictionary
        mock_char_procs.__len__.return_value = 1

        # Setup Font Dict
        font_dict = {
            "/Subtype": "/Type3",
            "/CharProcs": mock_char_procs,
            "/BaseFont": "/TestFont",
        }

        # Initialize (which triggers _extract_type3_metrics)
        fd = FontData("/TestFont", font_dict)

        assert fd.type3_design_height == 20.0
        assert fd.type3_design_width == 31.0

    def test_parsing_aggregate_em_height(self, temp_pdf_doc):
        """
        Verifies that we scan multiple glyphs to find the true Em Height.
        Glyph 1 ('m'): 0 to 20
        Glyph 2 ('p'): -10 to 20
        Total Range: -10 to 20 = 30
        """
        mock_char_procs = MagicMock(spec=dict)
        # We pretend we have 2 glyphs
        mock_char_procs.keys.return_value = ["/m", "/p"]

        streams = {
            "/m": create_mock_stream("10 0 0 0 10 20 d1", temp_pdf_doc),  # 0 to 20
            "/p": create_mock_stream("10 0 0 -10 10 20 d1", temp_pdf_doc),  # -10 to 20
        }
        mock_char_procs.__getitem__.side_effect = lambda k: streams[k]
        mock_char_procs.__len__.return_value = 2

        font_dict = {"/Subtype": "/Type3", "/CharProcs": mock_char_procs}

        fd = FontData("/TestFont", font_dict)

        # Expected: max_ury (20) - min_lly (-10) = 30
        assert fd.type3_design_height == 30.0

    def test_resilience_to_garbage_data(self, temp_pdf_doc):
        """
        Ensures the parser doesn't crash on garbage binary data.
        """
        mock_char_procs = MagicMock(spec=dict)
        mock_char_procs.keys.return_value = ["/Bad"]
        # Random binary bytes that might decode to weird chars, but no 'd1'
        mock_char_procs.__getitem__.return_value = create_mock_stream(
            "ÿØÿà\x00\x10JFIF", temp_pdf_doc
        )
        mock_char_procs.__len__.return_value = 1

        font_dict = {"/Subtype": "/Type3", "/CharProcs": mock_char_procs}

        # Should not raise exception
        fd = FontData("/BadFont", font_dict)

        # Should remain 0.0 default
        assert fd.type3_design_height == 0.0
        assert fd.type3_design_width == 0.0

    def test_ignores_short_argument_lists(self, temp_pdf_doc):
        """
        If 'd1' appears but without enough preceding numbers, ignore it.
        """
        mock_char_procs = MagicMock(spec=dict)
        mock_char_procs.keys.return_value = ["/Broken"]
        # Only 2 args before d1 (needs 6)
        mock_char_procs.__getitem__.return_value = create_mock_stream(
            "10 20 d1", temp_pdf_doc
        )
        mock_char_procs.__len__.return_value = 1

        font_dict = {"/Subtype": "/Type3", "/CharProcs": mock_char_procs}

        fd = FontData("/BrokenFont", font_dict)
        assert fd.type3_design_height == 0.0
        assert fd.type3_design_width == 0.0
