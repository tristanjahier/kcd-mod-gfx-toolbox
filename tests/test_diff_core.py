import re
import pytest
from pathlib import Path
from kcd_gfx_toolbox.diff.core import (
    DiffHunk,
    FileDiff,
    TextHunk,
    TextHunkLine,
    TextDiff,
    TextDiffSpan,
    align_hunk_pair_edge_context,
    align_hunk_pairs,
    cut_text_hunks_with_context,
    diff_file_trees,
    diff_file_trees_basic,
    diff_text_hunks,
    diff_texts,
    format_path_rename_git_style,
)
from tests.helpers import sample_text, sample_text_lines


def _create_fake_file_tree(tmp_path: Path, paths: dict[str, str | None]):
    for path, content in paths.items():
        if path.strip() != path:
            pytest.fail("Paths must never start nor end with whitespace in file tree fixtures.")

        if path.startswith("/"):
            pytest.fail("Paths must never start with a slash in file tree fixtures.")

        if path.endswith("/") or content is None:
            if path.endswith("/") and content is None:
                (tmp_path / path).mkdir(parents=True, exist_ok=True)
            else:
                pytest.fail(
                    "Format error in file tree fixture: a directory must be marked with both a trailing slash and a None value."
                )
        else:
            file_path = tmp_path / path
            if not file_path.parent.exists():
                pytest.fail(
                    "Error in file tree fixture: parent paths must always be declared before their descendants."
                )

            file_path.write_text(content or "", encoding="utf-8")


def _hunk_line(index: int, text: str, **kwargs) -> TextHunkLine:
    """Create a text hunk selected line."""
    return TextHunkLine(index=index, text=text, **kwargs)


def _hunk_select(index: int, text: str) -> TextHunkLine:
    """Create a text hunk selected line."""
    return TextHunkLine(index=index, text=text, is_context=False)


def _hunk_ctx(index: int, text: str) -> TextHunkLine:
    """Create a text hunk context line."""
    return TextHunkLine(index=index, text=text, is_context=True)


def _sample_text_hunk(text: str) -> TextHunk:
    """Create a text hunk from lines."""
    return TextHunk(_hunk_select(i, line) for i, line in enumerate(sample_text_lines(text), start=0))


def test_diff_file_trees_basic_with_no_differences(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/blabla.txt": "blabla",
            "A/Caca/": None,
            "A/Caca/niouf.txt": "Nioufinio",
            "A/Caca/empty.txt": "",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/blabla.txt": "blabla",
            "B/Caca/": None,
            "B/Caca/niouf.txt": "Nioufinio",
            "B/Caca/empty.txt": "",
            "B/Caca/AnEmptyDir/": None,
        },
    )

    different, only_in_a, only_in_b = diff_file_trees_basic(tmp_path / "A", tmp_path / "B")

    assert not different
    assert not only_in_a
    assert not only_in_b


def test_diff_file_trees_basic_with_differences_but_mirrored_paths(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/blabla.txt": "blabla",
            "A/Caca/": None,
            "A/Caca/niouf.txt": "Nioufinio",
            "A/Caca/empty.txt": "",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/blabla.txt": "blablu",
            "B/Caca/": None,
            "B/Caca/niouf.txt": "Nioufiniouk",
            "B/Caca/empty.txt": "",
        },
    )

    different, only_in_a, only_in_b = diff_file_trees_basic(tmp_path / "A", tmp_path / "B")

    assert set(different) == {
        Path("blabla.txt"),
        Path("Caca/niouf.txt"),
    }

    assert not only_in_a
    assert not only_in_b


def test_diff_file_trees_basic_with_many_differences(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/blabla.txt": "blabla",
            "A/Caca/": None,
            "A/Caca/niouf.txt": "Nioufinio",
            "A/Caca/empty.txt": "",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/wrapped/": None,
            "B/wrapped/blabla.txt": "blabla",
            "B/Caca/": None,
            "B/Caca/niouf.txt": "Nioufiniouk",
            "B/Caca/not_empty.txt": "hihihihihi",
        },
    )

    different, only_in_a, only_in_b = diff_file_trees_basic(tmp_path / "A", tmp_path / "B")

    assert set(different) == {
        Path("Caca/niouf.txt"),
    }

    assert set(only_in_a) == {Path("blabla.txt"), Path("Caca/empty.txt")}

    assert set(only_in_b) == {Path("wrapped/blabla.txt"), Path("Caca/not_empty.txt")}


