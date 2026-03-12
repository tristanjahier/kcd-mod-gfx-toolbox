import pytest
from kcd_gfx_toolbox.avm1 import pcode_parsing
from kcd_gfx_toolbox.avm1.pcode_parsing import (
    PcodeBlankLineWithLabel,
    PcodeBlock,
    PcodeInstruction,
    PcodeOperand,
    PcodeStructural,
    is_pcode_instruction,
    parse_pcode_lines,
    tokenize_line,
)
from .helpers import get_test_data_dir, sample_text, sample_text_lines


def test_tokenize_line():
    # DO NOT FORGET that \\ will only render 1 character in the resulting string!

    pcode_sample = ' label56:Push register1,, N "cagada, \\" ah:ah",    0.0, 6 {}  '
    tokens = tokenize_line(pcode_sample)

    assert tokens == [
        (1, "label56"),
        (8, ":"),
        (9, "Push"),
        (14, "register1"),
        (23, ","),
        (24, ","),
        (26, "N"),
        (28, '"cagada, \\" ah:ah"'),
        (46, ","),
        (51, "0.0"),
        (54, ","),
        (56, "6"),
        (58, "{"),
        (59, "}"),
    ]


def test_tokenize_line_with_non_quoted_backslash():
    tokens = tokenize_line("A B\\, 1312")
    assert tokens == [(0, "A"), (2, "B\\"), (4, ","), (6, "1312")]


