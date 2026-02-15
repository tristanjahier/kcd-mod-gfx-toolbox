from kcd_gfx_toolbox.lib import avm1_pcode_normalization
from .helpers import sample_text_lines, list_data_files, read_data_file, get_test_data_dir
import re
from collections import Counter


def test_strip_label():
    assert avm1_pcode_normalization.strip_label("loc456: Push register3") == "Push register3"
    assert avm1_pcode_normalization.strip_label("Push register3") == "Push register3"
    assert avm1_pcode_normalization.strip_label("L9:If loc998") == "If loc998"


def test_find_function_name_and_start_line():
    pcode_sample = sample_text_lines("""
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

    func_info = avm1_pcode_normalization.find_function_name_and_start_line(pcode_sample, 6)

    assert func_info is not None

    func_start, func_name = func_info

    assert func_start == 5
    assert func_name == "GetMoneyForString"


def test_find_function_end_line_standard():
    pcode_sample = sample_text_lines("""
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

    func_end = avm1_pcode_normalization.find_function_end_line(pcode_sample, 6)

    assert func_end == 15


def test_find_function_end_line_nested():
    # The goal of this test is to ensure the function does not stop at a nested function boundary.
    pcode_sample = sample_text_lines("""
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

    func_end = avm1_pcode_normalization.find_function_end_line(pcode_sample, 1)

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

    func_end = avm1_pcode_normalization.find_function_end_line(pcode_sample, 2)

    assert func_end == 9


def test_split_into_blocks():
    pcode_sample = read_data_file("pcode/StashManager_v1.pcode")
    blocks = avm1_pcode_normalization.split_into_blocks(pcode_sample)

    # There must be exactly the same number of blocks, with the same names (and occurrences).
    fixture_block_files = list_data_files("pcode/blocks/StashManager_v1")
    fixture_block_names = [re.sub(r"^\d+_(.*)", r"\1", p.stem) for p in fixture_block_files]
    test_block_names = [bname for bname, _ in blocks]
    assert Counter(fixture_block_names) == Counter(test_block_names), "Block names and count do not match exactly."

    # After we are sure that we have exactly the same set of block names, we compare their contents.

    for idx, (block_name, block_lines) in enumerate(blocks, start=1):
        # A bit dirty, should remove the number prefixing from normalized blocks.
        block_file_name = f"{idx:03d}_{block_name}.pcode"
        fixture_block_file = get_test_data_dir() / "pcode/blocks/StashManager_v1" / block_file_name

        if fixture_block_file.is_file():
            block_text: str = "\n".join(block_lines)
            fixture_block_text = fixture_block_file.read_text(encoding="utf-8").strip()
            assert block_text == fixture_block_text
            continue

        raise RuntimeError(f"Cannot find data fixture for {block_name} in pcode/blocks/StashManager_v1.")


def test_split_comma_separated_operands():
    test1 = avm1_pcode_normalization.split_comma_separated_operands('register8, "GetType"')
    assert test1 == ["register8", '"GetType"']

    # Test that it never cuts in the middle of a string literal.
    test2 = avm1_pcode_normalization.split_comma_separated_operands('register8, "Hello, World!", 0.0')
    assert test2 == ["register8", '"Hello, World!"', "0.0"]


def test_extract_label_from_line_with_label():
    pcode_sample = "loc6454: Push register1"
    rest_of_line, label = avm1_pcode_normalization.extract_label_from_line(pcode_sample)
    assert label == "loc6454"
    assert rest_of_line == "Push register1"


def test_extract_label_from_line_without_label():
    pcode_sample = "StoreRegister 3"
    rest_of_line, label = avm1_pcode_normalization.extract_label_from_line(pcode_sample)
    assert label is None
    assert rest_of_line == "StoreRegister 3"


def test_line_has_label_true():
    assert avm1_pcode_normalization.line_has_label('loc042b:Push "count"') is True


def test_line_has_label_false():
    assert avm1_pcode_normalization.line_has_label("Jump loc055c") is False


def test_canonicalize_push_lines():
    pcode_sample = sample_text_lines("""
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

    canonicalized = avm1_pcode_normalization.canonicalize_push_lines(pcode_sample)

    assert canonicalized == sample_text_lines("""
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


def test_canonicalize_number_literals():
    pcode_sample = sample_text_lines("""
        Push register1, "m_SlotsSize", 0.0
        SetMember
        Push -0
        StoreRegister 2
        Pop
        Push "type", 3.0, register7, "GetType"
        CallMethod
    """)

    canonicalized = avm1_pcode_normalization.canonicalize_number_literals(pcode_sample)

    assert canonicalized == sample_text_lines("""
        Push register1, "m_SlotsSize", 0
        SetMember
        Push 0
        StoreRegister 2
        Pop
        Push "type", 3, register7, "GetType"
        CallMethod
    """)


def test_canonicalize_function_definition_headers():
    pcode_sample = sample_text_lines("""
        Push register2
        Push "GetRemoveCount"
        DefineFunction2 "", 3, 12, false, false, true , false , true , false , false, true, false, 2, "index", 3, "count", 4, "remove"  {
        loc999754:DefineFunction2 "computeTake", 2, 3, false, false, true, false, true, false, true, false, false, 1, "remaining", 2, "availableCount"  {
        Push register1
        Push register2
        Less2
    """)

    canonicalized = avm1_pcode_normalization.canonicalize_function_definition_headers(pcode_sample)

    # Test canonicalization to `DefineFunction` and label preservation.
    assert canonicalized == sample_text_lines("""
        Push register2
        Push "GetRemoveCount"
        DefineFunction "", 3, "index", "count", "remove" {
        loc999754:DefineFunction "computeTake", 2, "remaining", "availableCount" {
        Push register1
        Push register2
        Less2
    """)


def test_canonicalize_register_references_in_function_block():
    pcode_sample = sample_text_lines("""
        Push register2
        Push "SetItemQuantity"
        DefineFunction "", 1, "count" {
        Push register2, "m_Quantity"
        GetMember
        Push register8
        GetMember
        Push 0.0
        StoreRegister 8
        Pop
        Push register3, register2
        Pop
        }
        SetMember
    """)

    canonicalized = avm1_pcode_normalization.canonicalize_register_references_in_function_block(pcode_sample)

    # Test that canonicalization only happens inside of the function block.
    # (The first `register2` is untouched.)
    assert canonicalized == sample_text_lines("""
        Push register2
        Push "SetItemQuantity"
        DefineFunction "", 1, "count" {
        Push register1, "m_Quantity"
        GetMember
        Push register2
        GetMember
        Push 0.0
        StoreRegister 2
        Pop
        Push register3, register1
        Pop
        }
        SetMember
    """)


def test_canonicalize_register_references_in_non_function_block():
    pcode_sample = sample_text_lines("""
        Push register2
        Push "m_SelectedCategory"
        Push 0
        SetMember
        Push register2
        Push "m_CurrentSort"
        Push 0
        SetMember
    """)

    canonicalized = avm1_pcode_normalization.canonicalize_register_references_in_function_block(pcode_sample)

    # Test that canonicalization is skipped if not in a function block at all.
    assert canonicalized == sample_text_lines("""
        Push register2
        Push "m_SelectedCategory"
        Push 0
        SetMember
        Push register2
        Push "m_CurrentSort"
        Push 0
        SetMember
    """)


def test_normalize_not_not_if_patterns():
    pcode_sample = sample_text_lines("""
        Push register2
        Less2
        Not
        Not
        If loc0632
        Push register2
    """)

    canonicalized = avm1_pcode_normalization.normalize_not_not_if_patterns(pcode_sample)

    assert canonicalized == sample_text_lines("""
        Push register2
        Less2
        If loc0632
        Push register2
    """)


def test_normalize_not_not_if_patterns_with_labels():
    pcode_sample = sample_text_lines("""
        Push register2
        loc1023:Less2
        Not
        Not
        loc1024:If loc0632
        Push register2
    """)

    canonicalized = avm1_pcode_normalization.normalize_not_not_if_patterns(pcode_sample)

    assert canonicalized == sample_text_lines("""
        Push register2
        loc1023:Less2
        loc1024:If loc0632
        Push register2
    """)


def test_normalize_not_not_if_patterns_with_label_on_not():
    pcode_sample = sample_text_lines("""
        Push register2
        Less2
        loc1023:Not
        Not
        If loc0632
        Push register2
    """)

    canonicalized = avm1_pcode_normalization.normalize_not_not_if_patterns(pcode_sample)

    # Test that simplification is skipped if there is a label on a `Not`.
    assert canonicalized == sample_text_lines("""
        Push register2
        Less2
        loc1023:Not
        Not
        If loc0632
        Push register2
    """)


def test_canonicalize_labels():
    pcode_sample = sample_text_lines("""
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
        loc07df:Push register7
        Push register5
        Push "length"
        GetMember
    """)

    canonicalized = avm1_pcode_normalization.canonicalize_labels(pcode_sample)

    assert canonicalized == sample_text_lines("""
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
        L4:Push register7
        Push register5
        Push "length"
        GetMember
    """)


def test_normalize_block():
    raw_block_files = {p.name: p for p in list_data_files("pcode/blocks/StashManager_v1")}
    normalized_block_files = {p.name: p for p in list_data_files("normalization/StashManager_v1")}

    assert Counter(raw_block_files.keys()) == Counter(normalized_block_files.keys()), (
        "Block names and count do not match exactly between raw and normalized fixtures."
    )

    for block_file_name, raw_block_file in raw_block_files.items():
        raw_block = raw_block_file.read_text(encoding="utf-8")
        test_normalized_block = avm1_pcode_normalization.normalize_block(raw_block.splitlines()).strip()

        fixture_file = normalized_block_files.get(block_file_name)
        assert fixture_file is not None, f"Missing fixture: tests/data/normalization/StashManager_v1/{block_file_name}"

        fixture_normalized_block = fixture_file.read_text(encoding="utf-8").strip()
        assert test_normalized_block == fixture_normalized_block
