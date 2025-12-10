# src/swapfont/models.py
"""
Data models for swapfont configuration and font analysis.
"""

import logging
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Optional, Set, Union

import pikepdf
from fontTools.ttLib import TTLibError
from pikepdf import parse_content_stream
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)

# Standard PDF operators that display text
TEXT_SHOWING_OPERATORS = ["Tj", "TJ", "'", '"']


def resolve_unicode_name(val: str) -> str:
    """
    Resolves a descriptive string (e.g. "LATIN SMALL LIGATURE FI")
    to its unicode character (e.g. "\ufb01").
    Returns the original string if it is already short or lookup fails.
    """
    if len(val) <= 1:
        return val

    clean_val = val.strip().upper().replace("-", " ")

    # 1. Try Exact Lookup
    try:
        return unicodedata.lookup(clean_val)
    except (KeyError, ValueError):
        pass

    # 2. Try Fuzzy "Ligature" Lookup
    if "LIGATURE" in clean_val:
        try:
            # Handle "ligature fi" -> "LATIN SMALL LIGATURE FI"
            base = clean_val.replace("LIGATURE", "").strip()
            return unicodedata.lookup(f"LATIN SMALL LIGATURE {base}")
        except (KeyError, ValueError):
            pass

        try:
            # Handle "latin small ligature fi" variations
            return unicodedata.lookup(f"LATIN SMALL {clean_val}")
        except (KeyError, ValueError):
            pass

    # 3. Warn but return original
    if " " in clean_val:
        logger.warning(
            "Could not resolve unicode description '%s'. Using as literal.", val
        )

    return val


class SmartEncodingMap(dict):
    """
    A dictionary that preserves original keys (strings/hex) but allows robust lookups.
    """

    def __getitem__(self, key: Any) -> Any:
        # 1. Fast Path: Direct lookup
        if super().__contains__(key):
            return super().__getitem__(key)

        # 2. Integer Lookup Fallback
        if isinstance(key, int):
            candidates = [
                f"0x{key:02x}",  # "0x0c"
                f"0x{key:x}",  # "0xc"
                f"0X{key:02X}",  # "0X0C"
                f"0X{key:X}",  # "0XC"
                str(key),  # "12"
            ]
            for cand in candidates:
                if super().__contains__(cand):
                    return super().__getitem__(cand)

        raise KeyError(key)


def _to_smart_map(v: Any) -> SmartEncodingMap:
    """Validator to ensure input is wrapped in SmartEncodingMap."""
    return SmartEncodingMap(v) if v else SmartEncodingMap()


# Define a custom field type for Pydantic
SmartEncodingMapField = Annotated[
    SmartEncodingMap,
    BeforeValidator(_to_smart_map),
    PlainSerializer(dict, return_type=Dict[str, str]),
]


@dataclass
class StrategyOptions:
    """
    Configuration options for the replacement strategy.
    """

    method: str = "Tz"
    max_scale: float = 105.0
    min_scale: float = 95.0

    def __post_init__(self):
        pass


class ReplacementRule(BaseModel):
    """Defines a single font replacement operation."""

    source_font_name: str
    source_base_font: Optional[str] = None
    source_type: str = "N/A"
    is_embedded: bool = False
    point_sizes: List[float] = Field(default_factory=list)

    target_font_file: str
    target_font_name: str = "NewFont"
    strategy: str = "scale_to_fit"
    preserve_unmapped: bool = False

    encoding_map: SmartEncodingMapField = Field(default_factory=SmartEncodingMap)

    width_overrides: Dict[str, float] = {}

    strategy_options: Union[StrategyOptions, Dict[str, Any]] = Field(
        default_factory=StrategyOptions
    )

    hybrid_max_char_spacing: float = 0.0

    # NEW: Manual scaling override
    fontsize_scaling_percentage: float = 100.0

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    @field_validator("encoding_map", mode="before")
    @classmethod
    def resolve_encoding_descriptions(cls, v):
        """
        Pre-processes the encoding map to resolve Unicode descriptions.
        """
        if not v:
            return v

        resolved_map = {}
        for key, val in v.items():
            new_key = key
            if (
                isinstance(key, str)
                and len(key) > 1
                and not key.lower().startswith("0x")
                and not key.isdigit()
            ):
                new_key = resolve_unicode_name(key)

            new_val = val
            if isinstance(val, str):
                new_val = resolve_unicode_name(val)

            resolved_map[new_key] = new_val

        return resolved_map


