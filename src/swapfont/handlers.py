# src/swapfont/handlers.py
import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

import numpy as np
import pikepdf
from pdfbeaver import (
    HandlerRegistry,
    NormalizedOperand,
    StreamContext,
    extract_text_position,
    normalize_pdf_operand,
)
from pikepdf import Operator

if TYPE_CHECKING:
    from .engines.layout_engine import LayoutEngine

logger = logging.getLogger(__name__)

# --- Testable Helper Functions (Module Level) ---


def scale_tj_array(active_operands, input_state, layout_engine):
    """Rescales values in a TJ array based on font size differences."""
    source_fs = 1.0
    if input_state and input_state.get("tstate"):
        source_fs = getattr(input_state["tstate"], "fontsize", 1.0)

    target_fs = layout_engine.active_font_size
    if target_fs < 1e-3:
        target_fs = 1.0
    gap_scale = source_fs / target_fs

    new_array = []
    for item in active_operands[0]:
        if isinstance(item, (int, float, Decimal)):
            new_array.append(float(item) * gap_scale)
        else:
            new_array.append(item)
    active_operands[0] = pikepdf.Array(new_array)


def calculate_scale_percent(
    op, active_operands, original_operands, input_state, start_pos, layout_engine
):  # pylint: disable=too-many-arguments,too-many-positional-arguments
    """
    Calculates the horizontal scaling percentage required to match width.

    Arguments are numerous because this calculation depends on:
    - The operation type (Tj vs TJ)
    - The operands (text data)
    - The input state (font size, char spacing)
    - The layout engine (target font metrics)
    """
    target_width = layout_engine.calculate_target_visual_width(op, active_operands)
    input_end_pos = extract_text_position(input_state)
    input_width = np.linalg.norm(input_end_pos[:2] - start_pos[:2])

    if input_width < 0.001:
        input_width = layout_engine.calculate_source_width_fallback(
            op, original_operands, input_state
        )

    scale_percent = 100.0
    if input_width > 1e-3 and target_width > 1e-3:
        scale_percent = (input_width / target_width) * 100.0

        # Defaults: Liberal (50% - 200%)
        # "Make it fit, even if it looks a bit squashed/stretched."
        limit_min = 50.0
        limit_max = 200.0

        # Read config (if present)
        if layout_engine.active_rule:
            opts = layout_engine.active_rule.strategy_options

            # Helper to extract values safely
            user_min = None
            user_max = None

            if hasattr(opts, "min_scale"):
                user_min = float(opts.min_scale)
                user_max = float(opts.max_scale)
            elif isinstance(opts, dict):
                user_min = float(opts.get("min_scale", 50.0))
                user_max = float(opts.get("max_scale", 200.0))

            # Apply user config (NO GUARDRAILS, just basic sanity > 0)
            if user_min is not None and user_min > 0:
                limit_min = user_min

            if user_max is not None and user_max > user_min:
                limit_max = user_max

        # Final Clamp
        scale_percent = max(limit_min, min(scale_percent, limit_max))

    return scale_percent


def get_type3_matrix_ops(
    output_state: Any, layout_engine: "LayoutEngine"
) -> Tuple[bool, Dict[str, Tuple]]:
    """
    Generates Type 3 font matrix inversion operations if needed.

    If the text is visually flipped (negative Y scale in TRM), this generates
    Tm operations to un-flip it for the replacement font (which is standard/upright).
    """
    is_t3 = abs(getattr(layout_engine, "current_type3_scale_factor", 1.0) - 1.0) > 1e-5
    if not is_t3:
        return False, {}

    # 1. DETECT visual flip using the Text Rendering Matrix (TRM = Tm x CTM)
    _, trm = output_state.get_matrices()
    if trm[1, 1] >= 0:
        return False, {}

    # 2. FIX the flip using the Text Matrix (Tm) directly.
    current_tm = output_state.textstate.matrix

    apply_vals = list(current_tm)
    apply_vals[3] = abs(apply_vals[3])

    apply_op = (
        [float(x) for x in apply_vals],
        Operator("Tm"),
    )

    restore_op = (
        [float(x) for x in current_tm],
        Operator("Tm"),
    )
    # breakpoint()
    return True, {"apply": apply_op, "restore": restore_op}