def test_parse_pcode_lines():
    pcode_sample = sample_text_lines("""
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

    pcode_block = pcode_parsing.parse_pcode_lines(pcode_sample)

    assert pcode_block == PcodeBlock(
        lines=[
            PcodeInstruction(
                source_lines=[0],
                opcode="Push",
                operands=[
                    PcodeOperand(type="symbol", value="register1"),
                    PcodeOperand(type="string", value="m_DisplayedData"),
                    PcodeOperand(type="numeric", value="0.0"),
                    PcodeOperand(type="string", value="Array"),
                ],
                label=None,
            ),
            PcodeInstruction(source_lines=[1], opcode="NewObject"),
            PcodeInstruction(source_lines=[2], opcode="SetMember"),
            PcodeStructural(source_lines=[3], value="}"),
            PcodeInstruction(source_lines=[4], opcode="SetMember"),
            PcodeInstruction(
                source_lines=[5],
                opcode="Push",
                operands=[
                    PcodeOperand(type="symbol", value="register2"),
                    PcodeOperand(type="string", value="GetMoneyForString"),
                ],
            ),
            PcodeInstruction(
                source_lines=[6],
                opcode="DefineFunction2",
                operands=[
                    PcodeOperand(type="string", value=""),
                    PcodeOperand(type="numeric", value="0"),
                    PcodeOperand(type="numeric", value="2"),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                ],
            ),
            PcodeInstruction(
                source_lines=[7],
                opcode="Push",
                operands=[
                    PcodeOperand(type="numeric", value="0.1"),
                    PcodeOperand(type="numeric", value="0.0"),
                    PcodeOperand(type="symbol", value="register1"),
                    PcodeOperand(type="string", value="GetMoney"),
                ],
                label="loc4vs5",
            ),
            PcodeInstruction(source_lines=[8], opcode="CallMethod"),
            PcodeInstruction(
                source_lines=[9],
                opcode="Push",
                operands=[PcodeOperand(type="numeric", value="1"), PcodeOperand(type="string", value="Math")],
            ),
            PcodeInstruction(source_lines=[10], opcode="GetVariable"),
            PcodeInstruction(
                source_lines=[11],
                opcode="Push",
                operands=[PcodeOperand(type="string", value="round")],
            ),
            PcodeInstruction(source_lines=[12], opcode="CallMethod"),
            PcodeInstruction(source_lines=[13], opcode="Multiply"),
            PcodeInstruction(source_lines=[14], opcode="Return"),
            PcodeStructural(source_lines=[15], value="}"),
            PcodeInstruction(source_lines=[17], opcode="SetMember"),
            PcodeInstruction(
                source_lines=[18],
                opcode="Push",
                operands=[
                    PcodeOperand(type="symbol", value="register2"),
                    PcodeOperand(type="string", value="GetMoney"),
                ],
            ),
            PcodeInstruction(
                source_lines=[19],
                opcode="DefineFunction2",
                operands=[
                    PcodeOperand(type="string", value=""),
                    PcodeOperand(type="numeric", value="0"),
                    PcodeOperand(type="numeric", value="5"),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                ],
                label="loc1312",
            ),
            PcodeInstruction(
                source_lines=[20],
                opcode="Push",
                operands=[PcodeOperand(type="numeric", value="0.0")],
            ),
            PcodeBlankLineWithLabel(source_lines=[21], label="loc78f"),
            PcodeInstruction(source_lines=[22], opcode="Push", operands=[PcodeOperand(type="numeric", value="-1")]),
            PcodeInstruction(source_lines=[23], opcode="Add2"),
            PcodeInstruction(source_lines=[24], opcode="Push", operands=[PcodeOperand(type="numeric", value="-1.3")]),
            PcodeInstruction(source_lines=[25], opcode="Subtract"),
        ]
    )


def test_parse_pcode_lines_label_on_delimiter():
    pcode_sample = sample_text_lines("""
        loc4qsd6:}
    """)

    assert pcode_parsing.parse_pcode_lines(pcode_sample) == PcodeBlock(
        lines=[PcodeStructural(source_lines=[0], value="}", label="loc4qsd6")]
    )


def test_parse_pcode_file():
    file_path = get_test_data_dir() / "pcode/sample.pcode"
    pcode_block = pcode_parsing.parse_pcode_file(file_path)

    assert pcode_block == PcodeBlock(
        lines=[
            PcodeInstruction(
                source_lines=[0], opcode="StoreRegister", operands=[PcodeOperand(type="numeric", value="1")]
            ),
            PcodeInstruction(source_lines=[1], opcode="SetMember"),
            PcodeInstruction(
                source_lines=[2], opcode="Push", operands=[PcodeOperand(type="symbol", value="register1")]
            ),
            PcodeInstruction(
                source_lines=[3], opcode="Push", operands=[PcodeOperand(type="string", value="prototype")]
            ),
            PcodeInstruction(source_lines=[4], opcode="GetMember", label="loc78j2"),
            PcodeInstruction(
                source_lines=[5], opcode="StoreRegister", operands=[PcodeOperand(type="numeric", value="2")]
            ),
            PcodeInstruction(source_lines=[6], opcode="Pop"),
        ]
    )


def test_PcodeBlock_render():
    pcode_block = PcodeBlock(
        lines=[
            PcodeInstruction(
                source_lines=[0],
                opcode="Push",
                operands=[
                    PcodeOperand(type="symbol", value="register1"),
                    PcodeOperand(type="string", value="m_DisplayedData"),
                    PcodeOperand(type="numeric", value="0.0"),
                    PcodeOperand(type="string", value="Array"),
                ],
                label=None,
            ),
            PcodeInstruction(source_lines=[1], opcode="NewObject"),
            PcodeInstruction(source_lines=[2], opcode="SetMember"),
            PcodeStructural(source_lines=[3], value="}"),
            PcodeInstruction(source_lines=[4], opcode="SetMember"),
            PcodeInstruction(
                source_lines=[5],
                opcode="Push",
                operands=[
                    PcodeOperand(type="symbol", value="register2"),
                    PcodeOperand(type="string", value="GetMoneyForString"),
                ],
            ),
            PcodeInstruction(
                source_lines=[6],
                opcode="DefineFunction2",
                operands=[
                    PcodeOperand(type="string", value=""),
                    PcodeOperand(type="numeric", value="0"),
                    PcodeOperand(type="numeric", value="2"),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                ],
            ),
            PcodeInstruction(
                source_lines=[7],
                opcode="Push",
                operands=[
                    PcodeOperand(type="numeric", value="0.1"),
                    PcodeOperand(type="numeric", value="0.0"),
                    PcodeOperand(type="symbol", value="register1"),
                    PcodeOperand(type="string", value="GetMoney"),
                ],
                label="loc4vs5",
            ),
            PcodeInstruction(source_lines=[8], opcode="CallMethod"),
            PcodeInstruction(
                source_lines=[9],
                opcode="Push",
                operands=[PcodeOperand(type="numeric", value="1"), PcodeOperand(type="string", value="Math")],
            ),
            PcodeInstruction(source_lines=[10], opcode="GetVariable"),
            PcodeInstruction(
                source_lines=[11],
                opcode="Push",
                operands=[PcodeOperand(type="string", value="round")],
            ),
            PcodeInstruction(source_lines=[12], opcode="CallMethod"),
            PcodeInstruction(source_lines=[13], opcode="Multiply"),
            PcodeInstruction(source_lines=[14], opcode="Return"),
            PcodeStructural(source_lines=[15], value="}"),
            PcodeInstruction(source_lines=[16], opcode="SetMember"),
            PcodeInstruction(
                source_lines=[17],
                opcode="Push",
                operands=[
                    PcodeOperand(type="symbol", value="register2"),
                    PcodeOperand(type="string", value="GetMoney"),
                ],
            ),
            PcodeInstruction(
                source_lines=[18],
                opcode="DefineFunction2",
                operands=[
                    PcodeOperand(type="string", value=""),
                    PcodeOperand(type="numeric", value="0"),
                    PcodeOperand(type="numeric", value="5"),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=False),
                    PcodeOperand(type="boolean", value=True),
                    PcodeOperand(type="boolean", value=False),
                ],
                label="loc1312",
            ),
            PcodeInstruction(
                source_lines=[19],
                opcode="Push",
                operands=[PcodeOperand(type="numeric", value="0.0")],
            ),
        ]
    )

    assert pcode_block.render() == sample_text("""
        Push register1, "m_DisplayedData", 0.0, "Array"
        NewObject
        SetMember
        }
        SetMember
        Push register2, "GetMoneyForString"
        DefineFunction2 "", 0, 2, false, false, true, false, true, false, false, true, false {
        loc4vs5:Push 0.1, 0.0, register1, "GetMoney"
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
        loc1312:DefineFunction2 "", 0, 5, false, false, true, false, true, false, false, true, false {
        Push 0.0
    """)


def test_PcodeBlock_render_label_on_delimiter():
    pcode_block = PcodeBlock(lines=[PcodeStructural(source_lines=[0], value="}", label="loc4qsd6")])

    assert pcode_block.render() == "loc4qsd6:}"


def test_PcodeBlock_render_label_on_blank_line():
    pcode_block = PcodeBlock(lines=[PcodeBlankLineWithLabel(source_lines=[90], label="L311")])

    assert pcode_block.render() == "L311:"


def test_PcodeBlock_render_canonicalizes_whitespace():
    pcode_sample = sample_text_lines("""
        Push register2
        If loc4bsdf4
        L200:Push register1,"GetWeight"
        StoreRegister  4
         Push register2
        Push "Concat3"
        Pop

        DefineFunction2 "computeTake", 2 ,  3 ,   false,false,true,false ,true ,false,true, false, false, 1, "remaining", 2,"availableCount"{
        loc0698:Push   register7,   "Toto"
    """)

    assert parse_pcode_lines(pcode_sample).render() == sample_text("""
        Push register2
        If loc4bsdf4
        L200:Push register1, "GetWeight"
        StoreRegister 4
        Push register2
        Push "Concat3"
        Pop
        DefineFunction2 "computeTake", 2, 3, false, false, true, false, true, false, true, false, false, 1, "remaining", 2, "availableCount" {
        loc0698:Push register7, "Toto"
    """)


def test_PcodeLine_replace():
    pcode_line = PcodeInstruction(
        source_lines=[17],
        opcode="Push",
        operands=[
            PcodeOperand(type="symbol", value="register2"),
            PcodeOperand(type="string", value="GetMoney"),
        ],
    )

    new_pcode_line = pcode_line.replace(opcode="SetMember", source_lines=[6], label="yapyap")

    assert new_pcode_line is not pcode_line
    assert new_pcode_line == PcodeInstruction(
        source_lines=[6],
        opcode="SetMember",
        operands=[
            PcodeOperand(type="symbol", value="register2"),
            PcodeOperand(type="string", value="GetMoney"),
        ],
        label="yapyap",
    )


def test_is_pcode_instruction():
    assert is_pcode_instruction(PcodeInstruction(source_lines=[1312], opcode="Toto"))
    assert not is_pcode_instruction(PcodeStructural(source_lines=[1312], value="}"))
    assert not is_pcode_instruction(PcodeBlankLineWithLabel(source_lines=[1312], label="lbl456qs"))
    assert not is_pcode_instruction(None)


def test_PcodeBlankLineWithLabel_instanciation_without_label():
    with pytest.raises(ValueError, match="Label cannot be None or blank in PcodeBlankLineWithLabel."):
        PcodeBlankLineWithLabel(source_lines=[5], label=None)
