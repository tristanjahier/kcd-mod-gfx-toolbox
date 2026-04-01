from pathlib import Path
from kcd_gfx_toolbox.avm1.pcode_normalization import (
    canonicalize_function_definition_headers,
    canonicalize_increment_decrement_patterns,
    canonicalize_labels,
    canonicalize_numeric_literals,
    canonicalize_push_lines,
    canonicalize_register_references_in_function_block,
    find_function_end_line,
    find_function_name_and_start_line,
    list_label_references,
    normalize_block,
    normalize_file,
    normalize_not_not_if_patterns,
    split_into_blocks,
    strip_unreferenced_label_definitions,
)
from kcd_gfx_toolbox.avm1.pcode_parsing import parse_pcode_file
from .helpers import sample_pcode, sample_text, sample_text_lines, list_data_files, read_data_file, get_test_data_dir
import re
from collections import Counter


def test_find_function_name_and_start_line_single_line():
    pcode_sample = sample_pcode("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        SetMember
        Push register2, "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 0.1, 0.0, register1, "GetMoney"
        CallMethod
        Push 1, "Math"
        GetVariable
    """)

    func_info = find_function_name_and_start_line(pcode_sample.lines, 6)

    assert func_info is not None

    func_start, func_name = func_info

    assert func_start == 5
    assert func_name == "GetMoneyForString"


def test_find_function_name_and_start_line_two_lines():
    pcode_sample = sample_pcode("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        SetMember
        Push register2
        Push "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 0.1, 0.0, register1, "GetMoney"
        CallMethod
        Push 1, "Math"
        GetVariable
    """)

    func_info = find_function_name_and_start_line(pcode_sample.lines, 7)

    assert func_info is not None

    func_start, func_name = func_info

    assert func_start == 5
    assert func_name == "GetMoneyForString"


def test_find_function_name_and_start_line_malformed_1():
    pcode_sample = sample_pcode("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        SetMember
        Push register2
        Pop
        Push "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 0.1, 0.0, register1, "GetMoney"
        CallMethod
        Push 1, "Math"
        GetVariable
    """)

    func_info = find_function_name_and_start_line(pcode_sample.lines, 8)

    assert func_info is None


def test_find_function_name_and_start_line_malformed_2():
    pcode_sample = sample_pcode("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        Push "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 0.1, 0.0, register1, "GetMoney"
        CallMethod
        Push 1, "Math"
        GetVariable
    """)

    func_info = find_function_name_and_start_line(pcode_sample.lines, 5)

    assert func_info is None