def generate_text_ops(op, active_operands, scale_percent, output_state, layout_engine):
    """Generates a list of PDF operators to handle text operations,
    including potential scaling and matrix transformations for Type 3
    fonts.

    This function constructs the necessary operations to adjust the
    text rendering, including:

    - Applying matrix inversion for Type 3 fonts (if required).

    - Scaling the text width using the 'Tz' operator if the scaling
      percentage differs from 100%.

    - Restoring the original matrix after the text operation, if Type
      3 font inversion was applied.

    Args:

        op (str): The text operator (e.g., "Tj", "TJ", "'", '"') to
        process.

        active_operands (List[NormalizedOperand]): The operands
            associated with the operator, typically containing the
            text and other parameters.

        scale_percent (float): The percentage by which the text needs
            to be scaled, calculated based on the difference between
            the input text width and the target width. This is applied
            using the 'Tz' operator in the PDF.

        output_state (Any): The current state tracker that contains
            the textstate and matrix transformations.

        layout_engine (LayoutEngine): The layout engine that manages
        font and scale information.

    Returns:

        List[Tuple[List[float], Operator]]: A list of tuples where
        each tuple contains an operand list and an operator. These
        tuples correspond to the PDF operators required to render the
        text, potentially including Tm (text matrix), Tz (text
        scaling), and others.

    """
    ops = []
    is_t3_inv, tm_ops = get_type3_matrix_ops(output_state, layout_engine)

    if is_t3_inv:
        ops.append(tm_ops["apply"])

    if abs(scale_percent - 100.0) > 1.0:
        ops.append(([round(scale_percent, 3)], Operator("Tz")))

    ops.append((active_operands, Operator(op)))

    if abs(scale_percent - 100.0) > 1.0:
        ops.append(([100], Operator("Tz")))

    if is_t3_inv:
        ops.append(tm_ops["restore"])

    return ops


def create_font_replacer_handler(layout_engine: "LayoutEngine") -> HandlerRegistry:
    """
    Factory that builds a HandlerRegistry configured for Font Replacement.
    """
    registry = HandlerRegistry()

    @registry.register("Tf")
    def handle_set_font(operands: List[NormalizedOperand], context: StreamContext):
        try:
            assert len(operands) == 2
            _ = float(operands[1])
        except (TypeError, AssertionError, ValueError):
            logging.warning("Could not set font for operands=%s", operands)
            return [(operands, Operator("Tf"))]
        final_name, final_size = layout_engine.set_active_font(
            normalize_pdf_operand(operands[0]), float(operands[1])
        )

        # Access tracker dynamically from context
        tracker = context.tracker

        if layout_engine.active_wrapper:
            if hasattr(tracker, "set_active_proxy"):
                tracker.set_active_proxy(
                    layout_engine.active_wrapper,
                    layout_engine.active_target_slot_map,
                )

        return [([pikepdf.Name(f"/{final_name}"), final_size], Operator("Tf"))]

    @registry.register("Tj", "TJ", "'", '"')
    def handle_text_show(
        operands: List[NormalizedOperand], context: StreamContext, op: str
    ):
        if not layout_engine.active_rule:
            return registry.PASS_THROUGH

        start_pos = np.array([0.0, 0.0, 1.0])
        if context.pre_input:
            start_pos = extract_text_position(context.pre_input)

        active_operands = layout_engine.rewrite_text_operands(op, operands)

        if op == "TJ":
            scale_tj_array(active_operands, context.post_input, layout_engine)

        scale_percent = calculate_scale_percent(
            op, active_operands, operands, context.post_input, start_pos, layout_engine
        )

        return generate_text_ops(
            op, active_operands, scale_percent, context.tracker, layout_engine
        )

    return registry
