import pytest
from pathlib import Path
from kcd_gfx_toolbox.file_diff import (
    FileDiff,
    TextDiff,
    TextDiffSpan,
    diff_file_trees,
    diff_file_trees_basic,
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