def test_find_function_end_line_standard():
    pcode_sample = sample_pcode("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        SetMember
        Push register2, "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 0.1, 0.0, register1, "GetMoney"
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
        DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {
        Push 0.0
    """)

    func_end = find_function_end_line(pcode_sample.lines, 6)

    assert func_end == 15


def test_find_function_end_line_nested():
    # The goal of this test is to ensure the function does not stop at a nested function boundary.
    pcode_sample = sample_pcode("""
        Push "GetRemoveCount"
        DefineFunction2 "", 3, 12, false, false, true, false, true, false, false, true, false, 2, "index", 3, "count", 4, "remove" {
        DefineFunction2 "computeTake", 2, 3, false, false, true, false, true, false, true, false, false, 1, "remaining", 2, "availableCount" {
        Push register1
        Push register2
        Less2
        If loc0632
        Push register2
        Jump loc0637
        loc0632:Push register1
        loc0637:Return
        }
        Push register5
        Return
        }
        SetMember
        Push register2
    """)

    func_end = find_function_end_line(pcode_sample.lines, 1)

    assert func_end == 14


def test_find_function_end_line_fallback():
    pcode_sample = sample_text_lines("""
        SetMember
        Push register2, "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 0.1, 0.0, register1, "GetMoney"
        CallMethod
        Push 1, "Math"
        GetVariable
        Push "round"
        CallMethod
        Multiply
    """)

    func_end = find_function_end_line(pcode_sample, 2)

    assert func_end == 9


def test_split_into_blocks():
    pcode_sample = sample_pcode(read_data_file("pcode/StashManager_v1.pcode"))
    blocks = split_into_blocks(pcode_sample)

    # There must be exactly the same number of blocks, with the same names (and occurrences).
    fixture_block_files = list_data_files("pcode/blocks/StashManager_v1")
    fixture_block_names = [p.stem for p in fixture_block_files]
    test_block_names = [block.name for block in blocks]
    assert Counter(fixture_block_names) == Counter(test_block_names), "Block names and count do not match exactly."

    # After we are sure that we have exactly the same set of block names, we compare their contents.

    for block in blocks:
        # A bit dirty, should remove the number prefixing from normalized blocks.
        block_file_name = f"{block.name}.pcode"
        fixture_block_file = get_test_data_dir() / "pcode/blocks/StashManager_v1" / block_file_name

        if fixture_block_file.is_file():
            block_text = block.render()
            fixture_block_text = fixture_block_file.read_text(encoding="utf-8").strip()
            assert block_text == fixture_block_text
            continue

        raise RuntimeError(f"Cannot find data fixture for {block.name} in pcode/blocks/StashManager_v1.")


def test_split_into_blocks_no_lookback_if_name_declared_in_function_definition_header():
    pcode_sample = sample_pcode("""
        Push register2, "WrongLookbackName"
        loc0400:DefineFunction2 "SetupElements", 0, 6, false, false, true, false, true, false, false, true, false {
        Push 0.0
        StoreRegister 4
        Pop
        }
        SetMember
    """)

    blocks = split_into_blocks(pcode_sample)

    assert [block.name for block in blocks] == ["__toplevel", "SetupElements"]

    assert blocks[1].render() == sample_text("""
        loc0400:DefineFunction2 "SetupElements", 0, 6, false, false, true, false, true, false, false, true, false {
        Push 0.0
        StoreRegister 4
        Pop
        }
        SetMember
    """)


def test_split_into_blocks_unnamed_function_uses_lookback_and_includes_binding_lines():
    pcode_sample = sample_pcode("""
        Push register3
        StoreRegister 4
        Pop
        Push register8
        Push "BoundByLookback"
        DefineFunction2 "", 1, 2, false, false, true, false, true, false, true, false, false, 1, "value" {
        Push register1
        Return
        }
        SetMember
    """)

    blocks = split_into_blocks(pcode_sample)

    assert [block.name for block in blocks] == ["__toplevel", "BoundByLookback"]

    assert blocks[1].render() == sample_text("""
        Push register8
        Push "BoundByLookback"
        DefineFunction2 "", 1, 2, false, false, true, false, true, false, true, false, false, 1, "value" {
        Push register1
        Return
        }
        SetMember
    """)


def test_split_into_blocks_drops_overlapping_lookback_for_unnamed_function():
    pcode_sample = sample_pcode("""
        Push register2
        Push "FirstFunction"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 1
        }
        SetMember
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 2
        }
        SetMember
    """)

    blocks = split_into_blocks(pcode_sample)

    assert [block.name for block in blocks] == ["FirstFunction", "__anonymous"]

    assert blocks[1].render() == sample_text("""
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 2
        }
        SetMember
    """)


def test_split_into_blocks_uses_fallback_name_for_unsafely_named_function():
    pcode_sample = sample_pcode("""
        Push register8
        Push "@!{}&"
        DefineFunction2 "", 1, 2, false, false, true, false, true, false, true, false, false, 1, "value" {
        Push register1
        Return
        }
        SetMember
    """)

    blocks = split_into_blocks(pcode_sample)

    assert [block.name for block in blocks] == ["__anonymous"]


def test_split_into_blocks_numbers_duplicate_block_names():
    pcode_sample = sample_pcode("""
        Push register2
        Push "SameName"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 1
        }
        SetMember
        If loc0e3c
        Push "_global"
        GetVariable
        Push register2
        Push "SameName"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 2
        }
        SetMember
        Push register2
        Push "E_IS_Condition"
        Push 4
        SetMember
    """)

    blocks = split_into_blocks(pcode_sample)

    assert [block.name for block in blocks] == ["SameName", "__toplevel", "SameName__2", "__toplevel__2"]


def test_canonicalize_push_lines():
    pcode_sample = sample_pcode("""
        Push register2
        If loc0bd4
        Push register1, "GetWeight"
        StoreRegister 4
        Push register2
        Push "Concat3"
        Pop
        Push "slots"
        GetMember
        StoreRegister 6
        loc0698:Push register7, "Toto"
    """)

    canonicalized = canonicalize_push_lines(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        If loc0bd4
        Push register1
        Push "GetWeight"
        StoreRegister 4
        Push register2
        Push "Concat3"
        Pop
        Push "slots"
        GetMember
        StoreRegister 6
        loc0698:Push register7
        Push "Toto"
    """)


