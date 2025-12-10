import json

from click.testing import CliRunner

from swapfont.glue_tool import main


def test_glue_tool_end_to_end(tmp_path):
    """
    Test that the glue tool correctly reads inspector output and user mapping,
    producing the expected replacement rules.
    """
    runner = CliRunner()

    # 1. Prepare Input Files
    inspector_path = tmp_path / "inspector.json"
    mapping_path = tmp_path / "mapping.json"
    output_path = tmp_path / "output.json"

    # Mock Inspector Output (similar to what pdf-font-inspector produces)
    inspector_data = {
        "rules": [
            {
                "source_font_name": "/F1",
                "source_base_font": "ArialMT",
                "is_embedded": True,
            },
            {
                "source_font_name": "/F2",
                "source_base_font": "TimesNewRomanPSMT",
                "is_embedded": False,
            },
            {
                "source_font_name": "/F3",
                "source_base_font": "UnknownFont",
                "is_embedded": False,
            },
        ]
    }
    inspector_path.write_text(json.dumps(inspector_data), encoding="utf-8")

    # Mock User Mapping (User says: Replace Arial with MyArial.ttf)
    user_mapping = {
        "ArialMT": "/path/to/MyArial.ttf",
        "TimesNewRomanPSMT": "/path/to/Times.ttf",
    }
    mapping_path.write_text(json.dumps(user_mapping), encoding="utf-8")

    # 2. Run the CLI command
    result = runner.invoke(
        main, [str(inspector_path), str(output_path), "--mapping", str(mapping_path)]
    )

    # 3. Verify execution success
    assert result.exit_code == 0
    assert "Generated 2 rules" in result.output

    # 4. Verify Output JSON content
    assert output_path.exists()
    with open(output_path, "r", encoding="utf-8") as f:
        output_data = json.load(f)

    assert "rules" in output_data
    rules = output_data["rules"]
    assert len(rules) == 2

    # Check Rule 1 (Arial)
    rule1 = next(r for r in rules if r["source_base_font"] == "ArialMT")
    assert rule1["source_font_name"] == "/F1"
    assert rule1["target_font_file"] == "/path/to/MyArial.ttf"
    # Verify the specific name generation logic: f"/F_New_{source_name.strip('/')}"
    assert rule1["target_font_name"] == "/F_New_F1"

    # Check Rule 2 (Times)
    rule2 = next(r for r in rules if r["source_base_font"] == "TimesNewRomanPSMT")
    assert rule2["target_font_file"] == "/path/to/Times.ttf"
    # Verify default strategy options are set
    assert rule2["strategy"] == "scale_to_fit"
    assert rule2["strategy_options"]["method"] == "horizontal_scaling"

    # Check that UnknownFont was skipped (filtering logic)
    assert not any(r["source_base_font"] == "UnknownFont" for r in rules)


def test_glue_tool_no_mapping_provided(tmp_path):
    """Test that providing no mapping file results in zero rules generated."""
    runner = CliRunner()

    inspector_path = tmp_path / "inspector.json"
    output_path = tmp_path / "output.json"

    inspector_data = {
        "rules": [{"source_base_font": "Arial", "source_font_name": "/F1"}]
    }
    inspector_path.write_text(json.dumps(inspector_data), encoding="utf-8")

    # Run without --mapping
    result = runner.invoke(main, [str(inspector_path), str(output_path)])

    assert result.exit_code == 0
    assert "Generated 0 rules" in result.output

    with open(output_path, "r") as f:
        data = json.load(f)
        assert data["rules"] == []


def test_glue_tool_handles_missing_keys_gracefully(tmp_path):
    """
    Test that entries without a 'source_base_font' are safely skipped
    instead of crashing the tool.
    """
    runner = CliRunner()
    inspector_path = tmp_path / "malformed.json"
    mapping_path = tmp_path / "map.json"
    output_path = tmp_path / "out.json"

    # One valid entry, one entry missing 'source_base_font'
    inspector_data = {
        "rules": [
            {"source_font_name": "/F1"},  # Missing base font -> Should be skipped
            {"source_base_font": "Arial", "source_font_name": "/F2"},  # Valid
        ]
    }
    inspector_path.write_text(json.dumps(inspector_data), encoding="utf-8")
    mapping_path.write_text(json.dumps({"Arial": "arial.ttf"}), encoding="utf-8")

    result = runner.invoke(
        main, [str(inspector_path), str(output_path), "--mapping", str(mapping_path)]
    )

    assert result.exit_code == 0
    assert "Generated 1 rules" in result.output

    with open(output_path, "r") as f:
        data = json.load(f)
        assert len(data["rules"]) == 1
        assert data["rules"][0]["source_base_font"] == "Arial"
