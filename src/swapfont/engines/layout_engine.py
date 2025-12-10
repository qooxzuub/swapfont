# src/swapfont/engines/layout_engine.py
"""
Handles the mathematical and logical operations for text replacement.
Responsible for:
1. Rewriting text bytes (Source -> Target Mapping).
2. Calculating visual widths of source and target text.
3. Handling Type 3 scaling factors.
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pikepdf
from pdfbeaver.utils.pdf_conversion import extract_string_bytes

from ..font_utils import FontWrapper
from ..models import ReplacementConfig, ReplacementRule

logger = logging.getLogger(__name__)


class LayoutEngine:  # pylint: disable=too-many-instance-attributes
    """
    Encapsulates the rules and math for text replacement.
    """

    def __init__(
        self,
        config: ReplacementConfig,
        target_font_cache: Dict[str, FontWrapper],
        custom_encoding_maps: Dict[str, Dict[str, int]],
        source_font_cache: Dict[str, Any],
        source_pikepdf_fonts: Any,
    ):
        # pylint: disable=too-many-arguments, too-many-positional-arguments
        self.config = config
        self.target_font_cache = target_font_cache
        self.custom_encoding_maps = custom_encoding_maps
        self.source_font_cache = source_font_cache
        self.source_pikepdf_fonts = source_pikepdf_fonts

        # Active State
        self.current_pdf_font_name: Optional[str] = None
        self.active_rule: Optional[ReplacementRule] = None
        self.active_wrapper: Optional[FontWrapper] = None
        self.active_font_size: float = 1.0

        # Char (str) -> Slot (int)
        self.active_target_slot_map: Optional[Dict[str, int]] = None

        # Inverse Map: Slot (int) -> Char (str)
        self.active_target_char_map: Optional[Dict[int, str]] = None

        # Source Byte (int) -> Char (str) (from Rule Hex Keys)
        self.active_source_hex_map: Dict[int, str] = {}

        # Track Type 3 scaling
        self.current_type3_scale_factor: float = 1.0

    def set_active_font(self, font_name: str | pikepdf.Name, font_size: float):
        """Updates the engine with the current font context."""
        font_name_str = str(font_name)

        self.current_pdf_font_name = font_name_str
        self.active_font_size = font_size

        # Find applicable rule
        # Note: We strip the leading slash for matching, following PDF convention
        clean_name = font_name_str.replace("/", "")
        self.active_rule = next(
            (
                r
                for r in self.config.rules
                if r.source_font_name.replace("/", "") == clean_name
            ),
            None,
        )

        # Reset per-font state
        self.active_wrapper = None
        self.active_target_slot_map = None
        self.active_target_char_map = None
        self.active_source_hex_map = {}
        self.current_type3_scale_factor = 1.0

        if self.active_rule:
            self.active_wrapper = self.target_font_cache.get(
                self.active_rule.target_font_file
            )

            # Helper: Build all encoding maps (Slot, Char, Hex)
            self._initialize_encoding_maps()

            # Handle Type 3 Scaling
            source_data = self.source_font_cache.get(f"/{clean_name}")

            if source_data and getattr(source_data, "is_type3", False):
                scale = getattr(source_data, "type3_design_height", 0)
                if scale > 0:
                    self.current_type3_scale_factor = scale
                    font_size = font_size * scale
                    self.active_font_size = font_size

            # Apply User Override (fontsize_scaling_percentage)
            user_scale = self.active_rule.fontsize_scaling_percentage
            if abs(user_scale - 100.0) > 0.001:
                self.active_font_size = self.active_font_size * (user_scale / 100.0)

        font_name_to_return = clean_name
        if self.active_rule is not None:
            font_name_to_return = self.active_rule.target_font_name.lstrip("/")
        return font_name_to_return, self.active_font_size

    def _initialize_encoding_maps(self):
        """
        Builds the three encoding maps used for replacement:
        1. active_target_slot_map: Char (str) -> Slot (int) for rewriting
        2. active_source_hex_map: Source Byte (int) -> Char (str) from Rule Hex Keys
        3. active_target_char_map: Slot (int) -> Char (str) for width calculation
        """
        # 1. Initialize Map from Global Config
        raw_map = self.custom_encoding_maps.get(self.active_rule.target_font_file, {})
        self.active_target_slot_map = {}

        # Normalize map to ensure Char (str) -> Slot (int)
        if raw_map:
            for k, v in raw_map.items():
                if isinstance(k, int) and isinstance(v, str):
                    self.active_target_slot_map[v] = k
                else:
                    self.active_target_slot_map[k] = v

        # 2. Process Rule-Specific Map
        if self.active_rule.encoding_map:
            # Merge into Target Map (Char -> Slot)
            for k, v in self.active_rule.encoding_map.items():
                self.active_target_slot_map[k] = v

            # Populate Hex Map (Source Byte -> Char)
            for k, v in self.active_rule.encoding_map.items():
                try:
                    k_int = int(k, 16)
                    self.active_source_hex_map[k_int] = v
                except (ValueError, TypeError):
                    pass

        # 3. Build Inverse Map for Width Calculation (Slot -> Char)
        if self.active_target_slot_map:
            self.active_target_char_map = {
                v: k for k, v in self.active_target_slot_map.items()
            }

    def _get_source_font_metrics(
        self,
    ) -> Optional[Tuple[Any, int, int, List[float], float]]:
        """
        Extracts metrics (Widths, FirstChar, LastChar, FontMatrix, MissingWidth).
        """
        if not self.current_pdf_font_name:
            return None

        # Resolve font key (try with and without slash)
        font_key = f"/{self.current_pdf_font_name}"
        if font_key not in self.source_pikepdf_fonts:
            font_key = self.current_pdf_font_name

        if font_key not in self.source_pikepdf_fonts:
            return None

        font_obj = self.source_pikepdf_fonts[font_key]

        # Verify required fields
        if not (
            "/Widths" in font_obj
            and "/FirstChar" in font_obj
            and "/LastChar" in font_obj
        ):
            logger.warning(
                "Failed to calculate source width: missing metrics in %s", font_obj
            )
            return None

        widths = font_obj["/Widths"]
        first_char = int(font_obj["/FirstChar"])
        last_char = int(font_obj["/LastChar"])

        # Default PDF FontMatrix (1/1000 standard scaling)
        font_matrix = [0.001, 0, 0, 0.001, 0, 0]
        if "/FontMatrix" in font_obj:
            font_matrix = [float(x) for x in font_obj["/FontMatrix"]]

        # Extract MissingWidth
        missing_width = 0.0
        if "/FontDescriptor" in font_obj:
            fd = font_obj["/FontDescriptor"]
            if "/MissingWidth" in fd:
                try:
                    missing_width = float(fd["/MissingWidth"])
                except (ValueError, TypeError):
                    pass

        return widths, first_char, last_char, font_matrix, missing_width

    def calculate_source_width_fallback(
        self, op: str, operands: List[Any], source_state_dict: Dict[str, Any]
    ) -> float:
        # pylint: disable=too-many-arguments, too-many-positional-arguments
        """
        Calculates source text width using the source PDF font metrics dictionary.
        Used as a fallback when geometric distance cannot be measured.
        """
        if op not in ["Tj", "TJ"]:
            return 0.0

        metrics = self._get_source_font_metrics()
        if not metrics:
            return 0.0

        items = operands[0] if op == "TJ" else [operands[0]]
        glyph_width_sum, gap_sum, char_count = self._sum_source_widths(items, metrics)

        # Pass metrics[3] (font_matrix) to finalize
        return self._finalize_source_width(
            glyph_width_sum, gap_sum, char_count, metrics[3], source_state_dict
        )

    def _sum_source_widths(self, items, metrics) -> Tuple[float, float, int]:
        """Calculates raw glyph widths and gaps from operand items."""
        glyph_width_sum = 0.0
        gap_sum = 0.0
        char_count = 0

        for item in items:
            if isinstance(item, (int, float, Decimal)):
                gap_sum += float(item)
            else:
                w, count = self._compute_source_string_width(item, metrics)
                glyph_width_sum += w
                char_count += count

        return glyph_width_sum, gap_sum, char_count

    def _compute_source_string_width(self, item, metrics) -> Tuple[float, int]:
        """Calculates the width sum of characters in a string item."""
        widths, first_char, last_char, _, missing_width = metrics
        s_bytes = extract_string_bytes(item)
        width_sum = 0.0

        for b in s_bytes:
            if first_char <= b <= last_char:
                idx = b - first_char
                if 0 <= idx < len(widths):
                    width_sum += float(widths[idx])
                else:
                    width_sum += missing_width
            else:
                # Use MissingWidth for out-of-range characters
                width_sum += missing_width

        return width_sum, len(s_bytes)

    def _finalize_source_width(
        self, glyph_width, gap_width, char_count, font_matrix, state
    ) -> float:
        """Applies scaling matrices to the raw width sums."""
        s_tstate = state["tstate"]
        s_font_size = s_tstate.fontsize
        s_tm_scale_x = s_tstate.matrix[0]
        s_ctm = state["ctm"]
        s_ctm_scale_x = s_ctm[0]

        glyph_scale = abs(s_font_size * s_tm_scale_x * s_ctm_scale_x * font_matrix[0])
        gap_scale = abs(s_font_size * s_tm_scale_x * s_ctm_scale_x) / 1000.0

        final_width = (glyph_width * glyph_scale) - (gap_width * gap_scale)

        # Sanity check: if calculation seems broken (too small), use fallback estimate
        estimated_em_width = abs(
            s_font_size * s_tm_scale_x * s_ctm_scale_x * self.current_type3_scale_factor
        )
        if char_count > 0 and final_width < (0.1 * estimated_em_width * char_count):
            final_width = 0.5 * estimated_em_width * char_count

        return final_width

    def calculate_target_visual_width(self, op: str, operands: List[Any]) -> float:
        """
        Calculates the visual width of the text using the target font metrics.
        """
        if not self.active_wrapper:
            return 1.0

        items = operands[0] if op == "TJ" else [operands[0]]
        total_width_pts = 0.0

        for item in items:
            total_width_pts += self._process_target_item(item)

        return total_width_pts

    def _process_target_item(self, item: Any) -> float:
        """Calculates width contribution (pts) of a single target item (num or str)."""
        if isinstance(item, (int, float, Decimal)):
            return -(float(item) / 1000.0) * self.active_font_size

        return self._compute_target_string_width(item)

    def _compute_target_string_width(self, item: Any) -> float:
        """Calculates total width (pts) of a string using target font metrics."""
        s_bytes = extract_string_bytes(item)
        width_pts = 0.0

        for b in s_bytes:
            target_char = self._map_target_byte_to_char(b)

            if not target_char:
                # Only fallback to ASCII range. High-bit chars (128-255)
                # are risky to map via chr() as they depend on the font's encoding.
                target_char = chr(b) if 32 <= b <= 126 else None

            if target_char:
                try:
                    w_norm = self.active_wrapper.get_char_width(target_char)
                    width_pts += (w_norm / 1000.0) * self.active_font_size
                except ValueError as exc:
                    raise exc

        return width_pts

    def rewrite_text_operands(self, op: str, operands: List[Any]) -> List[Any]:
        """
        Rewrites the text bytes in the operands using the active rule's mapping.
        """
        if not self.active_rule or not self.active_target_slot_map:
            return operands

        new_operands = []

        # Handle TJ vs Tj
        if op == "TJ":
            source_array = operands[0]
            new_array = []
            for item in source_array:
                if isinstance(item, (int, float, Decimal)):
                    new_array.append(item)
                else:
                    new_array.append(self._rewrite_string(item))
            new_operands.append(new_array)
        else:
            # Tj, ', "
            new_operands.append(self._rewrite_string(operands[0]))
            # Append other operands if any (Tj only has 1, ' has 1, " has 3)
            if len(operands) > 1:
                new_operands.extend(operands[1:])

        return new_operands

    def _rewrite_string(self, item: Any) -> pikepdf.String:
        """Rewrites a single string item."""
        source_bytes = extract_string_bytes(item)
        target_bytes = bytearray()

        for b in source_bytes:
            # Map source byte -> Target Slot
            target_slot, _ = self._map_source_byte(b)
            if target_slot is not None:
                target_bytes.append(target_slot)
            else:
                # Fallback: keep original or map to 0?
                # Keeping original risks garbage if font doesn't match
                target_bytes.append(b)

        ret = pikepdf.String(bytes(target_bytes))
        return ret

    def _map_source_byte(self, b: int) -> Tuple[Optional[int], int]:
        """
        Maps source byte -> Target Slot.
        """
        if not self.active_rule or not self.active_target_slot_map:
            logger.warning("mapping source byte: missing mapping data")
            return None, b

        # 1. Look up in specialized Hex Map (Source Byte -> Char)
        # This covers cases where rule.encoding_map uses hex keys (e.g., "41": "A")
        char_b = self.active_source_hex_map.get(b)

        # 2. Fallback to Identity (ASCII/Latin1)
        # This covers standard cases (e.g., source byte 65 is just 'A')
        if char_b is None:
            try:
                char_b = chr(b)
            except (ValueError, OverflowError):
                pass

        # 3. Look up in Target Map (Char -> Slot)
        ret = None
        if char_b:
            try:
                ret = self.active_target_slot_map[char_b]
            except KeyError:
                pass

        return ret, b

    def _map_target_byte_to_char(self, b: int) -> Optional[str]:
        """
        Maps a byte from the target font encoding back to a character.
        Used for width calculation.
        """
        if self.active_target_char_map:
            return self.active_target_char_map.get(b)
        return None