def test_canonicalize_numeric_literals():
    pcode_sample = sample_pcode("""
        Push register1, "m_SlotsSize", 0.0
        SetMember
        Push -0
        StoreRegister 2
        Pop
        Push "type", 3.0, register7, "GetType"
        CallMethod
        Push -0.0, 8.2
    """)

    canonicalized = canonicalize_numeric_literals(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register1, "m_SlotsSize", 0
        SetMember
        Push 0
        StoreRegister 2
        Pop
        Push "type", 3, register7, "GetType"
        CallMethod
        Push 0, 8.2
    """)


def test_canonicalize_function_definition_headers():
    pcode_sample = sample_pcode("""
        Push register2
        Push "GetRemoveCount"
        DefineFunction2 "", 3, 12, false, false, true , false , true , false , false, true, false, 2, "index", 3, "count", 4, "remove"  {
        loc999754:DefineFunction2 "computeTake", 2, 3, false, false, true, false, true, false, true, false, false, 1, "remaining", 2, "availableCount"  {
        Push register1
        Push register2
        Less2
    """)

    canonicalized = canonicalize_function_definition_headers(pcode_sample.lines)

    # Test canonicalization to `DefineFunction` and label preservation.
    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        Push "GetRemoveCount"
        DefineFunction "", 3, "index", "count", "remove" {
        loc999754:DefineFunction "computeTake", 2, "remaining", "availableCount" {
        Push register1
        Push register2
        Less2
    """)


def test_canonicalize_register_references_in_function_block():
    pcode_sample = sample_pcode("""
        Push register2
        Push "SetItemQuantity"
        DefineFunction "", 1, "count" {
        Push register2, "m_Quantity"
        GetMember
        Push register8
        GetMember
        loc1312:
        Push 0.0
        StoreRegister 8
        Pop
        Push register3, register2
        Pop
        }
        SetMember
    """)

    canonicalized = canonicalize_register_references_in_function_block(pcode_sample.lines)

    # Test that canonicalization only happens inside of the function block.
    # (The first `register2` is untouched.)
    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        Push "SetItemQuantity"
        DefineFunction "", 1, "count" {
        Push register2, "m_Quantity"
        GetMember
        Push register1
        GetMember
        loc1312:
        Push 0.0
        StoreRegister 1
        Pop
        Push register3, register2
        Pop
        }
        SetMember
    """)


def test_canonicalize_register_references_in_non_function_block():
    pcode_sample = sample_pcode("""
        Push register2
        Push "m_SelectedCategory"
        Push 0
        SetMember
        Push register2
        Push "m_CurrentSort"
        Push 0
        SetMember
    """)

    canonicalized = canonicalize_register_references_in_function_block(pcode_sample.lines)

    # Test that canonicalization is skipped if not in a function block at all.
    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        Push "m_SelectedCategory"
        Push 0
        SetMember
        Push register2
        Push "m_CurrentSort"
        Push 0
        SetMember
    """)


def test_canonicalize_register_references_preserves_string_literals():
    pcode_sample = sample_pcode("""
        Push register2
        Push "SetItemQuantityInRegister8"
        DefineFunction "", 1, "count" {
        Push "register8"
        Push register8
        Push "StoreRegister 8"
        StoreRegister 8
        Push register2
        }
        SetMember
    """)

    canonicalized = canonicalize_register_references_in_function_block(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        Push "SetItemQuantityInRegister8"
        DefineFunction "", 1, "count" {
        Push "register8"
        Push register1
        Push "StoreRegister 8"
        StoreRegister 1
        Push register2
        }
        SetMember
    """)


def test_canonicalize_register_references_isolates_nested_function_scopes():
    pcode_sample = sample_pcode("""
        Push register2
        Push "SetItemQuantity"
        DefineFunction "", 0 {
        Push register9
        StoreRegister 9
        DefineFunction "inner", 0 {
        Push register42
        StoreRegister 42
        }
        Push register8
        StoreRegister 8
        }
        SetMember
    """)

    canonicalized = canonicalize_register_references_in_function_block(pcode_sample.lines)

    # Nested function register remapping must not affect parent function scope.
    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        Push "SetItemQuantity"
        DefineFunction "", 0 {
        Push register1
        StoreRegister 1
        DefineFunction "inner", 0 {
        Push register1
        StoreRegister 1
        }
        Push register2
        StoreRegister 2
        }
        SetMember
    """)


def test_canonicalize_register_references_prioritizes_written_registers():
    pcode_sample = sample_pcode("""
        Push register2
        Push "WriteFirstMapping"
        DefineFunction "", 0 {
        Push register9
        Push register8
        StoreRegister 8
        Push register8
        Push register5
        Return
        }
        SetMember
    """)

    canonicalized = canonicalize_register_references_in_function_block(pcode_sample.lines)

    # Register written through `StoreRegister 8` must get the first canonical index.
    # Read-only register9 and register5 are assigned afterwards.
    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        Push "WriteFirstMapping"
        DefineFunction "", 0 {
        Push register2
        Push register1
        StoreRegister 1
        Push register1
        Push register3
        Return
        }
        SetMember
    """)


def test_normalize_not_not_if_patterns():
    pcode_sample = sample_pcode("""
        Push register2
        Less2
        Not
        Not
        If loc0632
        Push register2
    """)

    canonicalized = normalize_not_not_if_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        Less2
        If loc0632
        Push register2
    """)