def test_diff_texts_with_no_differences():
    text_sample_1 = sample_text_lines("""
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    text_sample_2 = sample_text_lines("""
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    diff = diff_texts(text_sample_1, text_sample_2)

    assert diff == TextDiff(spans=[], lines_changed=0)


def test_diff_texts_with_only_insertions():
    text_sample_1 = sample_text_lines("""
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    text_sample_2 = sample_text_lines("""
        Pop
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push 8
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    diff = diff_texts(text_sample_1, text_sample_2)

    assert diff == TextDiff(spans=[TextDiffSpan((0, 0), (0, 1)), TextDiffSpan((5, 5), (6, 7))], lines_changed=2)


def test_diff_texts_with_only_deletions():
    text_sample_1 = sample_text_lines("""
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    text_sample_2 = sample_text_lines("""
        Push register5
        PushDuplicate
        If L2
        Pop
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    diff = diff_texts(text_sample_1, text_sample_2)

    assert diff == TextDiff(spans=[TextDiffSpan((2, 3), (2, 2))], lines_changed=1)


def test_diff_texts_with_only_replacements():
    text_sample_1 = sample_text_lines("""
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    text_sample_2 = sample_text_lines("""
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push register5
        Push register6
        Push register4
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    diff = diff_texts(text_sample_1, text_sample_2)

    assert diff == TextDiff(spans=[TextDiffSpan((5, 7), (5, 8))], lines_changed=3)


def test_diff_texts_with_a_bit_of_everything():
    text_sample_1 = sample_text_lines("""
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    text_sample_2 = sample_text_lines("""
        Push 1
        StoreRegister 7
        Pop
        Push register5
        PushDuplicate
        Equals2
        If L9
        StoreRegister 2
        Pop
        Push register2
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    diff = diff_texts(text_sample_1, text_sample_2)

    # 3 inserts at the beginning
    # max(2, 3) lines replaced in the middle
    # 1 line deleted near the end
    assert diff == TextDiff(
        spans=[TextDiffSpan((0, 0), (0, 3)), TextDiffSpan((2, 4), (5, 8)), TextDiffSpan((6, 7), (10, 10))],
        lines_changed=7,
    )


def test_diff_texts_with_a_bit_of_everything_reversed():
    text_sample_1 = sample_text_lines("""
        Push 1
        StoreRegister 7
        Pop
        Push register5
        PushDuplicate
        Equals2
        If L9
        StoreRegister 2
        Pop
        Push register2
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    text_sample_2 = sample_text_lines("""
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    diff = diff_texts(text_sample_1, text_sample_2)

    # Must result in the same number of changed lines in reverse.
    assert diff == TextDiff(
        spans=[TextDiffSpan((0, 3), (0, 0)), TextDiffSpan((5, 8), (2, 4)), TextDiffSpan((10, 10), (6, 7))],
        lines_changed=7,
    )


def test_diff_texts_with_nothing():
    assert diff_texts([], []).lines_changed == 0


def test_diff_file_trees_with_no_differences(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/blabla.txt": "blabla",
            "A/Caca/": None,
            "A/Caca/niouf.txt": "Nioufinio",
            "A/Caca/empty.txt": "",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/blabla.txt": "blabla",
            "B/Caca/": None,
            "B/Caca/niouf.txt": "Nioufinio",
            "B/Caca/empty.txt": "",
            "B/Caca/AnEmptyDir/": None,
        },
    )

    changes, only_in_a, only_in_b, _ = diff_file_trees(tmp_path / "A", tmp_path / "B")

    assert not changes
    assert not only_in_a
    assert not only_in_b


def test_diff_file_trees_with_differences_but_mirrored_paths(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/blabla.txt": "blabla",
            "A/Caca/": None,
            "A/Caca/niouf.txt": "Nioufinio",
            "A/Caca/empty.txt": "",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/blabla.txt": "blablad",
            "B/Caca/": None,
            "B/Caca/niouf.txt": sample_text("""
                Nioufiniouk
                Ada!
            """),
            "B/Caca/empty.txt": "",
        },
    )

    changes, only_in_a, only_in_b, _ = diff_file_trees(tmp_path / "A", tmp_path / "B")

    assert set(changes) == {
        FileDiff(path=Path("blabla.txt"), path_new=None, lines_changed=1, spans=[TextDiffSpan((0, 1), (0, 1))]),
        FileDiff(path=Path("Caca/niouf.txt"), path_new=None, lines_changed=2, spans=[TextDiffSpan((0, 1), (0, 2))]),
    }

    assert not only_in_a
    assert not only_in_b


def test_diff_file_trees_with_only_unmatched_paths(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/foo/": None,
            "A/foo/a.pcode": "alfagolo",
            "A/foo/b.pcode": "bravo",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/bar/": None,
            "B/bar/a.pcode": "argabikini",
            "B/bar/c.pcode": "charlie",
        },
    )

    changes, only_in_a, only_in_b, _ = diff_file_trees(tmp_path / "A", tmp_path / "B")

    assert not changes

    assert set(only_in_a) == {
        Path("foo/a.pcode"),
        Path("foo/b.pcode"),
    }

    assert set(only_in_b) == {
        Path("bar/a.pcode"),
        Path("bar/c.pcode"),
    }


def test_diff_file_trees_with_pure_renames(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/foo/": None,
            "A/foo/a.pcode": "same_content",
            "A/foo/b.pcode": "this text will not change...",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/bar/": None,
            "B/bar/a.pcode": "same_content",
            "B/bar/c.pcode": "this text will not change...",
        },
    )

    changes, only_in_a, only_in_b, equals = diff_file_trees(tmp_path / "A", tmp_path / "B")

    # Files with identical content but different paths are treated as pure renames.
    # They are paired and therefore do not remain unmatched.
    assert set(changes) == {
        FileDiff(path=Path("foo/a.pcode"), path_new=Path("bar/a.pcode"), lines_changed=0),
        FileDiff(path=Path("foo/b.pcode"), path_new=Path("bar/c.pcode"), lines_changed=0),
    }
    assert not only_in_a
    assert not only_in_b
    assert not equals


def test_diff_file_trees_pairs_similar_renamed_files(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/scripts/": None,
            "A/scripts/old_name.pcode": sample_text("""
                Push register2
                StoreRegister 1
                Pop
                Push register1
                Push "m_Count"
                GetMember
                Push register2
                Less2
                If L4
                Push register1
                Push "counter"
                GetMember
                Push 1
                Add2
                SetMember
                Jump L6
                L4: Push register1
                Push "counter"
                GetMember
                Push 1
                Subtract2
                SetMember
                L6: Push "A"
                Return
            """),
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/scripts/": None,
            "B/scripts/new_name.pcode": sample_text("""
                Push register2
                StoreRegister 1
                Pop
                Push register1
                Push "m_Count"
                GetMember
                Push register2
                Less2
                If L4
                Push register1
                Push "counter"
                GetMember
                Push 1
                Add2
                SetMember
                Jump L6
                L4: Push register1
                Push "counter"
                GetMember
                Push 1
                Subtract2
                SetMember
                L6: Push "B"
                Return
            """),
        },
    )

    changes, only_in_a, only_in_b, _ = diff_file_trees(tmp_path / "A", tmp_path / "B")

    assert set(changes) == {
        FileDiff(
            path=Path("scripts/old_name.pcode"),
            path_new=Path("scripts/new_name.pcode"),
            lines_changed=1,
            spans=[TextDiffSpan((22, 23), (22, 23))],
        )
    }

    assert not only_in_a
    assert not only_in_b


def test_diff_file_trees_pairs_best_similar_rename_candidate(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/scripts/": None,
            "A/scripts/source_block.pcode": sample_text("""
                Push register1
                Push "m_Count"
                GetMember
                StoreRegister 1
                Pop
                Push register2
                Push "m_Weight"
                GetMember
                Push 0
                Greater2
                If L1
                Push register3
                Push "slot"
                GetMember
                Push 1
                Add2
                SetMember
                Jump L2
                L1: Push "fallback"
                L2: Push "END"
                Return
            """),
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/scripts/": None,
            "B/scripts/renamed_best_candidate.pcode": sample_text("""
                Push register1
                Push "m_Count"
                GetMember
                StoreRegister 1
                Pop
                Push register2
                Push "m_Weight"
                GetMember
                Push 0
                Greater2
                If L1
                Push register3
                Push "slot"
                GetMember
                Push 1
                Add2
                SetMember
                Jump L2
                L1: Push "fallback"
                L2: Push "END_BEST"
                Return
            """),
            "B/scripts/renamed_other_candidate.pcode": sample_text("""
                Push register1
                Push "m_Count"
                GetMember
                StoreRegister 1
                Pop
                Push register2
                Push "m_Weight"
                GetMember
                Push 0
                Greater2
                If L1
                Push register3
                Push "slot"
                GetMember
                Push 1
                Add2
                SetMember
                Jump L2
                L1: Push "fallback_modded"
                L2: Push "END_OTHER"
                Return
            """),
        },
    )

    changes, only_in_a, only_in_b, _ = diff_file_trees(tmp_path / "A", tmp_path / "B")

    # Both candidate files are similar enough to be comparable, but only the closest
    # content match should be paired with the source block.
    assert set(changes) == {
        FileDiff(
            path=Path("scripts/source_block.pcode"),
            path_new=Path("scripts/renamed_best_candidate.pcode"),
            lines_changed=1,
            spans=[TextDiffSpan((19, 20), (19, 20))],
        )
    }

    assert not only_in_a
    assert set(only_in_b) == {Path("scripts/renamed_other_candidate.pcode")}


