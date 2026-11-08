from kcd_gfx_toolbox.avm1.pcode_alignment import (
    align_block_b_on_block_a,
    align_labels,
    align_registers,
    build_label_alignment_map,
    build_register_alignment_map,
    extract_jump_target_label_from_line,
    extract_register_indices_from_line,
    neutralize_labels_in_line,
    neutralize_registers_in_line,
    remap_labels_in_line,
    remap_registers_in_line,
)
from kcd_gfx_toolbox.avm1.pcode_parsing import parse_pcode_line, parse_pcode_lines
from tests.helpers import sample_pcode


def test_neutralize_labels_in_line_plain_instruction_unchanged():
    assert neutralize_labels_in_line(parse_pcode_line("Push 1")) == parse_pcode_line("Push 1")


def test_neutralize_labels_in_line_label_prefix_neutralized():
    assert neutralize_labels_in_line(parse_pcode_line("L125:Push 1")) == parse_pcode_line("LABEL: Push 1")


def test_neutralize_labels_in_line_jump_target_neutralized():
    assert neutralize_labels_in_line(parse_pcode_line("Jump loc4565")) == parse_pcode_line("Jump LABEL")


def test_neutralize_labels_in_line_if_target_neutralized():
    assert neutralize_labels_in_line(parse_pcode_line("If La0x8")) == parse_pcode_line("If LABEL")


def test_neutralize_labels_in_line_label_prefix_and_jump_both_neutralized():
    assert neutralize_labels_in_line(parse_pcode_line("L1:Jump L2")) == parse_pcode_line("LABEL: Jump LABEL")


def test_neutralize_labels_in_line_label_prefix_and_if_both_neutralized():
    assert neutralize_labels_in_line(parse_pcode_line("L1:If L2")) == parse_pcode_line("LABEL: If LABEL")


def test_neutralize_labels_in_line_empty_labeled_line():
    assert neutralize_labels_in_line(parse_pcode_line("lockjaw:")) == parse_pcode_line("LABEL:")


def test_neutralize_labels_in_line_labeled_closing_brace():
    assert neutralize_labels_in_line(parse_pcode_line("lockjaw:}")) == parse_pcode_line("LABEL:}")


def test_neutralize_labels_in_line_unlabeled_closing_brace():
    assert neutralize_labels_in_line(parse_pcode_line("}")) == parse_pcode_line("}")


def test_extract_jump_target_label_from_line_with_jump():
    assert extract_jump_target_label_from_line(parse_pcode_line("Jump L1")) == "L1"


def test_extract_jump_target_label_from_line_with_if():
    assert extract_jump_target_label_from_line(parse_pcode_line("If L2")) == "L2"


def test_extract_jump_target_label_from_line_with_label_prefix():
    assert extract_jump_target_label_from_line(parse_pcode_line("L1:Jump L2")) == "L2"
    assert extract_jump_target_label_from_line(parse_pcode_line("L1:If L2")) == "L2"


def test_extract_jump_target_label_from_line_without_labels():
    assert extract_jump_target_label_from_line(parse_pcode_line("Push 1")) is None


def test_extract_jump_target_label_from_line_without_target_label():
    assert extract_jump_target_label_from_line(parse_pcode_line("L1:Push 1")) is None


def test_extract_jump_target_label_from_line_empty_labeled_line():
    assert extract_jump_target_label_from_line(parse_pcode_line("lockjaw:")) is None


def test_extract_jump_target_label_from_line_labeled_closing_brace():
    assert extract_jump_target_label_from_line(parse_pcode_line("lockjaw:}")) is None


def test_build_label_alignment_map_empty_blocks():
    assert build_label_alignment_map([], []) == {}


def test_build_label_alignment_map_without_labels():
    lines = parse_pcode_lines(["Push 1", "Push 2", "Return"]).lines
    assert build_label_alignment_map(lines, lines) == {}


def test_build_label_alignment_map_simple_drift():
    block_a = sample_pcode("""
        Push register6
        Return
        L1:Push 1
        If L2
        Push "A"
        L2:Return
    """)

    block_b = sample_pcode("""
        L1: Push register6
        Return
        L10:Push 1
        If L11
        Push "A"
        L11:Return
    """)

    result = build_label_alignment_map(block_a.lines, block_b.lines)
    assert result == {"L10": "L1", "L11": "L2"}


def test_build_label_alignment_map_jump_targets_contribute_to_votes():
    block_a = sample_pcode("""
        Push 1
        Jump L1
        L1:Return
    """)

    block_b = sample_pcode("""
        Push 1
        Jump L10
        L10:Return
    """)

    result = build_label_alignment_map(block_a.lines, block_b.lines)
    assert result.get("L10") == "L1"