def test_normalize_not_not_if_patterns_with_labels():
    pcode_sample = sample_pcode("""
        Push register2
        loc1023:Less2
        Not
        Not
        loc1024:If loc0632
        Push register2
    """)

    canonicalized = normalize_not_not_if_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        loc1023:Less2
        loc1024:If loc0632
        Push register2
    """)


def test_normalize_not_not_if_patterns_with_label_on_not():
    pcode_sample = sample_pcode("""
        Push register2
        Less2
        loc1023:Not
        Not
        If loc0632
        Push register2
    """)

    canonicalized = normalize_not_not_if_patterns(pcode_sample.lines)

    # Test that simplification is skipped if there is a label on a `Not`.
    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register2
        Less2
        loc1023:Not
        Not
        If loc0632
        Push register2
    """)


def test_list_label_references():
    pcode_sample = sample_pcode("""
        loc454b:DefineFunction "foo", 0 {
        Push 1
        If loc07b7
        Jump loc07c7
        loc07b7:Push register7
        Increment
        StoreRegister 7
        Pop
        Jump loc0698
        loc07c7:Push register4
        Not
        If loc08fd
        }
    """)

    labels = list_label_references(pcode_sample.lines)

    assert labels == {"loc07b7", "loc07c7", "loc0698", "loc08fd"}


def test_strip_unreferenced_label_definitions():
    pcode_sample = sample_pcode("""
        loc454b:DefineFunction "foo", 0 {
        Push 1
        If loc07b7
        Jump loc07c7
        loc07b7:Push register7
        Increment
        StoreRegister 7
        Pop
        Jump loc0698
        loc07c7:Push register4
        Not
        If loc08fd
        }
    """)

    stripped = strip_unreferenced_label_definitions(pcode_sample.lines)

    # Note that references themselves are not touched, even if the label definition is not found.

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "foo", 0 {
        Push 1
        If loc07b7
        Jump loc07c7
        loc07b7:Push register7
        Increment
        StoreRegister 7
        Pop
        Jump loc0698
        loc07c7:Push register4
        Not
        If loc08fd
        }
    """)


def test_strip_unreferenced_label_definitions_drops_label_only_lines():
    pcode_sample = sample_pcode("""
        loc78f:
        Push 1
    """)

    stripped = strip_unreferenced_label_definitions(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        Push 1
    """)


