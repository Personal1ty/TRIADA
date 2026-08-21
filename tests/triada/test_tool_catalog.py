from app.tools.catalog import AUTO_TOOL_CATALOG


def test_auto_tool_catalog_contains_supported_read_only_tools():
    assert "git" in AUTO_TOOL_CATALOG
    assert "ls" in AUTO_TOOL_CATALOG
    assert "rg" in AUTO_TOOL_CATALOG
    assert "cat" in AUTO_TOOL_CATALOG
    assert "write_file" not in AUTO_TOOL_CATALOG
    assert "apply_patch" not in AUTO_TOOL_CATALOG