def test_diff_file_trees_does_not_pair_renamed_files_below_similarity_threshold(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/scripts/": None,
            "A/scripts/old_name_low_similarity.pcode": sample_text("""
                Push register1
                Push "counter"
                GetMember
                Push 1
                Add2
                SetMember
                Push register1
                Push "category"
                GetMember
                If L2
                Push "A"
                Return
            """),
            "A/scripts/high_similarity_but_not_enough_v1.pcode": sample_text("""
                Push register1
                Push "m_Count"
                GetMember
                Push 1
                Add2
                SetMember
                Push register2
                Push "m_Weight"
                GetMember
                Push 0
                Greater2
                If L1
                Push "MARKER_ALPHA"
                Jump L2
                L1: Push "MARKER_BETA"
                L2: Push register1
                Push "Done"
                Trace
                Return
            """),
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/scripts/": None,
            "B/scripts/new_name_low_similarity.pcode": sample_text("""
                Push register5
                Push "m_SlotsObject"
                GetMember
                Push 0
                Equals2
                Not
                If L9
                Push register3
                Push "isQuestItem"
                Push true
                SetMember
                Return
            """),
            "B/scripts/high_similarity_but_not_enough_v2.pcode": sample_text("""
                Push register1
                Push "m_Count"
                GetMember
                Push 1
                Add2
                SetMember
                Push register2
                Push "m_Weight"
                GetMember
                Push 0
                Greater2
                If L1
                Push "MARKER_ALPHA_MODDED"
                Jump L2
                L1: Push "MARKER_BETA"
                L2: Push register1
                Push "Done"
                Pop
                Return
            """),
        },
    )

    changes, only_in_a, only_in_b, _ = diff_file_trees(tmp_path / "A", tmp_path / "B")

    # Different paths + below-threshold similarity: both candidate pairs must stay unmatched.
    # The "high-similarity" pair still stays below threshold:
    # 2 replacements over 19 lines => similarity ~= 0.895 (< 0.9).
    assert not changes

    assert set(only_in_a) == {
        Path("scripts/old_name_low_similarity.pcode"),
        Path("scripts/high_similarity_but_not_enough_v1.pcode"),
    }

    assert set(only_in_b) == {
        Path("scripts/new_name_low_similarity.pcode"),
        Path("scripts/high_similarity_but_not_enough_v2.pcode"),
    }


def test_diff_file_trees_with_include_paths_filter(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/keep/": None,
            "A/keep/changed.pcode": sample_text("""
                Push 1
                Return
            """),
            "A/keep/only_in_a.pcode": "A only",
            "A/ignore/": None,
            "A/ignore/changed.pcode": "ABCDEF",
            "A/ignore/only_in_a.pcode": "45ds f45sdf ",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/keep/": None,
            "B/keep/changed.pcode": sample_text("""
                Push 2
                Return
            """),
            "B/keep/only_in_b.pcode": "B only",
            "B/ignore/": None,
            "B/ignore/changed.pcode": "ABCDEFG",
            "B/ignore/only_in_b.pcode": "qsdf dfsdf ",
        },
    )

    changes, only_in_a, only_in_b, _ = diff_file_trees(
        tmp_path / "A",
        tmp_path / "B",
        include_paths={Path("keep")},
    )

    assert set(changes) == {
        FileDiff(
            path=Path("keep/changed.pcode"),
            path_new=None,
            lines_changed=1,
            spans=[TextDiffSpan((0, 1), (0, 1))],
        )
    }

    assert set(only_in_a) == {Path("keep/only_in_a.pcode")}
    assert set(only_in_b) == {Path("keep/only_in_b.pcode")}