def test_canonicalize_labels():
    pcode_sample = sample_pcode("""
        If loc07b7
        Jump loc07c7
        loc07b7:Push register7
        Increment
        StoreRegister 7
        Pop
        Jump loc0698
        loc07c7:Push register4
        Not
        If loc08fd
        Push 0
        StoreRegister 7
        Pop
        loc07df:Push register7, loc07c7 , "locoloco! loc07c7dsf.", "title"
        SetMember
    """)

    canonicalized = canonicalize_labels(pcode_sample.lines)

    # Note 1: tokens looking like label references are not replaced if they are not operands
    # of a If or Jump. Example: loc07c7.
    # Note 2: whitespace changes are normal because of PcodeLine rendering.
    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        If L0
        Jump L1
        L0:Push register7
        Increment
        StoreRegister 7
        Pop
        Jump L2
        L1:Push register4
        Not
        If L3
        Push 0
        StoreRegister 7
        Pop
        L4:Push register7, loc07c7, "locoloco! loc07c7dsf.", "title"
        SetMember
    """)


def test_canonicalize_labels_free_form_labels():
    pcode_sample = sample_pcode("""
        StrictEquals
        If labelous
        my_label: Push register0
        Push register1
        Push "E_IS_Condition"
        GetMember
        StrictEquals
        If L099
        Jump my_label
        end:Push "count"
    """)

    canonicalized = canonicalize_labels(pcode_sample.lines)

    # Note: whitespace changes are normal because of PcodeLine rendering.
    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        StrictEquals
        If L0
        L1:Push register0
        Push register1
        Push "E_IS_Condition"
        GetMember
        StrictEquals
        If L2
        Jump L1
        L3:Push "count"
    """)


def test_canonicalize_labels_idempotency():
    # An already canonical input should not change when re-canonicalized.
    pcode_sample = sample_pcode("""
        StrictEquals
        If L0
        L1:Push register0
        Push register1
        Push "E_IS_Condition"
        GetMember
        StrictEquals
        If L2
        Jump L1
        L3:Push "count"
    """)

    canonicalized = canonicalize_labels(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        StrictEquals
        If L0
        L1:Push register0
        Push register1
        Push "E_IS_Condition"
        GetMember
        StrictEquals
        If L2
        Jump L1
        L3:Push "count"
    """)


def test_canonicalize_increment_decrement_patterns_pushregister_increment_storeregister():
    pcode_sample = sample_pcode("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        Push 1
        Add2
        StoreRegister 4
        Pop
        Jump L8
        L7:Push register2
        Return
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        Increment
        StoreRegister 4
        Pop
        Jump L8
        L7:Push register2
        Return
    """)


def test_canonicalize_increment_decrement_patterns_pushregister_decrement_storeregister():
    pcode_sample = sample_pcode("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        Push 1
        Subtract
        StoreRegister 4
        Pop
        Jump L8
        L7:Push register2
        Return
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        Decrement
        StoreRegister 4
        Pop
        Jump L8
        L7:Push register2
        Return
    """)


def test_canonicalize_increment_decrement_patterns_pushregister_increment_return():
    pcode_sample = sample_pcode("""
        Push "TotoBinio"
        DefineFunction2 "", 1, 2, false, false, true, false, true, false, true, false, false, 1, "v" {
        Push register1
        Push 1
        Add2
        Return
        }
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push "TotoBinio"
        DefineFunction2 "", 1, 2, false, false, true, false, true, false, true, false, false, 1, "v" {
        Push register1
        Increment
        Return
        }
    """)


def test_canonicalize_increment_decrement_patterns_pushregister_decrement_return():
    pcode_sample = sample_pcode("""
        Push "TotoBinio"
        DefineFunction2 "", 1, 2, false, false, true, false, true, false, true, false, false, 1, "v" {
        Push register1
        Push 1
        Subtract
        Return
        }
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push "TotoBinio"
        DefineFunction2 "", 1, 2, false, false, true, false, true, false, true, false, false, 1, "v" {
        Push register1
        Decrement
        Return
        }
    """)


def test_canonicalize_increment_decrement_patterns_getmember_increment_setmember():
    pcode_sample = sample_pcode("""
        Push register1
        Push "pauseCounter"
        GetMember
        Push 1
        Add
        SetMember
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register1
        Push "pauseCounter"
        GetMember
        Increment
        SetMember
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)