def test_build_label_alignment_map_with_identical_blocks_returns_identity():
    block = sample_pcode("""
        L1:Push 1
        If L2
        L2:Return
    """)

    result = build_label_alignment_map(block.lines, block.lines)
    assert result == {"L1": "L1", "L2": "L2"}


def test_build_label_alignment_map_with_completely_different_blocks():
    block_a = sample_pcode("""
        L1:Push "foo"
        L2:Push "bar"
    """)

    block_b = sample_pcode("""
        L10:Push "baz"
        L11:Push "qux"
    """)

    assert build_label_alignment_map(block_a.lines, block_b.lines) == {}


def test_build_label_alignment_map_tie_not_matched():
    # L10 and L11 in block_b both equally correspond to L1 in block_a. Tie -> dropped.
    # loc4 in block_b corresponds equally to L3 and L4 in block_a. Tie -> dropped.
    # (These p-code blocks are total non-sense regarding AVM1! Do not mind.)
    block_a = sample_pcode("""
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

    block_b = sample_pcode("""
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

    result = build_label_alignment_map(block_a.lines, block_b.lines)
    assert "L1" not in result.values()
    assert "loc4" not in result


def test_remap_labels_in_line_remaps_label_prefix():
    label_map = {"L1": "loc_001", "L2": "l214", "L3": "L_3", "loc12": "loc13"}
    assert remap_labels_in_line(parse_pcode_line("L1:Push 1"), label_map) == parse_pcode_line("loc_001:Push 1")
    assert remap_labels_in_line(parse_pcode_line("L2:StoreRegister 2"), label_map) == parse_pcode_line(
        "l214:StoreRegister 2"
    )


def test_remap_labels_in_line_remaps_jump_target():
    label_map = {"L1": "loc_001", "L2": "l214", "L3": "L_3", "loc12": "loc13"}
    assert remap_labels_in_line(parse_pcode_line("Jump L1"), label_map) == parse_pcode_line("Jump loc_001")
    assert remap_labels_in_line(parse_pcode_line("If loc12"), label_map) == parse_pcode_line("If loc13")


def test_remap_labels_in_line_remaps_both_prefix_and_jump_target():
    label_map = {"L1": "loc_001", "L2": "l214", "L3": "L_3", "loc12": "loc13"}
    assert remap_labels_in_line(parse_pcode_line("L1:Jump L2"), label_map) == parse_pcode_line("loc_001:Jump l214")
    assert remap_labels_in_line(parse_pcode_line("L3:If loc12"), label_map) == parse_pcode_line("L_3:If loc13")
    assert remap_labels_in_line(parse_pcode_line("loc456: Jump L2"), label_map) == parse_pcode_line("loc456:Jump l214")
    assert remap_labels_in_line(parse_pcode_line("L2: Jump loc456"), label_map) == parse_pcode_line("l214:Jump loc456")


def test_remap_labels_in_line_unknown_label_prefix_unchanged():
    assert remap_labels_in_line(parse_pcode_line("L4:Push register1"), {"L2": "l214", "L3": "L_3"}) == parse_pcode_line(
        "L4:Push register1"
    )


def test_remap_labels_in_line_unknown_jump_target_unchanged():
    assert remap_labels_in_line(parse_pcode_line("Jump L2"), {"L1": "loc_001"}) == parse_pcode_line("Jump L2")


def test_remap_labels_in_line_without_label_unchanged():
    label_map = {"L1": "loc_001", "L2": "l214", "L3": "L_3", "loc12": "loc13"}
    assert remap_labels_in_line(parse_pcode_line("Push 1"), label_map) == parse_pcode_line("Push 1")


def test_remap_labels_in_line_with_empty_map_unchanged():
    assert remap_labels_in_line(parse_pcode_line("L1: Push 1"), {}) == parse_pcode_line("L1: Push 1")
    assert remap_labels_in_line(parse_pcode_line("Jump L1"), {}) == parse_pcode_line("Jump L1")


def test_remap_labels_in_line_empty_labeled_line():
    assert remap_labels_in_line(parse_pcode_line("L214:"), {"L214": "toto"}) == parse_pcode_line("toto:")
    assert remap_labels_in_line(parse_pcode_line("L214:"), {"L215": "toto"}) == parse_pcode_line("L214:")


def test_remap_labels_in_line_labeled_closing_brace():
    assert remap_labels_in_line(parse_pcode_line("L214:}"), {"L214": "toto"}) == parse_pcode_line("toto:}")
    assert remap_labels_in_line(parse_pcode_line("L214:}"), {"L215": "toto"}) == parse_pcode_line("L214:}")


def test_remap_labels_in_line_unlabeled_closing_brace():
    assert remap_labels_in_line(parse_pcode_line("}"), {"L214": "toto"}) == parse_pcode_line("}")


def test_align_labels_for_diff_no_label_map_no_changes():
    block_a = sample_pcode("""
        Push 1
        Return
        Pop
        Push register3
        StoreRegister 4
    """)

    block_b = sample_pcode("""
        Push 1
        Return
        If loc78
        Pop
        Push register6
        StoreRegister 4
    """)

    assert align_labels(block_a.lines, block_b.lines) == block_b.lines


def test_align_labels_for_diff_unmapped_label_unchanged():
    block_a = sample_pcode("""
        Push 1
        Return
        If loc79
        Pop
        Push register6
        StoreRegister 4
    """)

    block_b = sample_pcode("""
        Push 1
        Return
        If loc78
        Pop
        L6:Push register6
        StoreRegister 4
    """)

    # L6 must stay untouched:
    assert (
        align_labels(block_a.lines, block_b.lines)
        == sample_pcode("""
        Push 1
        Return
        If loc79
        Pop
        L6:Push register6
        StoreRegister 4
    """).lines
    )


def test_align_labels():
    block_a = sample_pcode("""
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

    block_b = sample_pcode("""
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

    assert (
        align_labels(block_a.lines, block_b.lines)
        == sample_pcode("""
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
    """).lines
    )


def test_neutralize_registers_in_line_push_register():
    assert neutralize_registers_in_line(parse_pcode_line("Push register8")) == parse_pcode_line("Push registerN")
    assert neutralize_registers_in_line(parse_pcode_line("Push register8, 1")) == parse_pcode_line("Push registerN, 1")
    assert neutralize_registers_in_line(parse_pcode_line("Push 0, register4")) == parse_pcode_line("Push 0, registerN")
    assert neutralize_registers_in_line(parse_pcode_line("Push 0.5, register9")) == parse_pcode_line(
        "Push 0.5, registerN"
    )
    assert neutralize_registers_in_line(parse_pcode_line('Push register4, "toto"')) == parse_pcode_line(
        'Push registerN, "toto"'
    )
    assert neutralize_registers_in_line(parse_pcode_line('Push "caca", register12')) == parse_pcode_line(
        'Push "caca", registerN'
    )
    assert neutralize_registers_in_line(
        parse_pcode_line('Push register2, register3, "yabak", register10')
    ) == parse_pcode_line('Push registerN, registerN, "yabak", registerN')


def test_neutralize_registers_in_line_store_register():
    assert neutralize_registers_in_line(parse_pcode_line("StoreRegister 4")) == parse_pcode_line("StoreRegister N")


def test_neutralize_registers_in_line_try_register():
    assert neutralize_registers_in_line(parse_pcode_line("Try register4 {")) == parse_pcode_line("Try registerN {")
    assert neutralize_registers_in_line(parse_pcode_line("L1:Try register4 {")) == parse_pcode_line(
        "L1:Try registerN {"
    )


def test_neutralize_registers_in_line_label_unchanged():
    assert neutralize_registers_in_line(parse_pcode_line("L1:Push register8")) == parse_pcode_line("L1:Push registerN")
    assert neutralize_registers_in_line(parse_pcode_line("locmine:StoreRegister 56")) == parse_pcode_line(
        "locmine:StoreRegister N"
    )


def test_neutralize_registers_in_line_non_register_instructions_unchanged():
    assert neutralize_registers_in_line(parse_pcode_line("Push 1")) == parse_pcode_line("Push 1")
    assert neutralize_registers_in_line(parse_pcode_line("Add2")) == parse_pcode_line("Add2")
    assert neutralize_registers_in_line(parse_pcode_line("If loc96")) == parse_pcode_line("If loc96")
    assert neutralize_registers_in_line(parse_pcode_line("Try {")) == parse_pcode_line("Try {")
    assert neutralize_registers_in_line(parse_pcode_line('Try "register4" {')) == parse_pcode_line('Try "register4" {')


def test_neutralize_registers_in_line_empty_labeled_line():
    assert neutralize_registers_in_line(parse_pcode_line("loc2439:")) == parse_pcode_line("loc2439:")


def test_neutralize_registers_in_line_labeled_closing_brace():
    assert neutralize_registers_in_line(parse_pcode_line("loc2439:}")) == parse_pcode_line("loc2439:}")


def test_neutralize_registers_in_line_unlabeled_closing_brace():
    assert neutralize_registers_in_line(parse_pcode_line("}")) == parse_pcode_line("}")


def test_extract_register_indices_from_line_push_register():
    assert extract_register_indices_from_line(parse_pcode_line("Push register8")) == [8]
    assert extract_register_indices_from_line(parse_pcode_line("Push register8, 1")) == [8]
    assert extract_register_indices_from_line(parse_pcode_line("Push 0, register4")) == [4]
    assert extract_register_indices_from_line(parse_pcode_line("Push 0.5, register9")) == [9]
    assert extract_register_indices_from_line(parse_pcode_line('Push register4, "toto"')) == [4]
    assert extract_register_indices_from_line(parse_pcode_line('Push "caca", register12')) == [12]
    assert extract_register_indices_from_line(parse_pcode_line('Push register2, register3, "yabak", register10')) == [
        2,
        3,
        10,
    ]


def test_extract_register_indices_from_line_store_register():
    assert extract_register_indices_from_line(parse_pcode_line("StoreRegister 0")) == [0]


def test_extract_register_indices_from_line_try_register():
    assert extract_register_indices_from_line(parse_pcode_line("Try register4 {")) == [4]
    assert extract_register_indices_from_line(parse_pcode_line("L10g:Try register12 {")) == [12]


def test_extract_register_indices_from_line_without_registers():
    assert extract_register_indices_from_line(parse_pcode_line("Push 1")) == []
    assert extract_register_indices_from_line(parse_pcode_line('Push "dsfsdf"')) == []
    assert extract_register_indices_from_line(parse_pcode_line("GetMember")) == []
    assert extract_register_indices_from_line(parse_pcode_line("Pop")) == []
    assert extract_register_indices_from_line(parse_pcode_line('Try "register4" {')) == []


def test_build_register_alignment_map_empty_blocks():
    assert build_register_alignment_map([], []) == {}


def test_build_register_alignment_map_without_registers():
    block_a = sample_pcode("""
        Push 1
        Push 2
        Return
    """)

    block_b = sample_pcode("""
        Push 1
        Push 3
        Return
    """)

    assert build_register_alignment_map(block_a.lines, block_b.lines) == {}


def test_build_register_alignment_map_simple_drift():
    block_a = sample_pcode("""
        Push 0
        StoreRegister 4
        Push register4
        Push register6
        If l12
        Return
    """)

    block_b = sample_pcode("""
        Push 0
        StoreRegister 8
        Push register8
        Push register10
        If l12
        Return
    """)

    result = build_register_alignment_map(block_a.lines, block_b.lines)
    assert result == {8: 4, 10: 6}


def test_build_register_alignment_map_tie_not_matched():
    block_a = sample_pcode("""
        Push 0, register10
        StoreRegister 1
        Push 1
        StoreRegister 2
        Push register1
        Push register2
        Return
        StoreRegister 10
    """)

    block_b = sample_pcode("""
        Push 0, register5
        StoreRegister 7
        Push 1
        StoreRegister 7
        Push register7
        Push register7
        Return
        StoreRegister 6
    """)

    # register7 in block_b corresponds equally to register1 and register2 in block_a. Tie -> dropped.
    # register5 and register6 in block_b both equally correspond to register10 in block_a. Tie -> dropped.
    assert build_register_alignment_map(block_a.lines, block_b.lines) == {}


def test_remap_registers_in_line_push_register():
    register_map = {10: 11, 8: 4, 2: 10}
    assert remap_registers_in_line(parse_pcode_line("Push register8"), register_map) == parse_pcode_line(
        "Push register4"
    )
    assert remap_registers_in_line(
        parse_pcode_line('Push register2, register3, "yabak", register10'), register_map
    ) == parse_pcode_line('Push register10, register3, "yabak", register11')


def test_remap_registers_in_line_store_register():
    assert remap_registers_in_line(parse_pcode_line("StoreRegister 8"), {8: 4}) == parse_pcode_line("StoreRegister 4")


def test_remap_registers_in_line_try_register():
    assert remap_registers_in_line(parse_pcode_line("Try register8 {"), {8: 4}) == parse_pcode_line("Try register4 {")
    assert remap_registers_in_line(parse_pcode_line("loc1312:Try register8 {"), {8: 4}) == parse_pcode_line(
        "loc1312:Try register4 {"
    )


def test_remap_registers_in_line_unknown_register_unchanged():
    assert remap_registers_in_line(parse_pcode_line("Push register8"), {9: 4}) == parse_pcode_line("Push register8")
    assert remap_registers_in_line(parse_pcode_line("StoreRegister 8"), {9: 4}) == parse_pcode_line("StoreRegister 8")


def test_remap_registers_in_line_with_empty_map_unchanged():
    assert remap_registers_in_line(parse_pcode_line("StoreRegister 6"), {}) == parse_pcode_line("StoreRegister 6")
    assert remap_registers_in_line(parse_pcode_line("Push register10"), {}) == parse_pcode_line("Push register10")


def test_remap_registers_in_line_non_register_instructions_unchanged():
    assert remap_registers_in_line(parse_pcode_line("Push 1"), {1: 2}) == parse_pcode_line("Push 1")
    assert remap_registers_in_line(parse_pcode_line("Add2"), {2: 3}) == parse_pcode_line("Add2")
    assert remap_registers_in_line(parse_pcode_line("If loc96"), {96: 59}) == parse_pcode_line("If loc96")
    assert remap_registers_in_line(parse_pcode_line("Try {"), {1: 2}) == parse_pcode_line("Try {")
    assert remap_registers_in_line(parse_pcode_line('Try "register8" {'), {8: 2}) == parse_pcode_line(
        'Try "register8" {'
    )


def test_remap_registers_in_line_empty_labeled_line():
    assert remap_registers_in_line(parse_pcode_line("loc1312:"), {9: 4}) == parse_pcode_line("loc1312:")


def test_remap_registers_in_line_labeled_closing_brace():
    assert remap_registers_in_line(parse_pcode_line("loc1312:}"), {0: 7}) == parse_pcode_line("loc1312:}")


def test_remap_registers_in_line_unlabeled_closing_brace():
    assert remap_registers_in_line(parse_pcode_line("}"), {1: 3}) == parse_pcode_line("}")


def test_align_registers_renames_try_register_operands():
    block_a = sample_pcode("""
        Try register2 {
        Push 1
        Pop
        }
        Catch {
        Push register2
        Trace
        }
    """)

    block_b = sample_pcode("""
        Try register5 {
        Push 1
        Pop
        }
        Catch {
        Push register5
        Trace
        }
    """)

    assert align_registers(block_a.lines, block_b.lines) == block_a.lines


def test_align_registers_for_diff_no_register_map_no_changes():
    block_a = sample_pcode("""
        Push 1
        Return
        L051: Pop
    """)

    block_b = sample_pcode("""
        Push 1
        Return
        L051: Pop
    """)

    assert align_registers(block_a.lines, block_b.lines) == block_b.lines


def test_align_registers():
    block_a = sample_pcode("""
        L3:Push 0.2
        StoreRegister 4
        Push 1.1, register8
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
        StoreRegister 8
    """)

    block_b = sample_pcode("""
        L3:Push 0.2
        StoreRegister 4
        Push 1.1, register9
        Pop
        L8: Push register9
        Push register7
        If loc78
        Pop
        L9: Push "caca"
        Push register3
        If lbl002
        Push "m_count"
        GetMember
        StoreRegister 7
    """)

    assert (
        align_registers(block_a.lines, block_b.lines)
        == sample_pcode("""
        L3:Push 0.2
        StoreRegister 4
        Push 1.1, register8
        Pop
        L8:Push register8
        Push register7
        If loc78
        Pop
        L9: Push "caca"
        Push register1
        If lbl002
        Push "m_count"
        GetMember
        StoreRegister 7
    """).lines
    )


def test_align_block_b_on_block_a():
    # Those lines block each other:
    #   A: `L8: Push register8`
    #   B: `L10: Push register9`
    # The registers are different, so the label alignment pass does not touch the label.
    # Then, because the labels are still different, the register alignment pass does not touch the register.
    # This is an acceptable limitation of the technique.

    block_a = sample_pcode("""
        L3:Push 0.2
        StoreRegister 4
        Push 1.1, register8
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
        StoreRegister 8
    """)

    block_b = sample_pcode("""
        L5:Push 0.2
        StoreRegister 4
        Push 1.1, register9
        Pop
        L10: Push register9
        Push register7
        If loc78
        Pop
        L11: Push "caca"
        Push register3
        If loc_121
        Push "m_count"
        GetMember
        StoreRegister 7
    """)

    aligned = align_block_b_on_block_a(block_a, block_b)

    assert (
        aligned.lines
        == sample_pcode("""
        L3:Push 0.2
        StoreRegister 4
        Push 1.1, register9
        Pop
        L10:Push register9
        Push register7
        If loc78
        Pop
        L11: Push "caca"
        Push register1
        If lbl002
        Push "m_count"
        GetMember
        StoreRegister 7
    """).lines
    )