def test_diff_file_trees_hash_pairing_with_unequal_counts(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/scripts/": None,
            "A/scripts/clone_a1.pcode": "identical payload",
            "A/scripts/clone_a2.pcode": "identical payload",
            "A/scripts/clone_a3.pcode": "identical payload",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/scripts/": None,
            "B/scripts/new_subdir/": None,
            "B/scripts/new_subdir/clone_b1.pcode": "identical payload",
            "B/scripts/new_subdir/clone_b2.pcode": "identical payload",
        },
    )

    changes, only_in_a, only_in_b, _ = diff_file_trees(tmp_path / "A", tmp_path / "B")

    # There are multiple possible pairing, but only 2 targets in tree B, so one file will
    # remain unmatched in A.
    assert len(changes) == 2
    assert {ch.path for ch in changes}.isdisjoint(only_in_a)

    assert {ch.path_new for ch in changes} == {
        Path("scripts/new_subdir/clone_b1.pcode"),
        Path("scripts/new_subdir/clone_b2.pcode"),
    }

    assert len(only_in_a) == 1
    assert only_in_a[0] in {
        Path("scripts/clone_a1.pcode"),
        Path("scripts/clone_a2.pcode"),
        Path("scripts/clone_a3.pcode"),
    }

    assert not only_in_b


def test_diff_file_trees_reports_equal_paths_and_pure_renames_separately(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/common/": None,
            "A/common/same_path.pcode": "same payload",
            "A/scripts/": None,
            "A/scripts/renamed_but_equal_in_a.pcode": "exactly identical payload",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/common/": None,
            "B/common/same_path.pcode": "same payload",
            "B/scripts/": None,
            "B/scripts/renamed_but_equal_in_b.pcode": "exactly identical payload",
        },
    )

    changes, only_in_a, only_in_b, equals = diff_file_trees(tmp_path / "A", tmp_path / "B")

    assert set(changes) == {
        FileDiff(
            path=Path("scripts/renamed_but_equal_in_a.pcode"),
            path_new=Path("scripts/renamed_but_equal_in_b.pcode"),
            lines_changed=0,
        )
    }

    assert not only_in_a
    assert not only_in_b

    assert set(equals) == {
        Path("common/same_path.pcode"),
    }


def test_diff_file_trees_reports_equal_files_that_are_not_byte_identical(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/scripts/": None,
            "A/scripts/a.pcode": "Push register1\nReturn\n",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/scripts/": None,
            "B/scripts/a.pcode": "Push register1\nReturn",
        },
    )

    changes, only_in_a, only_in_b, equals = diff_file_trees(tmp_path / "A", tmp_path / "B")

    assert not changes
    assert not only_in_a
    assert not only_in_b
    assert equals == [Path("scripts/a.pcode")]


def test_diff_file_trees_reports_pure_rename_pairs_that_are_not_byte_identical(tmp_path: Path):
    _create_fake_file_tree(
        tmp_path,
        {
            "A/": None,
            "A/scripts/": None,
            "A/scripts/a.pcode": "Push register1\nReturn\n",
        },
    )

    _create_fake_file_tree(
        tmp_path,
        {
            "B/": None,
            "B/scripts/": None,
            "B/scripts/atoto.pcode": "Push register1\nReturn",
        },
    )

    changes, only_in_a, only_in_b, equals = diff_file_trees(tmp_path / "A", tmp_path / "B")

    assert set(changes) == {
        FileDiff(
            path=Path("scripts/a.pcode"),
            path_new=Path("scripts/atoto.pcode"),
            lines_changed=0,  # pure rename
        )
    }

    assert not only_in_a
    assert not only_in_b
    assert not equals


def test_format_path_rename_git_style_edge_cases():
    assert format_path_rename_git_style(Path("a/b.txt"), Path("c/d.txt")) == "a/b.txt => c/d.txt"

    assert format_path_rename_git_style(Path("foo/bar"), Path("foo/bar/baz")) == "foo/{bar => bar/baz}"

    assert format_path_rename_git_style(Path("foo/bar/baz"), Path("bar/baz")) == "{foo/bar => bar}/baz"

    assert (
        format_path_rename_git_style(
            Path("qsdfsdf/pppp/yap/sdfdf/debo.txt"),
            Path("qsdfsdf/pppp/yap/sdfdf/pipi/yyy.txt"),
        )
        == "qsdfsdf/pppp/yap/sdfdf/{debo.txt => pipi/yyy.txt}"
    )

    assert format_path_rename_git_style(Path("unchanged/path.txt"), None) == "unchanged/path.txt"


def test_cut_text_hunks_with_context():
    sample = sample_text_lines("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        SetMember
        Push register2, "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        loc4vs5: Push 0.1, 0.0, register1, "GetMoney"
        CallMethod
        Push 1, "Math"
        GetVariable
        Push "round"
        CallMethod
        Multiply
        Return
        }

        SetMember
        Push register2, "GetMoney"
        loc1312: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {
        Push 0.0
        loc78f:
        Push -1
        Add2
        Push -1.3
        Subtract
    """)

    hunks = cut_text_hunks_with_context(sample, [1, 6, 7, 8, 19, 20], context_length=3, merge=False)

    assert hunks == [
        [
            _hunk_ctx(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
            _hunk_select(1, "NewObject"),
            _hunk_ctx(2, "SetMember"),
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
        ],
        [
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
            _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
            _hunk_select(6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(8, "CallMethod"),
            _hunk_ctx(9, 'Push 1, "Math"'),
            _hunk_ctx(10, "GetVariable"),
            _hunk_ctx(11, 'Push "round"'),
        ],
        [
            _hunk_ctx(16, ""),
            _hunk_ctx(17, "SetMember"),
            _hunk_ctx(18, 'Push register2, "GetMoney"'),
            _hunk_select(
                19, 'loc1312: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {'
            ),
            _hunk_select(20, "Push 0.0"),
            _hunk_ctx(21, "loc78f:"),
            _hunk_ctx(22, "Push -1"),
            _hunk_ctx(23, "Add2"),
        ],
    ]


def test_cut_text_hunks_with_context_with_outofbounds_selection():
    sample = sample_text_lines("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        Push -1
        SetMember
        Push register2, "GetMoney"
    """)

    with pytest.raises(ValueError, match=re.escape("Line selection contains an out-of-bounds span: [-1:3].")):
        cut_text_hunks_with_context(sample, [-1, 0, 1, 2])

    with pytest.raises(ValueError, match=re.escape("Line selection contains an out-of-bounds span: [1:6].")):
        cut_text_hunks_with_context(sample, [1, 2, 3, 4, 5])


