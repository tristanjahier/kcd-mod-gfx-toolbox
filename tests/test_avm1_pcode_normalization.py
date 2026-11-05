from collections import Counter
from pathlib import Path

from kcd_gfx_toolbox.avm1.pcode_normalization import (
    canonicalize_constant_pool,
    canonicalize_function_definition_headers,
    canonicalize_geturl2,
    canonicalize_increment_decrement_patterns,
    canonicalize_labels,
    canonicalize_numeric_literals,
    canonicalize_push_lines,
    canonicalize_register_references_in_function_block,
    canonicalize_string_concatenation,
    find_function_name_and_start_line,
    find_scope_end_line,
    list_label_references,
    normalize_block,
    normalize_file,
    normalize_not_not_if_patterns,
    split_into_blocks,
    strip_dead_undefined_register_initializers,
    strip_unreferenced_label_definitions,
)
from kcd_gfx_toolbox.avm1.pcode_parsing import parse_pcode_file

from .helpers import get_test_data_dir, list_data_files, read_data_file, sample_pcode, sample_text, sample_text_lines


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


def test_find_scope_end_line_standard():
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

    func_end = find_scope_end_line(pcode_sample.lines, 6)

    assert func_end == 15


def test_find_scope_end_line_nested():
    # The goal of this test is to ensure the function does not stop at a nested scope boundary.
    pcode_sample = sample_pcode("""
        Push "GetRemoveCount"
        DefineFunction2 "", 3, 12, false, false, true, false, true, false, false, true, false, 2, "index", 3, "count", 4, "remove" {
        DefineFunction2 "computeTake", 2, 3, false, false, true, false, true, false, true, false, false, 1, "remaining", 2, "availableCount" {
        Push register1
        Push register2
        Less2
        If loc0632
        Push register2
        Try register0 {
        Push register1, "onUpdateParams"
        GetMember
        }
        Catch {
        Push "Error"
        GetVariable
        }
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

    func_end = find_scope_end_line(pcode_sample.lines, 1)

    assert func_end == 22


def test_find_scope_end_line_fallback():
    pcode_sample = sample_pcode("""
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
    """).lines

    func_end = find_scope_end_line(pcode_sample, 2)

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


def test_split_into_blocks_deduplicates_block_names():
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

    assert [block.name for block in blocks] == ["SameName", "__toplevel", "SameName_2", "__toplevel_2"]


def test_split_into_blocks_deduplicates_block_names_case_insensitive():
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
        Push "sameName"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        Push 2
        }
        SetMember
    """)

    blocks = split_into_blocks(pcode_sample)

    assert [block.name for block in blocks] == ["SameName", "__toplevel", "sameName_2"]


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


def test_canonicalize_constant_pool():
    pcode_sample = sample_pcode("""
        ConstantPool "_global", "CestLaFete", "TotoCaca", "ASSetPropFlags"
        Push "_global"
        GetVariable
        Push "Inventory"
        GetMember
    """)

    canonicalized = canonicalize_constant_pool(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        ConstantPool ""
        Push "_global"
        GetVariable
        Push "Inventory"
        GetMember
    """)


def test_canonicalize_string_concatenation():
    pcode_sample = sample_pcode("""
        Push 0
        StoreRegister 1
        Pop
        L1:Push "FSCommand:"
        Push "OnSound"
        StringAdd
        Push "SELECT_ITEM"
        GetVariable
    """)

    canonicalized = canonicalize_string_concatenation(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        Push 0
        StoreRegister 1
        Pop
        L1:Push "FSCommand:OnSound"
        Push "SELECT_ITEM"
        GetVariable
    """)


def test_canonicalize_geturl2():
    pcode_sample = sample_pcode("""
        loc23247:Push "FSCommand:"
        Push "OnSound"
        StringAdd
        Push "NEGATIVE"
        GetVariable
        GetURL2 false, false, 1
        Jump loc23351
        loc23264:Push "_loc5_"
        GetVariable
        Push 1
        Push "_loc1_"
    """)

    canonicalized = canonicalize_geturl2(pcode_sample.lines)

    assert [ln.render() for ln in canonicalized] == sample_text_lines("""
        loc23247:Push "FSCommand:"
        Push "OnSound"
        StringAdd
        Push "NEGATIVE"
        GetVariable
        GetURL2 false, false, 0
        Jump loc23351
        loc23264:Push "_loc5_"
        GetVariable
        Push 1
        Push "_loc1_"
    """)