def test_canonicalize_increment_decrement_patterns_getmember_decrement_setmember():
    pcode_sample = sample_pcode("""
        Push register1
        Push "pauseCounter"
        GetMember
        Push 1
        Subtract
        SetMember
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register1
        Push "pauseCounter"
        GetMember
        Decrement
        SetMember
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)


def test_canonicalize_increment_decrement_patterns_getmember_increment_return():
    pcode_sample = sample_pcode("""
        GetMember
        Push "_tweenList"
        GetMember
        Push "length"
        GetMember
        Push 1
        Add2
        Return
        }
        SetMember
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        GetMember
        Push "_tweenList"
        GetMember
        Push "length"
        GetMember
        Increment
        Return
        }
        SetMember
    """)


def test_canonicalize_increment_decrement_patterns_getmember_decrement_return():
    pcode_sample = sample_pcode("""
        GetMember
        Push "_tweenList"
        GetMember
        Push "length"
        GetMember
        Push 1
        Subtract
        Return
        }
        SetMember
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        GetMember
        Push "_tweenList"
        GetMember
        Push "length"
        GetMember
        Decrement
        Return
        }
        SetMember
    """)


def test_canonicalize_increment_decrement_patterns_getvariable_increment_setvariable():
    pcode_sample = sample_pcode("""
        Push "pauseCounter"
        GetVariable
        Push 1
        Add2
        SetVariable
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push "pauseCounter"
        GetVariable
        Increment
        SetVariable
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)


def test_canonicalize_increment_decrement_patterns_getvariable_decrement_setvariable():
    pcode_sample = sample_pcode("""
        Push "pauseCounter"
        GetVariable
        Push 1
        Subtract
        SetVariable
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push "pauseCounter"
        GetVariable
        Decrement
        SetVariable
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)


def test_canonicalize_increment_decrement_patterns_getvariable_increment_return():
    pcode_sample = sample_pcode("""
        Push "count"
        GetVariable
        Push 1
        Add2
        Return
        }
        SetMember
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push "count"
        GetVariable
        Increment
        Return
        }
        SetMember
    """)


def test_canonicalize_increment_decrement_patterns_getvariable_decrement_return():
    pcode_sample = sample_pcode("""
        Push "count"
        GetVariable
        Push 1
        Subtract
        Return
        }
        SetMember
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push "count"
        GetVariable
        Decrement
        Return
        }
        SetMember
    """)


def test_canonicalize_increment_decrement_patterns_with_label_in_the_way_unchanged():
    pcode_sample1 = sample_pcode("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        locblablu:Push 1
        Add2
        StoreRegister 4
        Pop
        Jump L8
        L7:Push register2
        Return
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample1.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        locblablu:Push 1
        Add2
        StoreRegister 4
        Pop
        Jump L8
        L7:Push register2
        Return
    """)

    pcode_sample2 = sample_pcode("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        Push 1
        loc789q:Add2
        StoreRegister 4
        Pop
        Jump L8
        L7:Push register2
        Return
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample2.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        Push 1
        loc789q:Add2
        StoreRegister 4
        Pop
        Jump L8
        L7:Push register2
        Return
    """)

    pcode_sample3 = sample_pcode("""
        Push "pauseCounter"
        GetVariable
        loc456t:Push 1
        Add2
        SetVariable
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample3.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push "pauseCounter"
        GetVariable
        loc456t:Push 1
        Add2
        SetVariable
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)

    pcode_sample4 = sample_pcode("""
        GetMember
        Push "_tweenList"
        GetMember
        Push "length"
        GetMember
        Push 1
        labelito:Subtract
        Return
        }
        SetMember
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample4.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        GetMember
        Push "_tweenList"
        GetMember
        Push "length"
        GetMember
        Push 1
        labelito:Subtract
        Return
        }
        SetMember
    """)