class ReplacementConfig(BaseModel):
    """
    Top-level configuration container.
    """

    description: str = ""
    rules: List[ReplacementRule] = []

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def check_legacy_keys(cls, data: Any) -> Any:
        """Validates the input configuration for deprecated keys."""
        if isinstance(data, dict):
            if "replacements" in data and "rules" not in data:
                data["rules"] = data["replacements"]
        return data


class FontData:
    # pylint: disable=too-many-instance-attributes
    """
    Stores all necessary inspection data for a single font.
    Tracks page usage, metrics, and Type 3 specific data.
    """

    def __init__(self, source_name: str, font_dict: pikepdf.Dictionary):
        self.source_name = source_name
        self.font_dict = font_dict

        try:
            self.font_type = str(font_dict.get("/Subtype", "Unknown"))
            self.base_font = str(font_dict.get("/BaseFont", "N/A"))
        except TTLibError as e:
            logger.debug("Error reading basic font info for %s: %s", source_name, e)
            self.font_type = "Error"
            self.base_font = "Error"

        self.is_embedded = False
        self.pages_used: Set[int] = set()
        self.point_sizes: Set[float] = set()

        self.used_char_codes: Dict[int, float] = {}
        self.char_pages: Dict[int, Set[int]] = defaultdict(set)
        self.char_names: Dict[int, str] = {}

        self.widths: List[float] = []
        self.first_char: int = 0
        self.missing_width: float = 0.0
        self.font_matrix: List[float] = [0.001, 0, 0, 0.001, 0, 0]
        self.font_bbox: Optional[List[float]] = None

        self.type3_design_height: float = 0.0
        self.type3_design_width: float = 0.0
        self.is_type3: bool = False
        try:
            self.is_type3 = font_dict.get("/Subtype") == pikepdf.Name("/Type3")
            if self.is_type3:
                self._extract_initial_bbox(font_dict)
        except TTLibError:
            pass

        logger.debug(
            "Initializing FontData for %s (Type: %s, Base: %s)",
            self.source_name,
            self.font_type,
            self.base_font,
        )

        self._check_embedded(font_dict)
        self._extract_metrics(font_dict)

        if self.font_type == "/Type3":
            self._extract_type3_metrics(font_dict)

    def __repr__(self):
        return f"<FontData {self.source_name} type={self.font_type}>"

    def _extract_initial_bbox(self, font_dict):
        font_bbox = font_dict.get("/FontBBox")
        if font_bbox and len(font_bbox) == 4:
            try:
                self.type3_design_height = float(font_bbox[3]) - float(font_bbox[1])
            except (TypeError, ValueError):
                pass

    def _check_embedded(self, font_dict: pikepdf.Dictionary):
        """Checks if the font contains embedding streams."""
        font_descriptor = font_dict.get("/FontDescriptor")
        if font_descriptor and isinstance(font_descriptor, pikepdf.Dictionary):
            if (
                font_descriptor.get("/FontFile")
                or font_descriptor.get("/FontFile2")
                or font_descriptor.get("/FontFile3")
            ):
                self.is_embedded = True

            if "/MissingWidth" in font_descriptor:
                try:
                    self.missing_width = float(font_descriptor["/MissingWidth"])
                except (ValueError, TypeError):
                    pass

            if "/FontBBox" in font_descriptor:
                try:
                    self.font_bbox = [float(x) for x in font_descriptor["/FontBBox"]]
                except (ValueError, TypeError):
                    pass

        if self.font_type == "/Type3":
            self.is_embedded = True
            if "/FontBBox" in font_dict:
                try:
                    self.font_bbox = [float(x) for x in font_dict["/FontBBox"]]
                except (ValueError, TypeError):
                    pass

    def _extract_metrics(self, font_dict: pikepdf.Dictionary):
        """Extracts standard PDF font metrics (Widths, FirstChar)."""
        self._extract_font_matrix(font_dict)
        self._extract_widths(font_dict)
        self._extract_encoding(font_dict)

    def _extract_font_matrix(self, font_dict: pikepdf.Dictionary):
        if "/FontMatrix" in font_dict:
            try:
                fm = [float(x) for x in font_dict["/FontMatrix"]]
                if len(fm) == 6:
                    self.font_matrix = fm
            except (ValueError, TypeError):
                pass

    def _extract_widths(self, font_dict: pikepdf.Dictionary):
        norm_factor = 1.0
        if self.font_matrix[0] > 0:
            norm_factor = self.font_matrix[0] * 1000.0

        if "/FirstChar" in font_dict and "/Widths" in font_dict:
            try:
                self.first_char = int(font_dict["/FirstChar"])
                self.widths = [float(w) * norm_factor for w in font_dict["/Widths"]]
                logger.debug(
                    "Extracted widths for %s: FirstChar=%d, Count=%d, NormFactor=%.3f",
                    self.source_name,
                    self.first_char,
                    len(self.widths),
                    norm_factor,
                )
            except (ValueError, TypeError):
                logger.warning("Error parsing width metrics for %s", self.source_name)
        else:
            logger.debug("Font %s missing standard width metrics.", self.source_name)

    def _extract_encoding(self, font_dict: pikepdf.Dictionary):
        encoding_obj = font_dict.get("/Encoding")
        if encoding_obj is None:
            return

        if isinstance(encoding_obj, pikepdf.Dictionary):
            if "/Differences" in encoding_obj:
                diff_arr = encoding_obj["/Differences"]
                current_code = -1
                for item in diff_arr:
                    if isinstance(item, int):
                        current_code = item
                    elif isinstance(item, pikepdf.Name) and current_code != -1:
                        self.char_names[current_code] = str(item)
                        current_code += 1
        elif isinstance(encoding_obj, pikepdf.Name):
            pass

    def _extract_type3_metrics(self, font_dict: pikepdf.Dictionary):
        """
        Parses ALL CharProcs to estimate the TRUE Em-Height of the font.
        """
        if "/CharProcs" not in font_dict:
            return

        char_procs = font_dict["/CharProcs"]
        if not hasattr(char_procs, "keys") or not char_procs:
            return

        bounds = {
            "min_llx": float("inf"),
            "max_urx": float("-inf"),
            "min_lly": float("inf"),
            "max_ury": float("-inf"),
            "valid_samples": 0,
        }

        # Scan ALL glyphs to ensure deterministic sizing based on true maximums
        all_keys = list(char_procs.keys())

        logger.debug("T3: Scanning %d CharProcs for metrics...", len(all_keys))

        for key in all_keys:
            self._process_charproc_sample(char_procs[key], key, bounds)

        if bounds["valid_samples"] > 0 and bounds["max_ury"] > bounds["min_lly"]:
            self.type3_design_width = bounds["max_urx"] - bounds["min_llx"]
            self.type3_design_height = bounds["max_ury"] - bounds["min_lly"]
            logger.debug(
                "Est. Type 3 Design Height for %s: %.2f (Samples: %d)",
                self.source_name,
                self.type3_design_height,
                bounds["valid_samples"],
            )

    def _process_charproc_sample(self, stream_obj, key, bounds):
        """Parses a single CharProc stream to find its bounding box."""
        try:
            instructions = parse_content_stream(stream_obj)
            for operands, operator in instructions:
                # 'd1' operator defines glyph width and bounding box
                if operator.unparse() == b"d1":
                    self._update_bounds_from_operands(operands, bounds)
                    break

        except (pikepdf.PdfError, RuntimeError) as parsing_error:
            logger.warning("T3: Robust parsing failed for %s: %s", key, parsing_error)

    def _update_bounds_from_operands(self, operands, bounds):
        """Updates bounds dictionary from d1 operands."""
        if len(operands) < 6:
            return
        try:
            llx, lly, urx, ury = map(float, operands[2:6])
            bounds["min_llx"] = min(bounds["min_llx"], llx)
            bounds["max_urx"] = max(bounds["max_urx"], urx)
            bounds["min_lly"] = min(bounds["min_lly"], lly)
            bounds["max_ury"] = max(bounds["max_ury"], ury)
            bounds["valid_samples"] += 1
        except (ValueError, TypeError):
            pass

    def get_width(self, code: int) -> float:
        """Looks up the source font width for a character code."""
        if self.widths and code >= self.first_char:
            width_index = code - self.first_char
            if width_index < len(self.widths):
                return self.widths[width_index]

        if self.missing_width > 0:
            return self.missing_width

        return 0.0
