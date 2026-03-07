from kcd_gfx_toolbox.avm1_pcode_alignment import (
    neutralize_labels_in_line,
    extract_jump_target_label_from_line,
    build_label_alignment_map,
    remap_labels_in_line,
    align_labels_in_text,
)
from tests.helpers import sample_text_lines


def test_neutralize_labels_in_line_empty_line_unchanged():
    assert neutralize_labels_in_line("") == ""


def test_neutralize_labels_in_line_plain_instruction_unchanged():
    assert neutralize_labels_in_line("Push 1") == "Push 1"


def test_neutralize_labels_in_line_label_prefix_neutralized():
    assert neutralize_labels_in_line("L125:Push 1") == "<LABEL>: Push 1"


def test_neutralize_labels_in_line_label_prefix_with_whitespace_neutralized():
    assert neutralize_labels_in_line("  L123sdf:  Push 1") == "<LABEL>: Push 1"


def test_neutralize_labels_in_line_jump_target_neutralized():
    assert neutralize_labels_in_line("Jump loc4565") == "Jump <LABEL>"


def test_neutralize_labels_in_line_if_target_neutralized():
    assert neutralize_labels_in_line("If La0x8") == "If <LABEL>"


def test_neutralize_labels_in_line_label_prefix_and_jump_both_neutralized():
    assert neutralize_labels_in_line("L1:Jump L2") == "<LABEL>: Jump <LABEL>"


def test_neutralize_labels_in_line_label_prefix_and_if_both_neutralized():
    assert neutralize_labels_in_line("L1:If L2") == "<LABEL>: If <LABEL>"


def test_extract_jump_target_label_from_line_with_jump():
    assert extract_jump_target_label_from_line("Jump L1") == "L1"


def test_extract_jump_target_label_from_line_with_if():
    assert extract_jump_target_label_from_line("If L2") == "L2"


def test_extract_jump_target_label_from_line_case_insensitive():
    assert extract_jump_target_label_from_line("jump L1") == "L1"
    assert extract_jump_target_label_from_line("if L2") == "L2"


def test_extract_jump_target_label_from_line_with_label_prefix():
    assert extract_jump_target_label_from_line("L1:Jump L2") == "L2"
    assert extract_jump_target_label_from_line("L1:If L2") == "L2"


def test_extract_jump_target_label_from_line_without_labels():
    assert extract_jump_target_label_from_line("Push 1") is None


def test_extract_jump_target_label_from_line_without_target_label():
    assert extract_jump_target_label_from_line("L1:Push 1") is None


def test_extract_jump_target_label_from_line_empty():
    assert extract_jump_target_label_from_line("") is None


def test_build_label_alignment_map_empty_texts():
    assert build_label_alignment_map([], []) == {}


def test_build_label_alignment_map_without_labels():
    lines = ["Push 1", "Push 2", "Return"]
    assert build_label_alignment_map(lines, lines) == {}


def test_build_label_alignment_map_simple_drift():
    text1 = sample_text_lines("""
        Push register6
        Return
        L1:Push 1
        If L2
        Push "A"
        L2:Return
    """)

    text2 = sample_text_lines("""
        L1: Push register6
        Return
        L10:Push 1
        If L11
        Push "A"
        L11:Return
    """)

    result = build_label_alignment_map(text1, text2)
    assert result == {"L10": "L1", "L11": "L2"}


def test_build_label_alignment_map_jump_targets_contribute_to_votes():
    text1 = sample_text_lines("""
        Push 1
        Jump L1
        L1:Return
    """)

    text2 = sample_text_lines("""
        Push 1
        Jump L10
        L10:Return
    """)

    result = build_label_alignment_map(text1, text2)
    assert result.get("L10") == "L1"


def test_build_label_alignment_map_with_identical_texts_returns_identity():
    text = sample_text_lines("""
        L1:Push 1
        If L2
        L2:Return
    """)

    result = build_label_alignment_map(text, text)
    assert result == {"L1": "L1", "L2": "L2"}


def test_build_label_alignment_map_with_completely_different_texts():
    text1 = sample_text_lines("""
        L1:Push "foo"
        L2:Push "bar"
    """)

    text2 = sample_text_lines("""
        L10:Push "baz"
        L11:Push "qux"
    """)

    assert build_label_alignment_map(text1, text2) == {}


