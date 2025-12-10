from unittest.mock import MagicMock

from pikepdf import Name, Operator

from swapfont.models import ReplacementConfig, ReplacementRule

from ..conftest import build_test_editor


def test_stream_editor_outputs_replaced_font_operands():
    """
    Verifies that the StreamEditor writes the replacement font name and size
    to the output stream when processing a 'Tf' operator for a Type 3 font.

    Regression Check: Previously, the editor updated internal state but
    passed the original operands (e.g., /R20) through to the output.
    """
    # 1. Configuration
    # We define a rule to replace '/Type3Source' with '/ReplacedFont'
    rule = ReplacementRule(
        source_font_name="/Type3Source",
        target_font_file="dummy.ttf",
        target_font_name="ReplacedFont",
        strategy="scale_to_fit",
    )
    config = ReplacementConfig(rules=[rule])

    # # 2. Setup Editor with Mocks
    # # We mock the target cache to ensure the editor believes the font is loaded
    mock_wrapper = MagicMock()
    # target_cache = {"dummy.ttf": mock_wrapper}

    editor, layout_engine = build_test_editor([], config=config)
    # editor = StreamEditor(
    #     source_iterator=[],
    #     config=config,
    #     target_font_cache=target_cache,
    #     custom_encoding_maps={},
    #     source_font_cache={},
    #     source_pikepdf_fonts={},
    # )

    # 3. Mock LayoutEngine Behavior
    # The LayoutEngine is responsible for determining the *correct* new name and size.
    # We mock it to ensure we are strictly testing the StreamEditor's ability
    # to use that result.

    # Simulate: set_active_font("/Type3Source", 10.0) -> returns ("ReplacedFont", 12.0)
    layout_engine.set_active_font = MagicMock(return_value=("ReplacedFont", 12.0))

    # Simulate: The layout engine has successfully activated the wrapper
    layout_engine.active_wrapper = mock_wrapper
    layout_engine.active_target_slot_map = {}

    # 4. Simulate Input Operation
    # Input PDF command: /Type3Source 10 Tf
    input_operands = [Name("/Type3Source"), 10]

    mock_context = MagicMock()
    mock_context.output = MagicMock()  # The tracker

    # 5. Execute Handler with the context
    # This invokes the logic inside StreamEditor that handles 'Tf'
    output_ops = editor.handler.handle_operator("Tf", input_operands, mock_context, b"")

    # 6. Assertions
    assert len(output_ops) == 1, "Expected exactly one output operation for Tf"

    operands, operator = output_ops[0]

    # Check Operator
    assert operator == Operator("Tf")

    # Check Font Name Replacement
    # The output MUST be the target name, not the source name
    assert operands[0] == Name("/ReplacedFont"), (
        f"Regression: Font name was not replaced.\n"
        f"Expected: /ReplacedFont\n"
        f"Actual:   {operands[0]}"
    )

    # Check Font Size
    # The output MUST use the size returned by the layout engine
    assert operands[1] == 12.0, (
        f"Regression: Font size was not updated.\n"
        f"Expected: 12.0\n"
        f"Actual:   {operands[1]}"
    )

    # Verify interaction with LayoutEngine
    # Ensure the editor actually asked the engine for the correct font/size
    layout_engine.set_active_font.assert_called_once_with(Name("/Type3Source"), 10.0)