def test_strip_dead_undefined_register_initializers_leaves_non_function_blocks_untouched():
    pcode_sample = sample_pcode("""
        Push undefined
        StoreRegister 1
        Pop
        Push "x"
        Trace
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_ignores_the_undefined_string_literal():
    pcode_sample = sample_pcode("""
        DefineFunction "SetItemLabel", 0 {
        Push "undefined"
        StoreRegister 1
        Pop
        Push "x"
        Trace
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_prologue_steps_over_nested_functions():
    # The `If L0` line in the nested function must not end the outer prologue,
    # and its own initializer triple is out of scope.
    pcode_sample = sample_pcode("""
        DefineFunction "InitPlayerMenu", 0 {
        Push "helper"
        DefineFunction "", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push register2
        If L0
        L0:Push 1
        Return
        }
        SetVariable
        Push undefined
        StoreRegister 1
        Pop
        Push 5
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "InitPlayerMenu", 0 {
        Push "helper"
        DefineFunction "", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push register2
        If L0
        L0:Push 1
        Return
        }
        SetVariable
        Push 5
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)


def test_strip_dead_undefined_register_initializers_prologue_stops_at_the_first_referenced_label():
    # `L0` is targeted by `Jump L0` at the end, meaning that we are no longer in the prologue.
    # The triple itself is unlabeled and register1 is never read: only this boundary prevents the drop.
    pcode_sample = sample_pcode("""
        DefineFunction "AnimateCompass", 0 {
        L0:Push "x"
        Trace
        Push undefined
        StoreRegister 1
        Pop
        Jump L0
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_prologue_does_not_stop_at_an_unreferenced_label():
    # Nothing jumps to `L0`, so it does not end the prologue. Otherwise, the result would depend on
    # whether `strip_unreferenced_label_definitions` has already run, and normalization would not be idempotent.
    pcode_sample = sample_pcode("""
        DefineFunction "RefreshCompass", 0 {
        L0:Push "x"
        Trace
        Push undefined
        StoreRegister 1
        Pop
        Push "y"
        Trace
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "RefreshCompass", 0 {
        L0:Push "x"
        Trace
        Push "y"
        Trace
        }
    """)


def test_strip_dead_undefined_register_initializers_prologue_stops_at_the_first_branch():
    # The code after a branch may not run, so we are no longer in the prologue.
    # The triple itself is unlabeled and register1 is never read: only this boundary prevents the drop.
    pcode_sample = sample_pcode("""
        DefineFunction "UpdateMinimap", 0 {
        Push register2
        If L0
        Push undefined
        StoreRegister 1
        Pop
        Push "x"
        Trace
        L0:Push "y"
        Trace
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_prologue_stops_at_a_waitforframe():
    # Dropping an initializer triple after a `WaitForFrame` instruction is forbidden because
    # it would shift the instructions that would be skipped by `WaitForFrame`.
    pcode_sample = sample_pcode("""
        DefineFunction "ShowSplashScreen", 0 {
        WaitForFrame 5, 3
        Push undefined
        StoreRegister 1
        Pop
        Push 7
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_drops_a_triple_with_an_unreferenced_label():
    # Nothing jumps to `L0`, so the label does not prevent the drop. Otherwise, the result would depend on
    # whether `strip_unreferenced_label_definitions` has already run, and normalization would not be idempotent.
    pcode_sample = sample_pcode("""
        DefineFunction "RefreshCodex", 0 {
        Push "x"
        Trace
        Push undefined
        L0:StoreRegister 1
        Pop
        Push "y"
        Trace
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "RefreshCodex", 0 {
        Push "x"
        Trace
        Push "y"
        Trace
        }
    """)


def test_strip_dead_undefined_register_initializers_drops_when_the_register_is_never_read():
    # The initializer is the only write and there is no read at all: nothing can read the initial value.
    pcode_sample = sample_pcode("""
        DefineFunction "RefreshInventory", 0 {
        Push undefined
        StoreRegister 3
        Pop
        Push "done"
        Trace
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "RefreshInventory", 0 {
        Push "done"
        Trace
        }
    """)


def test_strip_dead_undefined_register_initializers_drops_when_every_branch_overwrites():
    # Exhaustive if/else: both arms write register1, so nothing can read its initial value.
    pcode_sample = sample_pcode("""
        DefineFunction "IsCursorInBounds", 2, "x", "y" {
        Push undefined
        StoreRegister 1
        Pop
        Push register2
        If L0
        Push true
        StoreRegister 1
        Pop
        Jump L1
        L0:Push false
        StoreRegister 1
        Pop
        L1:Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "IsCursorInBounds", 2, "x", "y" {
        Push register2
        If L0
        Push true
        StoreRegister 1
        Pop
        Jump L1
        L0:Push false
        StoreRegister 1
        Pop
        L1:Push register1
        Return
        }
    """)


def test_strip_dead_undefined_register_initializers_drops_when_a_branch_leaves_the_function():
    # `loc9443` is not defined in this function: this is the usual case where an `if (cond) return;`
    # compiles to a jump landing just past the block. That ends the function execution, and registers
    # should be scoped to it, so no read can follow it.
    # Here the only other path writes register1 first, leaving nothing able to observe `undefined` anyway.
    pcode_sample = sample_pcode("""
        DefineFunction "UpdateHealthBar", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push register2
        If loc9443
        Push 1
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "UpdateHealthBar", 0 {
        Push register2
        If loc9443
        Push 1
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)


def test_strip_dead_undefined_register_initializers_drops_when_the_read_is_after_a_return():
    # Nothing after `Return` runs, so the read below cannot observe the initializer value.
    pcode_sample = sample_pcode("""
        DefineFunction "CloseMenu", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push 0
        Return
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "CloseMenu", 0 {
        Push 0
        Return
        Push register1
        Return
        }
    """)


def test_strip_dead_undefined_register_initializers_drops_when_the_read_is_after_a_jump():
    # The read right after `Jump L0` never runs, and the jump target overwrites register1.
    pcode_sample = sample_pcode("""
        DefineFunction "SkipCutscene", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Jump L0
        Push register1
        Trace
        L0:Push 1
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "SkipCutscene", 0 {
        Jump L0
        Push register1
        Trace
        L0:Push 1
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)


def test_strip_dead_undefined_register_initializers_keeps_a_triple_with_a_referenced_label():
    # `If L0` lands on the initializer's `Push`: dropping the triple would remove a branch target.
    # register1 is never read: only the label prevents the drop.
    pcode_sample = sample_pcode("""
        DefineFunction "UpdateJournal", 0 {
        L0:Push undefined
        StoreRegister 1
        Pop
        Push register2
        If L0
        Push "y"
        Trace
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]

    # Same with the label on `StoreRegister`.
    pcode_sample = sample_pcode("""
        DefineFunction "UpdateJournal", 0 {
        Push undefined
        L0:StoreRegister 1
        Pop
        Push register2
        If L0
        Push "y"
        Trace
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]

    # Same with the label on `Pop`.
    pcode_sample = sample_pcode("""
        DefineFunction "UpdateJournal", 0 {
        Push undefined
        StoreRegister 1
        L0:Pop
        Push register2
        If L0
        Push "y"
        Trace
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_keeps_when_an_overwrite_can_be_jumped_over():
    # There is a write to register1, but with `If L0` it can be skipped entirely.
    pcode_sample = sample_pcode("""
        DefineFunction "GetTooltipText", 1, "flag" {
        Push undefined
        StoreRegister 1
        Pop
        Push register2
        If L0
        Push 1
        StoreRegister 1
        Pop
        L0:Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_keeps_when_a_read_follows_a_conditional_exit():
    # Same as `drops_when_a_branch_leaves_the_function`, except that here one execution path can read
    # the initial value of `register1`.
    pcode_sample = sample_pcode("""
        DefineFunction "GetQuestMarker", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push register2
        If loc9443
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_keeps_when_a_branch_targets_the_block_past_the_function():
    # `L9` is on the block's trailing `SetMember`: inside the block, outside the function. That is
    # the address right after the function body, so in reality this jump leaves the function, the
    # way a bare `return;` does. The control-flow analysis currently cannot tell it apart from a jump
    # into surrounding block code, so it resolves it as `UNRESOLVED` and keeps the initializer.
    # This is a known limitation (see `BranchResolution.UNRESOLVED`); if it is improved, the expected
    # output becomes a drop.
    pcode_sample = sample_pcode("""
        Push register2
        Push "OnCloseClicked"
        DefineFunction "", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Jump L9
        Push 1
        StoreRegister 1
        Pop
        Push register1
        Return
        }
        L9:SetMember
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_does_not_flow_into_a_nested_function_body():
    # Defining the nested function does not execute it, so its write to register1 does not protect the read
    # of register1 that follows its definition in the outer function body.
    pcode_sample = sample_pcode("""
        DefineFunction "BuildTradeMenu", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push "helper"
        DefineFunction "", 0 {
        Push 1
        StoreRegister 1
        Pop
        }
        SetVariable
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_flows_through_a_blank_labeled_line():
    # Both paths from `If L0` go through the blank `L0:` line and reach the read of register1.
    pcode_sample = sample_pcode("""
        DefineFunction "ToggleMapLayer", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push register2
        If L0
        L0:
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_keeps_when_a_throw_can_be_reached():
    # `Throw` lands on a handler that could read `register1`, whereas the write below it never runs.
    pcode_sample = sample_pcode("""
        DefineFunction "ValidateRecipe", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push "error"
        Throw
        Push 1
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_keeps_when_a_try_can_be_reached():
    # Control can reach `Try` with the initial value of `register1` still in place,
    # and what happens from there is not modeled.
    pcode_sample = sample_pcode("""
        DefineFunction "LoadSaveGame", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Try register2 {
        Push "x"
        Trace
        }
        Catch {
        Push "y"
        Trace
        }
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_keeps_when_a_waitforframe_can_be_reached():
    # `WaitForFrame` skips a number of actions instead of branching to a label, so the write to
    # register1 below may or may not run. Static analysis cannot determine the runtime behaviour,
    # so we must keep the initializer.
    pcode_sample = sample_pcode("""
        DefineFunction "ShowLoadingScreen", 0 {
        Push undefined
        StoreRegister 1
        Pop
        WaitForFrame 5, 2
        Push 1
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_keeps_when_a_waitforframe2_can_be_reached():
    # Same as `WaitForFrame` above: the write to register1 may be skipped.
    pcode_sample = sample_pcode("""
        DefineFunction "ShowSavingScreen", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push 5
        WaitForFrame2 2
        Push 1
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == [ln.render() for ln in pcode_sample.lines]


def test_strip_dead_undefined_register_initializers_preserves_source_lines_of_dropped_lines():
    pcode_sample = sample_pcode("""
        DefineFunction "ClearNotifications", 0 {
        Push undefined
        StoreRegister 3
        Pop
        Push "done"
        Trace
        }
    """)

    stripped = strip_dead_undefined_register_initializers(pcode_sample.lines)

    assert [ln.render() for ln in stripped] == sample_text_lines("""
        DefineFunction "ClearNotifications", 0 {
        Push "done"
        Trace
        }
    """)

    # No source line is stranded: the block still maps onto exactly what it mapped onto before.
    assert sorted({s for ln in stripped for s in ln.source_lines}) == sorted(
        {s for ln in pcode_sample.lines for s in ln.source_lines}
    )

    # The dropped triple's mapping lands on the preceding survivor, the function header.
    assert stripped[0].source_lines == [1, 2, 3, 4]


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


def test_normalize_block_closes_the_register_gap_left_by_a_dead_undefined_initializer():
    # register1 is initialized but never read: its initializer triple will be dropped.
    # As it was the only write of register1, its index, 1, will be freed and the register
    # canonicalization pass that comes after must close the gap.
    # If that canonicalization pass was done _before_ stripping dead initializers,
    # register2 would keep its index, hence resulting in different register numbers between
    # two scripts that only really differ by that dead initializer.
    pcode_sample = sample_pcode("""
        DefineFunction "UpdateWeightDisplay", 0 {
        Push undefined
        StoreRegister 1
        Pop
        Push 7
        StoreRegister 2
        Pop
        Push register2
        Return
        }
    """)

    normalized = normalize_block(pcode_sample)

    assert [ln.render() for ln in normalized.lines] == sample_text_lines("""
        DefineFunction "UpdateWeightDisplay", 0 {
        Push 7
        StoreRegister 1
        Pop
        Push register1
        Return
        }
    """)


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