def test_build_label_alignment_map_tie_not_matched():
    # L10 and L11 in text2 both equally correspond to L1 in text1. Tie -> dropped.
    # loc4 in text2 corresponds equally to L3 and L4 in text1. Tie -> dropped.
    # (These texts are total non-sense regarding AVM1 p-code! Do not mind.)
    text1 = sample_text_lines("""
        L1:Push 1
        Jump L1
        Push 2
        If L1
        Jump L1
        GetMember
        L3: StoreRegister 8
        L4: Pop
        If L4
        Push register1
        L3: Push 0.0
    """)

    text2 = sample_text_lines("""
        L10:Push 1
        Jump L11
        Push 2
        If L11
        Jump L10
        GetMember
        loc4: StoreRegister 8
        loc4: Pop
        If loc4
        Push register1
        loc4: Push 0.0
    """)

    result = build_label_alignment_map(text1, text2)
    assert "L1" not in result.values()
    assert "loc4" not in result


def test_remap_labels_in_line_remaps_label_prefix():
    label_map = {"L1": "loc_001", "L2": "l214", "L3": "L_3", "loc12": "loc13"}
    assert remap_labels_in_line("L1:Push 1", label_map) == "loc_001:Push 1"
    assert remap_labels_in_line("L2:StoreRegister 2", label_map) == "l214:StoreRegister 2"


def test_remap_labels_in_line_remaps_jump_target():
    label_map = {"L1": "loc_001", "L2": "l214", "L3": "L_3", "loc12": "loc13"}
    assert remap_labels_in_line("Jump L1", label_map) == "Jump loc_001"
    assert remap_labels_in_line("If loc12", label_map) == "If loc13"


def test_remap_labels_in_line_remaps_both_prefix_and_jump_target():
    label_map = {"L1": "loc_001", "L2": "l214", "L3": "L_3", "loc12": "loc13"}
    assert remap_labels_in_line("loc456: Jump L2", label_map) == "loc456:Jump l214"
    assert remap_labels_in_line("L1:Jump L2", label_map) == "loc_001:Jump l214"
    assert remap_labels_in_line("L3:If loc12", label_map) == "L_3:If loc13"


def test_remap_labels_in_line_unknown_label_prefix_unchanged():
    assert remap_labels_in_line("L4:Push register1", {"L2": "l214", "L3": "L_3"}) == "L4:Push register1"


def test_remap_labels_in_line_unknown_jump_target_unchanged():
    assert remap_labels_in_line("Jump L2", {"L1": "loc_001"}) == "Jump L2"


def test_remap_labels_in_line_without_label_unchanged():
    label_map = {"L1": "loc_001", "L2": "l214", "L3": "L_3", "loc12": "loc13"}
    assert remap_labels_in_line("Push  1 ", label_map) == "Push  1 "


def test_remap_labels_in_line_with_empty_map_unchanged():
    assert remap_labels_in_line("L1: Push 1", {}) == "L1: Push 1"
    assert remap_labels_in_line("Jump L1 ", {}) == "Jump L1 "


def test_align_labels_in_text_for_diff_no_label_map_no_changes():
    text1 = sample_text_lines("""
        Push 1
        Return
        Pop
        Push register3
        StoreRegister 4
    """)

    text2 = sample_text_lines("""
        Push 1
        Return
        If loc78
        Pop
        Push register6
        StoreRegister 4
    """)

    assert align_labels_in_text(text2, text1) == text2


def test_align_labels_in_text_for_diff_unmapped_label_unchanged():
    text1 = sample_text_lines("""
        Push 1
        Return
        If loc79
        Pop
        Push register6
        StoreRegister 4
    """)

    text2 = sample_text_lines("""
        Push 1
        Return
        If loc78
        Pop
        L6:Push register6
        StoreRegister 4
    """)

    # L6 must stay untouched:
    assert align_labels_in_text(text2, text1) == sample_text_lines("""
        Push 1
        Return
        If loc79
        Pop
        L6:Push register6
        StoreRegister 4
    """)


def test_align_labels_in_text_for_diff():
    text1 = sample_text_lines("""
        L3:Push 0.2
        StoreRegister 4
        Pop
        L8: Push register8
        Push register6
        If loc78
        Pop
        L9: Push "toto"
        Push register1
        If lbl002
        Push "m_count"
        GetMember
    """)

    text2 = sample_text_lines("""
        L5:Push 0.2
        StoreRegister 4
        Pop
        L10: Push register8
        Push register6
        If loc78
        Pop
        L11: Push "caca"
        Push register1
        If loc_121
        Push "m_count"
        GetMember
    """)

    assert align_labels_in_text(text2, text1) == sample_text_lines("""
        L3:Push 0.2
        StoreRegister 4
        Pop
        L8:Push register8
        Push register6
        If loc78
        Pop
        L11: Push "caca"
        Push register1
        If lbl002
        Push "m_count"
        GetMember
    """)
