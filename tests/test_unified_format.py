import pytest

from kcd_gfx_toolbox.diff.unified_format import (
    unidiff_context_line,
    unidiff_deletion_line,
    unidiff_file_header,
    unidiff_hunk_header,
    unidiff_insertion_line,
)


def test_unidiff_file_header_renders_side_a_with_a_prefix():
    assert unidiff_file_header("foo/bar.pcode", "a") == "--- a/foo/bar.pcode"


def test_unidiff_file_header_renders_side_b_with_b_prefix():
    assert unidiff_file_header("foo/bar.pcode", "b") == "+++ b/foo/bar.pcode"


def test_unidiff_file_header_uses_dev_null_when_path_is_none_on_side_a():
    assert unidiff_file_header(None, "a") == "--- /dev/null"


def test_unidiff_file_header_uses_dev_null_when_path_is_none_on_side_b():
    assert unidiff_file_header(None, "b") == "+++ /dev/null"


def test_unidiff_file_header_rejects_invalid_side():
    with pytest.raises(ValueError, match="Invalid side 'x'"):
        unidiff_file_header("foo", "x")  # pyright: ignore[reportArgumentType]


def test_unidiff_hunk_header_formats_typical_range():
    assert unidiff_hunk_header(420, 69, 13, 12) == "@@ -420,69 +13,12 @@"


def test_unidiff_deletion_line_prepends_minus():
    assert unidiff_deletion_line("foo") == "-foo"


def test_unidiff_deletion_line_handles_empty_line():
    assert unidiff_deletion_line("") == "-"


def test_unidiff_insertion_line_prepends_plus():
    assert unidiff_insertion_line("foo") == "+foo"


def test_unidiff_insertion_line_handles_empty_line():
    assert unidiff_insertion_line("") == "+"


def test_unidiff_context_line_prepends_space():
    assert unidiff_context_line("foo") == " foo"


def test_unidiff_context_line_handles_empty_line():
    assert unidiff_context_line("") == " "
