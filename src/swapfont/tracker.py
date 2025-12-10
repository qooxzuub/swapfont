# src/swapfont/tracker.py
from pdfbeaver.state_tracker import StateTracker


class FontedStateTracker(StateTracker):
    """
    Application-specific tracker that holds the font cache,
    encoding maps and the currently active font wrapper.

    """

    def __init__(self, target_font_cache, custom_encoding_maps):
        super().__init__()
        self.target_font_cache = target_font_cache
        self.custom_encoding_maps = custom_encoding_maps
        self.active_font_wrapper = None