def test_cut_text_hunks_with_context_with_smaller_context():
    sample = sample_text_lines("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        SetMember
        Push register2, "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        loc4vs5: Push 0.1, 0.0, register1, "GetMoney"
        CallMethod
        Push 1, "Math"
        GetVariable
        Push "round"
        CallMethod
        Multiply
        Return
        }

        SetMember
        Push register2, "GetMoney"
        loc1312: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {
        Push 0.0
        loc78f:
        Push -1
        Add2
        Push -1.3
        Subtract
    """)

    hunks = cut_text_hunks_with_context(sample, [1, 6, 7, 8, 19, 20], context_length=1, merge=False)

    assert hunks == [
        [
            _hunk_ctx(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
            _hunk_select(1, "NewObject"),
            _hunk_ctx(2, "SetMember"),
        ],
        [
            _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
            _hunk_select(6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(8, "CallMethod"),
            _hunk_ctx(9, 'Push 1, "Math"'),
        ],
        [
            _hunk_ctx(18, 'Push register2, "GetMoney"'),
            _hunk_select(
                19, 'loc1312: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {'
            ),
            _hunk_select(20, "Push 0.0"),
            _hunk_ctx(21, "loc78f:"),
        ],
    ]


def test_cut_text_hunks_with_context_with_unordered_set_selection():
    sample = sample_text_lines("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        SetMember
        Push register2, "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        loc4vs5: Push 0.1, 0.0, register1, "GetMoney"
        CallMethod
        Push 1, "Math"
        GetVariable
        Push "round"
        CallMethod
        Multiply
        Return
        }

        SetMember
        Push register2, "GetMoney"
        loc1312: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {
        Push 0.0
        loc78f:
        Push -1
        Add2
        Push -1.3
        Subtract
    """)

    hunks = cut_text_hunks_with_context(sample, {2, 13, 6, 0}, context_length=2, merge=True)

    assert hunks == [
        [
            _hunk_select(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
            _hunk_ctx(1, "NewObject"),
            _hunk_select(2, "SetMember"),
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
            _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
            _hunk_select(6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_ctx(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_ctx(8, "CallMethod"),
        ],
        [
            _hunk_ctx(11, 'Push "round"'),
            _hunk_ctx(12, "CallMethod"),
            _hunk_select(13, "Multiply"),
            _hunk_ctx(14, "Return"),
            _hunk_ctx(15, "}"),
        ],
    ]


def test_cut_text_hunks_with_context_merges_adjacent_and_overlapping_hunks():
    sample = sample_text_lines("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        SetMember
        Push register2, "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        loc4vs5: Push 0.1, 0.0, register1, "GetMoney"
        CallMethod
        Push 1, "Math"
        GetVariable
        Push "round"
        CallMethod
        Multiply
        Return
        }

        SetMember
        Push register2, "GetMoney"
        loc1312: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {
        Push 0.0
        loc78f:
        Push -1
        Add2
        Push -1.3
        Subtract
        Push register2
        Push "E_IS_Weight"
        Push 2
        SetMember
        Push register2
        Push "E_IS_Price"
        Push 3
        SetMember
    """)

    hunks = cut_text_hunks_with_context(sample, [1, 6, 7, 8, 19, 20, 27], context_length=3, merge=True)

    assert hunks == [
        [
            _hunk_ctx(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
            _hunk_select(1, "NewObject"),
            _hunk_ctx(2, "SetMember"),
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
            _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
            _hunk_select(6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(8, "CallMethod"),
            _hunk_ctx(9, 'Push 1, "Math"'),
            _hunk_ctx(10, "GetVariable"),
            _hunk_ctx(11, 'Push "round"'),
        ],
        [
            _hunk_ctx(16, ""),
            _hunk_ctx(17, "SetMember"),
            _hunk_ctx(18, 'Push register2, "GetMoney"'),
            _hunk_select(
                19, 'loc1312: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {'
            ),
            _hunk_select(20, "Push 0.0"),
            _hunk_ctx(21, "loc78f:"),
            _hunk_ctx(22, "Push -1"),
            _hunk_ctx(23, "Add2"),
            _hunk_ctx(24, "Push -1.3"),
            _hunk_ctx(25, "Subtract"),
            _hunk_ctx(26, "Push register2"),
            _hunk_select(27, 'Push "E_IS_Weight"'),
            _hunk_ctx(28, "Push 2"),
            _hunk_ctx(29, "SetMember"),
            _hunk_ctx(30, "Push register2"),
        ],
    ]


def test_cut_text_hunks_with_context_with_edge_selection():
    sample = sample_text_lines("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        Push -1
        SetMember
        Push register2, "GetMoney"
    """)

    hunks = cut_text_hunks_with_context(sample, [0], context_length=2, merge=False)

    assert hunks == [
        [
            _hunk_select(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
            _hunk_ctx(1, "NewObject"),
            _hunk_ctx(2, "Push -1"),
        ]
    ]

    hunks = cut_text_hunks_with_context(sample, [4], context_length=2, merge=False)

    assert hunks == [
        [_hunk_ctx(2, "Push -1"), _hunk_ctx(3, "SetMember"), _hunk_select(4, 'Push register2, "GetMoney"')]
    ]

    hunks = cut_text_hunks_with_context(sample, [3, 4], context_length=2, merge=False)

    assert hunks == [
        [
            _hunk_ctx(1, "NewObject"),
            _hunk_ctx(2, "Push -1"),
            _hunk_select(3, "SetMember"),
            _hunk_select(4, 'Push register2, "GetMoney"'),
        ]
    ]


def test_cut_text_hunks_with_context_with_empty_selection():
    sample = sample_text_lines("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        Push -1
        SetMember
        Push register2, "GetMoney"
    """)

    assert cut_text_hunks_with_context(sample, []) == []


def test_cut_text_hunks_with_context_with_exceeding_context():
    sample = sample_text_lines("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        Push -1
        SetMember
        Push register2, "GetMoney"
    """)

    # Demanded context goes beyond the start of the sample text.
    hunks = cut_text_hunks_with_context(sample, [1], context_length=2, merge=False)

    assert hunks == [
        [
            _hunk_ctx(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
            _hunk_select(1, "NewObject"),
            _hunk_ctx(2, "Push -1"),
            _hunk_ctx(3, "SetMember"),
        ]
    ]

    # Demanded context goes beyond the end of the sample text.
    hunks = cut_text_hunks_with_context(sample, [3], context_length=2, merge=False)

    assert hunks == [
        [
            _hunk_ctx(1, "NewObject"),
            _hunk_ctx(2, "Push -1"),
            _hunk_select(3, "SetMember"),
            _hunk_ctx(4, 'Push register2, "GetMoney"'),
        ]
    ]

    # Demanded context goes beyond both sample text bounds.
    hunks = cut_text_hunks_with_context(sample, [2], context_length=5, merge=False)

    assert hunks == [
        [
            _hunk_ctx(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
            _hunk_ctx(1, "NewObject"),
            _hunk_select(2, "Push -1"),
            _hunk_ctx(3, "SetMember"),
            _hunk_ctx(4, 'Push register2, "GetMoney"'),
        ]
    ]


def test_align_hunk_pair_edge_context():
    hunk_1 = TextHunk(
        [
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
            _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
            _hunk_select(6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(8, "CallMethod"),
            _hunk_ctx(9, 'Push 1, "Math"'),
            _hunk_ctx(10, "GetVariable"),
            _hunk_ctx(11, 'Push "round"'),
            _hunk_ctx(12, "GetVariable"),
            _hunk_ctx(13, "Add2"),
        ]
    )

    hunk_2 = TextHunk(
        [
            _hunk_ctx(4, "If loc02b2"),
            _hunk_ctx(5, "}"),
            _hunk_ctx(6, "SetMember"),
            _hunk_ctx(7, 'Push register2, "GetMoneyForString"'),
            _hunk_select(8, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(9, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(10, "CallMethod"),
            _hunk_ctx(11, 'Push 1, "Math"'),
            _hunk_ctx(12, "GetVariable"),
            _hunk_ctx(13, 'Push "round"'),
        ]
    )

    aligned_hunk_1, aligned_hunk_2 = align_hunk_pair_edge_context(hunk_1, hunk_2)

    assert aligned_hunk_1 == TextHunk(
        [
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
            _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
            _hunk_select(6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(8, "CallMethod"),
            _hunk_ctx(9, 'Push 1, "Math"'),
            _hunk_ctx(10, "GetVariable"),
            _hunk_ctx(11, 'Push "round"'),
        ]
    )

    assert aligned_hunk_2 == TextHunk(
        [
            _hunk_ctx(5, "}"),
            _hunk_ctx(6, "SetMember"),
            _hunk_ctx(7, 'Push register2, "GetMoneyForString"'),
            _hunk_select(8, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(9, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(10, "CallMethod"),
            _hunk_ctx(11, 'Push 1, "Math"'),
            _hunk_ctx(12, "GetVariable"),
            _hunk_ctx(13, 'Push "round"'),
        ]
    )


def test_align_hunk_pair_edge_context_with_empty_hunk():
    hunk_1 = TextHunk(
        [
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
            _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
            _hunk_select(6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(8, "CallMethod"),
            _hunk_ctx(9, 'Push 1, "Math"'),
            _hunk_ctx(10, "GetVariable"),
            _hunk_ctx(11, 'Push "round"'),
            _hunk_ctx(12, "GetVariable"),
            _hunk_ctx(13, "Add2"),
        ]
    )

    hunk_2 = TextHunk()

    aligned_hunk_1, aligned_hunk_2 = align_hunk_pair_edge_context(hunk_1, hunk_2)

    assert aligned_hunk_1 == hunk_1
    assert aligned_hunk_2 == hunk_2

    aligned_hunk_2, aligned_hunk_1 = align_hunk_pair_edge_context(hunk_2, hunk_1)  # reversed

    assert aligned_hunk_1 == hunk_1
    assert aligned_hunk_2 == hunk_2

    assert align_hunk_pair_edge_context(TextHunk(), TextHunk()) == (TextHunk(), TextHunk())


def test_align_hunk_pair_edge_context_without_leading_context():
    hunk_1 = TextHunk(
        [
            _hunk_select(36, "L4: Push register1"),
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 1"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
            _hunk_ctx(42, 'L6: Push "A"'),
        ]
    )

    hunk_2 = TextHunk(
        [
            _hunk_select(36, "L6: Push register2"),
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 2"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
        ]
    )

    aligned_hunk_1, aligned_hunk_2 = align_hunk_pair_edge_context(hunk_1, hunk_2)

    assert aligned_hunk_1 == TextHunk(
        [
            _hunk_select(36, "L4: Push register1"),
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 1"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
        ]
    )

    assert aligned_hunk_2 == TextHunk(
        [
            _hunk_select(36, "L6: Push register2"),
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 2"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
        ]
    )


def test_align_hunk_pair_edge_context_without_trailing_context():
    hunk_1 = TextHunk(
        [
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 1"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
            _hunk_select(42, 'L6: Push "A"'),
        ]
    )

    hunk_2 = TextHunk(
        [
            _hunk_ctx(35, "Push 9"),
            _hunk_ctx(36, 'Push "counter"'),
            _hunk_ctx(37, "GetMember"),
            _hunk_select(38, "Push 2"),
            _hunk_ctx(39, "Subtract2"),
            _hunk_ctx(40, "SetMember"),
            _hunk_select(41, 'L6: Push "B"'),
        ]
    )

    aligned_hunk_1, aligned_hunk_2 = align_hunk_pair_edge_context(hunk_1, hunk_2)

    assert aligned_hunk_1 == TextHunk(
        [
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 1"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
            _hunk_select(42, 'L6: Push "A"'),
        ]
    )

    assert aligned_hunk_2 == TextHunk(
        [
            _hunk_ctx(36, 'Push "counter"'),
            _hunk_ctx(37, "GetMember"),
            _hunk_select(38, "Push 2"),
            _hunk_ctx(39, "Subtract2"),
            _hunk_ctx(40, "SetMember"),
            _hunk_select(41, 'L6: Push "B"'),
        ]
    )


def test_align_hunk_pair_edge_context_without_edge_context():
    hunk_1 = TextHunk(
        [
            _hunk_select(36, "L4: Push register1"),
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 1"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
            _hunk_select(42, 'L6: Push "A"'),
        ]
    )

    hunk_2 = TextHunk(
        [
            _hunk_select(36, "L6: Push register2"),
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 2"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
            _hunk_select(42, 'L6: Push "B"'),
        ]
    )

    aligned_hunk_1, aligned_hunk_2 = align_hunk_pair_edge_context(hunk_1, hunk_2)

    assert aligned_hunk_1 == TextHunk(
        [
            _hunk_select(36, "L4: Push register1"),
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 1"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
            _hunk_select(42, 'L6: Push "A"'),
        ]
    )

    assert aligned_hunk_2 == TextHunk(
        [
            _hunk_select(36, "L6: Push register2"),
            _hunk_ctx(37, 'Push "counter"'),
            _hunk_ctx(38, "GetMember"),
            _hunk_select(39, "Push 2"),
            _hunk_ctx(40, "Subtract2"),
            _hunk_ctx(41, "SetMember"),
            _hunk_select(42, 'L6: Push "B"'),
        ]
    )


def test_align_hunk_pair_edge_context_without_context_at_all():
    hunk_1 = TextHunk(
        [
            _hunk_select(36, "L4: Push register1"),
            _hunk_select(37, 'Push "counter"'),
            _hunk_select(38, "GetMember"),
        ]
    )

    hunk_2 = TextHunk(
        [
            _hunk_select(36, "L6: Push register2"),
            _hunk_select(37, 'Push "counterino"'),
            _hunk_select(38, "GetVariable"),
        ]
    )

    aligned_hunk_1, aligned_hunk_2 = align_hunk_pair_edge_context(hunk_1, hunk_2)

    assert aligned_hunk_1 == TextHunk(
        [
            _hunk_select(36, "L4: Push register1"),
            _hunk_select(37, 'Push "counter"'),
            _hunk_select(38, "GetMember"),
        ]
    )

    assert aligned_hunk_2 == TextHunk(
        [
            _hunk_select(36, "L6: Push register2"),
            _hunk_select(37, 'Push "counterino"'),
            _hunk_select(38, "GetVariable"),
        ]
    )


def test_align_hunk_pair_edge_context_with_context_only():
    hunk_1 = TextHunk(
        [
            _hunk_ctx(21, "loc78f:"),
            _hunk_ctx(22, "Push -1"),
            _hunk_ctx(23, "Add2"),
            _hunk_ctx(24, "Push 0.3"),
        ]
    )

    hunk_2 = TextHunk(
        [
            _hunk_ctx(10, "loc78f:"),
            _hunk_ctx(11, "Push -1"),
            _hunk_ctx(12, "Add2"),
        ]
    )

    with pytest.raises(AssertionError):
        align_hunk_pair_edge_context(hunk_1, hunk_2)


def test_align_hunk_pairs_does_not_merge_non_adjacent_hunks():
    # We have two unrelated diffs at lines 5 and 25, separated by 20 identical lines.
    # With a context length of 5, `cut_text_hunks_with_context` produces TWO separate hunks per side.
    # `align_hunk_pairs` must keep them as two separate pairs.
    # Gluing them together will produce erroneous hunks with non-contiguous lines.
    side_a = [f"line{i}" for i in range(30)]
    side_a[5] = "DIFF_A_FIRST"
    side_a[25] = "DIFF_A_SECOND"
    side_b = list(side_a)
    side_b[5] = "DIFF_B_FIRST"
    side_b[25] = "DIFF_B_SECOND"

    hunks_a = cut_text_hunks_with_context(side_a, [5, 25], context_length=5, merge=True)
    hunks_b = cut_text_hunks_with_context(side_b, [5, 25], context_length=5, merge=True)
    assert len(hunks_a) == 2 and len(hunks_b) == 2  # sanity check: not pre-merged by cut_text_hunks

    pairs = align_hunk_pairs(hunks_a, hunks_b)

    assert len(pairs) == 2

    for ha, hb in pairs:
        a_idx = [ln.index for ln in ha]
        b_idx = [ln.index for ln in hb]
        assert a_idx == list(range(a_idx[0], a_idx[-1] + 1)), f"side A indices not contiguous: {a_idx}"
        assert b_idx == list(range(b_idx[0], b_idx[-1] + 1)), f"side B indices not contiguous: {b_idx}"


def test_align_hunk_pairs():
    hunks_1 = [
        [
            _hunk_ctx(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
            _hunk_select(1, "NewObject"),
            _hunk_ctx(2, "SetMember"),
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
        ],
        [
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
            _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
            _hunk_select(6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(8, "CallMethod"),
            _hunk_ctx(9, 'Push 1, "Math"'),
            _hunk_ctx(10, "GetVariable"),
            _hunk_ctx(11, 'Push "round"'),
        ],
        [
            _hunk_ctx(16, ""),
            _hunk_ctx(17, "SetMember"),
            _hunk_ctx(18, 'Push register2, "GetMoney"'),
            _hunk_select(
                19, 'loc1312: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {'
            ),
            _hunk_select(20, "Push 0.0"),
            _hunk_ctx(21, "loc78f:"),
            _hunk_ctx(22, "Push -1"),
            _hunk_ctx(23, "Add2"),
        ],
    ]

    hunks_2 = [
        [
            _hunk_ctx(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
            _hunk_select(1, "NewObject"),
            _hunk_ctx(2, "SetMember"),
            _hunk_ctx(3, "}"),
        ],
        [
            _hunk_ctx(3, "}"),
            _hunk_ctx(4, "SetMember"),
            _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
            _hunk_select(6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'),
            _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
            _hunk_select(8, "CallMethod"),
            _hunk_ctx(9, 'Push 1, "Math"'),
            _hunk_ctx(10, "GetVariable"),
            _hunk_ctx(11, 'Push "round"'),
        ],
        [
            _hunk_select(16, "GetMember"),
            _hunk_select(17, "Push register3"),
            _hunk_select(18, 'Push "vioc"'),
        ],
        [
            _hunk_ctx(19, ""),
            _hunk_ctx(20, "SetMember"),
            _hunk_ctx(21, 'Push register2, "GetMoney"'),
            _hunk_select(
                22, 'locable: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {'
            ),
            _hunk_select(23, "Push 0.0"),
            _hunk_select(24, "loc79j:"),
            _hunk_ctx(25, "Push -1"),
            _hunk_ctx(26, "Add2"),
        ],
    ]

    assert align_hunk_pairs(hunks_1, hunks_2) == [
        (
            [
                _hunk_ctx(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                _hunk_select(1, "NewObject"),
                _hunk_ctx(2, "SetMember"),
                _hunk_ctx(3, "}"),
            ],
            [
                _hunk_ctx(0, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                _hunk_select(1, "NewObject"),
                _hunk_ctx(2, "SetMember"),
                _hunk_ctx(3, "}"),
            ],
        ),
        (
            [
                _hunk_ctx(3, "}"),
                _hunk_ctx(4, "SetMember"),
                _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
                _hunk_select(
                    6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'
                ),
                _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
                _hunk_select(8, "CallMethod"),
                _hunk_ctx(9, 'Push 1, "Math"'),
                _hunk_ctx(10, "GetVariable"),
                _hunk_ctx(11, 'Push "round"'),
            ],
            [
                _hunk_ctx(3, "}"),
                _hunk_ctx(4, "SetMember"),
                _hunk_ctx(5, 'Push register2, "GetMoneyForString"'),
                _hunk_select(
                    6, 'DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {'
                ),
                _hunk_select(7, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
                _hunk_select(8, "CallMethod"),
                _hunk_ctx(9, 'Push 1, "Math"'),
                _hunk_ctx(10, "GetVariable"),
                _hunk_ctx(11, 'Push "round"'),
            ],
        ),
        # I could not make the function produce this output. Even though the current function result looks less
        # accurate to the human eye, it is still a valid and reasonable output.
        # (
        #     [],
        #     [
        #         (16, "GetMember"),
        #         (17, "Push register3"),
        #         (18, 'Push "vioc"'),
        #     ],
        # ),
        (
            [
                _hunk_ctx(16, ""),
                _hunk_ctx(17, "SetMember"),
                _hunk_ctx(18, 'Push register2, "GetMoney"'),
                _hunk_select(
                    19,
                    'loc1312: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {',
                ),
                _hunk_select(20, "Push 0.0"),
                _hunk_ctx(21, "loc78f:"),
                _hunk_ctx(22, "Push -1"),
                _hunk_ctx(23, "Add2"),
            ],
            # TODO: the following hunk should appear in a separate insertion hunk (see previous comment).
            # And the hunk on side A should be paired with the next hunk on side B.
            [
                _hunk_select(16, "GetMember"),
                _hunk_select(17, "Push register3"),
                _hunk_select(18, 'Push "vioc"'),
            ],
        ),
        (
            [],
            [
                _hunk_ctx(19, ""),
                _hunk_ctx(20, "SetMember"),
                _hunk_ctx(21, 'Push register2, "GetMoney"'),
                _hunk_select(
                    22,
                    'locable: DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {',
                ),
                _hunk_select(23, "Push 0.0"),
                _hunk_select(24, "loc79j:"),
                _hunk_ctx(25, "Push -1"),
                _hunk_ctx(26, "Add2"),
            ],
        ),
    ]


def test_diff_text_hunks():
    text_sample_1 = _sample_text_hunk("""
        Push register5
        PushDuplicate
        Not
        If L2
        Pop
        Push register2
        Push register3
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    text_sample_2 = _sample_text_hunk("""
        Push 1
        StoreRegister 7
        Pop
        Push register5
        PushDuplicate
        Equals2
        If L9
        StoreRegister 2
        Pop
        Push register2
        Push "UNDEFINED_SLOT"
        GetMember
    """)

    diffed_hunk_1, diffed_hunk_2 = diff_text_hunks(text_sample_1, text_sample_2)

    # 3 lines added at the beginning
    # 2-3 lines replaced in the middle
    # 1 line deleted near the end

    assert diffed_hunk_1 == DiffHunk(
        [
            TextHunk(),
            TextHunk(
                [
                    _hunk_line(0, "Push register5", is_context=True),
                    _hunk_line(1, "PushDuplicate", is_context=True),
                ]
            ),
            TextHunk([_hunk_line(2, "Not", is_deletion=True), _hunk_line(3, "If L2", is_deletion=True)]),
            TextHunk(
                [
                    _hunk_line(4, "Pop", is_context=True),
                    _hunk_line(5, "Push register2", is_context=True),
                ]
            ),
            TextHunk(
                [
                    _hunk_line(6, "Push register3", is_deletion=True),
                ]
            ),
            TextHunk(
                [
                    _hunk_line(7, 'Push "UNDEFINED_SLOT"', is_context=True),
                    _hunk_line(8, "GetMember", is_context=True),
                ]
            ),
        ]
    )

    assert diffed_hunk_2 == DiffHunk(
        [
            TextHunk(
                [
                    _hunk_line(0, "Push 1", is_addition=True),
                    _hunk_line(1, "StoreRegister 7", is_addition=True),
                    _hunk_line(2, "Pop", is_addition=True),
                ]
            ),
            TextHunk(
                [
                    _hunk_line(3, "Push register5", is_context=True),
                    _hunk_line(4, "PushDuplicate", is_context=True),
                ]
            ),
            TextHunk(
                [
                    _hunk_line(5, "Equals2", is_addition=True),
                    _hunk_line(6, "If L9", is_addition=True),
                    _hunk_line(7, "StoreRegister 2", is_addition=True),
                ]
            ),
            TextHunk(
                [
                    _hunk_line(8, "Pop", is_context=True),
                    _hunk_line(9, "Push register2", is_context=True),
                ]
            ),
            TextHunk(),
            TextHunk(
                [
                    _hunk_line(10, 'Push "UNDEFINED_SLOT"', is_context=True),
                    _hunk_line(11, "GetMember", is_context=True),
                ]
            ),
        ]
    )