def test_canonicalize_increment_decrement_patterns_member_variable_mix_unchanged():
    pcode_sample1 = sample_pcode("""
        Push "pauseCounter"
        GetVariable
        Push 1
        Subtract
        SetMember
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample1.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push "pauseCounter"
        GetVariable
        Push 1
        Subtract
        SetMember
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)

    pcode_sample2 = sample_pcode("""
        Push register1
        Push "pauseCounter"
        GetMember
        Push 1
        Add2
        SetVariable
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample2.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register1
        Push "pauseCounter"
        GetMember
        Push 1
        Add2
        SetVariable
        Push "fastTravelIcon"
        GetVariable
        Push "visible"
        GetMember
        Not
    """)


def test_canonicalize_increment_decrement_patterns_registers_dont_match_unchanged():
    pcode_sample = sample_pcode("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        Push 1
        Add2
        StoreRegister 40
        Pop
        Jump L8
        L7:Push register2
        Return
    """)

    canonicalized = canonicalize_increment_decrement_patterns(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push register9
        Push "RemoveSlot"
        CallMethod
        Pop
        L10:Push register4
        Push 1
        Add2
        StoreRegister 40
        Pop
        Jump L8
        L7:Push register2
        Return
    """)


def test_normalize_block():
    raw_block_files = {p.name: p for p in list_data_files("pcode/blocks/StashManager_v1", glob="*.pcode")}
    normalized_block_files = {p.name: p for p in list_data_files("normalization/StashManager_v1", glob="*.pcode")}

    assert Counter(raw_block_files.keys()) == Counter(normalized_block_files.keys()), (
        "Block names and count do not match exactly between raw and normalized fixtures."
    )

    for block_file_name, raw_block_file in raw_block_files.items():
        raw_block = parse_pcode_file(raw_block_file)
        test_normalized_block = normalize_block(raw_block).render()

        fixture_file = normalized_block_files.get(block_file_name)
        assert fixture_file is not None, f"Missing fixture: tests/data/normalization/StashManager_v1/{block_file_name}"

        fixture_normalized_block = fixture_file.read_text(encoding="utf-8").strip()
        assert test_normalized_block == fixture_normalized_block, (
            f"Block {block_file_name} does not match with its normalized fixture."
        )


def test_normalize_file(tmp_path: Path):
    result = normalize_file(get_test_data_dir() / "pcode/StashManager_v1.pcode", tmp_path)

    test_blocks = {p.name: p for p in tmp_path.glob("*.pcode") if p.is_file()}
    fixture_blocks = {p.name: p for p in list_data_files("normalization/StashManager_v1", glob="*.pcode")}

    assert Counter(test_blocks.keys()) == Counter(fixture_blocks.keys()), (
        "Block names and count do not match exactly between test output and fixtures."
    )

    for fixture_name in fixture_blocks:
        fixture_normalized_block = read_data_file("normalization/StashManager_v1/" + fixture_name).strip()
        test_normalized_block = (tmp_path / fixture_name).read_text(encoding="utf-8").strip()
        assert test_normalized_block == fixture_normalized_block, (
            f"Block {test_normalized_block} does not match with its normalized fixture."
        )

    assert len(result.blocks) == len(test_blocks)
    assert result.total_blocks == len(test_blocks)


def test_normalize_file_generates_source_maps(tmp_path: Path):
    normalize_file(get_test_data_dir() / "pcode/StashManager_v2.pcode", tmp_path, write_source_maps=True)

    block_files = {p.name: p for p in tmp_path.glob("*.pcode") if p.is_file()}
    sourcemap_names = {p.stem: p for p in tmp_path.glob("*.pcode.map") if p.is_file()}

    assert Counter(block_files.keys()) == Counter(sourcemap_names.keys()), (
        "File names and count do not match exactly between normalized blocks and their sourcemaps."
    )


def test_normalize_file_can_omit_source_maps(tmp_path: Path):
    normalize_file(get_test_data_dir() / "pcode/StashManager_v2.pcode", tmp_path, write_source_maps=False)
    sourcemaps = {p for p in tmp_path.glob("*.pcode.map") if p.is_file()}
    assert len(sourcemaps) == 0
