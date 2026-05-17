from dataclasses import dataclass
import pytest
from kcd_gfx_toolbox.avm1.pcode_parsing import PcodeBlock, PcodeLine
from kcd_gfx_toolbox.diff.core import TextHunk, TextHunkLine
from kcd_gfx_toolbox.diff.rendering import (
    RenderDiffSpanPair,
    _convert_span_from_normalized_pcode_to_raw,
    _convert_span_from_pcode_to_actionscript,
    _merge_overlapping_span_pairs,
    _merge_overlapping_hunk_pairs,
)


@dataclass(frozen=True, kw_only=True)
class DummyPcodeLine(PcodeLine):
    """Dummy p-code line implementation without parsing. For when only `source_lines` is important."""

    text: str

    def render(self) -> str:
        return self.text


def _pcode_ln(text: str, src: list[int]) -> PcodeLine:
    return DummyPcodeLine(text=text, source_lines=src)


def _hunk_ln(index: int, text: str, **kwargs) -> TextHunkLine:
    return TextHunkLine(index=index, text=text, **kwargs)


def _hunk_ctx(index: int, text: str) -> TextHunkLine:
    return _hunk_ln(index, text, is_context=True)


def _fake_corpus_with_lines(lines: dict[int, str]) -> list[str]:
    """Build a corpus with input indexed lines and fill in the gaps (from 0) with placeholders."""
    return [lines.get(i, f"<filler line {i}>") for i in range(max(lines) + 1)]


def test_convert_span_from_normalized_pcode_to_raw_start_anchor_span():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("StoreRegister 1", [510]),
            _pcode_ln("SetMember", [511]),
            _pcode_ln("Push register1", [512]),
            _pcode_ln('Push "prototype"', [512]),
            _pcode_ln("loc78j2: GetMember", [513]),
            _pcode_ln("StoreRegister 2", [514]),
            _pcode_ln("Pop", [515]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((0, 0), normalized_block)
    assert raw_span == (510, 510)


def test_convert_span_from_normalized_pcode_to_raw_middle_anchor_span():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("StoreRegister 1", [15]),
            _pcode_ln("SetMember", [16]),
            _pcode_ln("Push register1", [17]),
            _pcode_ln('Push "prototype"', [17]),
            _pcode_ln("loc78j2: GetMember", [18]),
            _pcode_ln("StoreRegister 2", [19]),
            _pcode_ln("Pop", [20]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((4, 4), normalized_block)
    assert raw_span == (18, 18)


def test_convert_span_from_normalized_pcode_to_raw_end_anchor_span():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("StoreRegister 1", [2615]),
            _pcode_ln("SetMember", [2616]),
            _pcode_ln("Push register1", [2617]),
            _pcode_ln('Push "prototype"', [2617]),
            _pcode_ln("loc78j2: GetMember", [2618]),
            _pcode_ln("StoreRegister 2", [2619]),
            _pcode_ln("Pop", [2620]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((7, 7), normalized_block)
    assert raw_span == (2621, 2621)


def test_convert_span_from_normalized_pcode_to_raw_start_span():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln('ConstantPool "_global", "HudMainController", "m_PlayerName", "Henry"', [538]),
            _pcode_ln('Push "_global"', [539]),
            _pcode_ln("GetVariable", [540]),
            _pcode_ln("StoreRegister 1", [541]),
            _pcode_ln("SetMember", [542]),
            _pcode_ln("Push register1", [543]),
            _pcode_ln('Push "prototype"', [543]),
            _pcode_ln("loc78j2: GetMember", [544]),
            _pcode_ln("StoreRegister 2", [545]),
            _pcode_ln("Pop", [546]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((0, 3), normalized_block)
    assert raw_span == (538, 541)


def test_convert_span_from_normalized_pcode_to_raw_middle_span():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("Push register2", [0]),
            _pcode_ln('Push "GetMoneyForString"', [0]),
            _pcode_ln('DefineFunction "", 0 {', [1]),
            _pcode_ln("loc4vs5: Push 0.1", [2]),
            _pcode_ln("Push 0.0", [2]),
            _pcode_ln("Push register1", [2]),
            _pcode_ln('Push "GetMoney"', [2]),
            _pcode_ln("CallMethod", [3]),
            _pcode_ln("Push 1", [4]),
            _pcode_ln('Push "Math"', [4]),
            _pcode_ln("GetVariable", [5]),
            _pcode_ln('Push "round"', [6]),
            _pcode_ln("CallMethod", [7]),
            _pcode_ln("Multiply", [8]),
            _pcode_ln("Return", [9]),
            _pcode_ln("}", [10]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((11, 13), normalized_block)
    assert raw_span == (6, 8)


def test_convert_span_from_normalized_pcode_to_raw_end_span():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("StoreRegister 1", [1293]),
            _pcode_ln("SetMember", [1294]),
            _pcode_ln("Push register1", [1295]),
            _pcode_ln('Push "prototype"', [1295]),
            _pcode_ln("loc78j2: GetMember", [1296]),
            _pcode_ln("StoreRegister 2", [1297]),
            _pcode_ln("Pop", [1298]),
            _pcode_ln("Push register5", [1299]),
            _pcode_ln("Push 1", [1299]),
            _pcode_ln("Push 2", [1299]),
            _pcode_ln("Add2", [1300]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((7, 11), normalized_block)
    assert raw_span == (1299, 1301)


def test_convert_span_from_normalized_pcode_to_raw_mid_expanded_push():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("Push register2", [70]),
            _pcode_ln('Push "m_SelectedCategory"', [70]),
            _pcode_ln("Push 0", [70]),
            _pcode_ln("SetMember", [71]),
            _pcode_ln("Push register2", [72]),
            _pcode_ln('Push "GetMoneyForString"', [72]),
            _pcode_ln('DefineFunction "", 0 {', [73]),
            _pcode_ln("loc4vs5: Push 0.1", [74]),
            _pcode_ln("Push 0.0", [74]),  # <- span start
            _pcode_ln("Push register1", [74]),  # <- span end
            _pcode_ln('Push "GetMoney"', [74]),
            _pcode_ln("CallMethod", [75]),
            _pcode_ln("Push 1", [76]),
            _pcode_ln('Push "Math"', [76]),
            _pcode_ln("GetVariable", [77]),
            _pcode_ln('Push "round"', [78]),
            _pcode_ln("CallMethod", [79]),
            _pcode_ln("Multiply", [80]),
            _pcode_ln("Return", [81]),
            _pcode_ln("}", [82]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((8, 9), normalized_block)
    assert raw_span == (74, 75)


def test_convert_span_from_normalized_pcode_to_raw_span_ending_mid_expanded_push():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("Push register2", [72]),
            _pcode_ln('Push "GetMoneyForString"', [72]),
            _pcode_ln('DefineFunction "", 0 {', [73]),
            _pcode_ln("loc4vs5: Push 0.1", [74]),  # <- span start
            _pcode_ln("StoreRegister 6", [75]),
            _pcode_ln("Push register1", [76]),
            _pcode_ln('Push "GetMoney"', [76]),
            _pcode_ln("Push 1", [76]),  # <- span end
            _pcode_ln('Push "Math"', [76]),
            _pcode_ln("GetVariable", [77]),
            _pcode_ln('Push "round"', [78]),
            _pcode_ln("CallMethod", [79]),
            _pcode_ln("Multiply", [80]),
            _pcode_ln("Return", [81]),
            _pcode_ln("}", [82]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((3, 7), normalized_block)

    assert raw_span == (74, 77)


def test_convert_span_from_normalized_pcode_to_raw_non_contiguous_source_lines():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("StoreRegister 1", [411]),
            _pcode_ln("SetMember", [412]),
            _pcode_ln("Push register1", [413]),
            _pcode_ln('Push "prototype"', [413]),
            _pcode_ln("loc78j2: GetMember", [414]),
            _pcode_ln("StoreRegister 2", [415]),
            # Imagine there were two extra "Not" lines here before normalization.
            _pcode_ln("If loc0632", [418]),
            _pcode_ln("Pop", [419]),
            _pcode_ln("Push register6", [420]),
            _pcode_ln("StoreRegister 7", [421]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((5, 6), normalized_block)
    assert raw_span == (415, 416)


def test_convert_span_from_normalized_pcode_to_raw_non_contiguous_source_lines_bridge():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("StoreRegister 1", [411]),
            _pcode_ln("SetMember", [412]),
            _pcode_ln("Push register1", [413]),
            _pcode_ln('Push "prototype"', [413]),
            _pcode_ln("loc78j2: GetMember", [414]),
            _pcode_ln("StoreRegister 2", [415]),
            # Imagine there were two extra "Not" lines here before normalization.
            _pcode_ln("If loc0632", [418]),
            _pcode_ln("Pop", [419]),
            _pcode_ln("Push register6", [420]),
            _pcode_ln("StoreRegister 7", [421]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((5, 7), normalized_block)
    assert raw_span == (415, 419)


def test_convert_span_from_normalized_pcode_to_raw_span_starting_on_collapsed_lines():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("Push register9", [36]),
            _pcode_ln('Push "RemoveSlot"', [36]),
            _pcode_ln("CallMethod", [37]),
            _pcode_ln("Pop", [38]),
            _pcode_ln("L10:Push register4", [39]),
            _pcode_ln("Increment", [40, 41]),  # <- span start
            _pcode_ln("StoreRegister 4", [42]),  # <- span end
            _pcode_ln("Pop", [43]),
            _pcode_ln("Jump L8", [44]),
            _pcode_ln("L7:Push register2", [45]),
            _pcode_ln("Return", [46]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((5, 6), normalized_block)
    assert raw_span == (40, 42)


def test_convert_span_from_normalized_pcode_to_raw_span_ending_on_collapsed_lines():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("Push register9", [36]),
            _pcode_ln('Push "RemoveSlot"', [36]),
            _pcode_ln("CallMethod", [37]),
            _pcode_ln("Pop", [38]),
            _pcode_ln("L10:Push register4", [39]),  # <- span start
            _pcode_ln("Increment", [40, 41]),
            _pcode_ln("StoreRegister 4", [43]),  # <- span end (exclusive)
            _pcode_ln("Pop", [44]),
            _pcode_ln("Jump L8", [45]),
            _pcode_ln("L7:Push register2", [46]),
            _pcode_ln("Return", [47]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((4, 6), normalized_block)
    assert raw_span == (39, 42)


def test_convert_span_from_normalized_pcode_to_raw_end_span_ending_on_collapsed_lines():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("Push register9", [36]),
            _pcode_ln('Push "RemoveSlot"', [36]),
            _pcode_ln("CallMethod", [37]),
            _pcode_ln("Pop", [38]),
            _pcode_ln("L10:Push register4", [39]),
            _pcode_ln('Push "FSCommand:OnSound"', [39, 40, 41]),  # <- span start
            # ---- span end ----
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((5, 6), normalized_block)
    assert raw_span == (39, 42)


def test_convert_span_from_normalized_pcode_to_raw_end_anchor_span_ending_on_collapsed_lines():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("Push register9", [36]),
            _pcode_ln('Push "RemoveSlot"', [36]),
            _pcode_ln("CallMethod", [37]),
            _pcode_ln("Pop", [38]),
            _pcode_ln("L10:Push register4", [39]),
            _pcode_ln('Push "FSCommand:OnSound"', [39, 40, 41]),
            # ---- anchor span ----
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((6, 6), normalized_block)
    assert raw_span == (42, 42)


def test_convert_span_from_normalized_pcode_to_raw_anchor_span_on_collapsed_lines():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln('Push "onEnterFrame"', [37]),
            _pcode_ln("Delete", [38]),
            _pcode_ln("Pop", [39]),
            _pcode_ln('Push "FSCommand:OnFastTravelPath"', [40, 41, 42]),  # <- anchor span
            _pcode_ln('Push "REMOVE_BUFF"', [43]),
            _pcode_ln("GetVariable", [44]),
            _pcode_ln("GetURL2 false, false, 1", [45]),
            _pcode_ln("Jump L8", [46]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((3, 3), normalized_block)
    assert raw_span == (40, 40)


def test_convert_span_from_normalized_pcode_to_raw_full_span():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("StoreRegister 1", [912]),
            _pcode_ln("SetMember", [913]),
            _pcode_ln("Push register1", [914]),
            _pcode_ln('Push "prototype"', [914]),
            _pcode_ln("loc78j2: GetMember", [915]),
            _pcode_ln("StoreRegister 2", [916]),
            _pcode_ln("Pop", [917]),
            _pcode_ln("Push register5", [918]),
            _pcode_ln("Push 1", [918]),
            _pcode_ln("Push 2", [918]),
            _pcode_ln("Add2", [919]),
        ]
    )

    raw_span = _convert_span_from_normalized_pcode_to_raw((0, 11), normalized_block)
    assert raw_span == (912, 920)


def test_convert_span_from_normalized_pcode_to_raw_empty_block_raises_error():
    normalized_block = PcodeBlock(lines=[])

    with pytest.raises(ValueError, match="P-code block must not be empty."):
        _convert_span_from_normalized_pcode_to_raw((0, 0), normalized_block)


def test_convert_span_from_normalized_pcode_to_raw_invalid_diff_span_raises_error():
    normalized_block = PcodeBlock(
        lines=[
            _pcode_ln("Push 1", [20]),
            _pcode_ln("Push 2", [20]),
            _pcode_ln("Push 3", [20]),
        ]
    )

    with pytest.raises(ValueError, match="Provided line span is invalid"):
        _convert_span_from_normalized_pcode_to_raw((-1, 0), normalized_block)

    with pytest.raises(ValueError, match="Provided line span is invalid"):
        _convert_span_from_normalized_pcode_to_raw((2, 1), normalized_block)

    with pytest.raises(ValueError, match="Provided line span is invalid"):
        _convert_span_from_normalized_pcode_to_raw((1, 4), normalized_block)


def test_convert_span_from_pcode_to_actionscript_start_anchor_span():
    srcmap: dict[int, int | None] = {
        135: 60,
        136: 61,
        137: 61,
        138: 61,
        139: 61,
        140: 62,
        141: 63,
        142: 63,
    }

    as_span = _convert_span_from_pcode_to_actionscript((135, 135), srcmap)
    assert as_span == (60, 60)


def test_convert_span_from_pcode_to_actionscript_end_anchor_span():
    srcmap: dict[int, int | None] = {
        135: 60,
        136: 60,
        137: 60,
        138: 61,
        139: 61,
        140: 62,
        141: 63,
        142: 63,
    }

    as_span = _convert_span_from_pcode_to_actionscript((143, 143), srcmap)
    assert as_span == (64, 64)


def test_convert_span_from_pcode_to_actionscript_start_span():
    srcmap: dict[int, int | None] = {
        135: 60,
        136: 60,
        137: 60,
        138: 61,
        139: 61,
        140: 62,
        141: 63,
        142: 63,
    }

    as_span = _convert_span_from_pcode_to_actionscript((135, 139), srcmap)
    assert as_span == (60, 62)


def test_convert_span_from_pcode_to_actionscript_end_span():
    srcmap: dict[int, int | None] = {
        135: 60,
        136: 60,
        137: 60,
        138: 61,
        139: 61,
        140: 62,
        141: 63,
        142: 63,
    }

    as_span = _convert_span_from_pcode_to_actionscript((140, 143), srcmap)
    assert as_span == (62, 64)


def test_convert_span_from_pcode_to_actionscript_middle_anchor_span_unmapped():
    srcmap: dict[int, int | None] = {
        705: None,
        706: None,
        707: None,
        708: 177,
        709: 177,
        710: 178,
        711: 179,
        712: 179,
    }

    as_span = _convert_span_from_pcode_to_actionscript((707, 707), srcmap)
    assert as_span == (177, 177)
    # Anchor 707 is unmapped => lookup forwards because it is a zero-width span, find {708: 177}.


def test_convert_span_from_pcode_to_actionscript_end_anchor_span_unmapped():
    srcmap: dict[int, int | None] = {
        77: None,
        78: None,
        79: 50,
        80: 51,
        81: 52,
        82: 52,
        83: None,
    }

    as_span = _convert_span_from_pcode_to_actionscript((84, 84), srcmap)
    assert as_span == (53, 53)
    # Anchor 84 is unmapped => lookup backwards because it is a zero-width span but we are
    # at the very end already, find {82: 52} => +1.


def test_convert_span_from_pcode_to_actionscript_span_start_unmapped():
    srcmap: dict[int, int | None] = {
        0: None,
        1: None,
        2: 100,
        3: 101,
        4: None,
        5: 103,
        6: 103,
        7: 104,
        8: None,
    }

    as_span = _convert_span_from_pcode_to_actionscript((4, 7), srcmap)
    assert as_span == (101, 104)
    # Start bound 4 is unmapped => lookup outwards, find {3: 101}.


def test_convert_span_from_pcode_to_actionscript_span_end_unmapped():
    srcmap: dict[int, int | None] = {
        1712: None,
        1713: None,
        1714: 211,
        1715: 212,
        1716: 213,
        1717: 214,
        1718: None,
        1719: 215,
        1720: None,
    }

    as_span = _convert_span_from_pcode_to_actionscript((1716, 1719), srcmap)
    assert as_span == (213, 216)
    # Inclusive end bound 1719-1 is unmapped => lookup outwards, find {1719: 215} => +1.


def test_convert_span_from_pcode_to_actionscript_anchor_span_non_contiguous_pcode_lines():
    srcmap: dict[int, int | None] = {
        705: None,
        706: None,
        708: 177,
        709: 177,
        710: 178,
        711: 179,
        713: 179,
        714: 180,
        716: 180,
    }

    as_span = _convert_span_from_pcode_to_actionscript((712, 712), srcmap)
    assert as_span == (179, 179)
    # Anchor 712 is unmapped => lookup forwards because it is a zero-width span, find {713: 179}.


def test_convert_span_from_pcode_to_actionscript_span_non_contiguous_pcode_lines():
    srcmap: dict[int, int | None] = {
        693: 177,
        694: 177,
        696: 178,
        697: 178,
        700: 179,
        701: 180,
        702: 181,
        703: 181,
        705: 182,
    }

    as_span = _convert_span_from_pcode_to_actionscript((695, 700), srcmap)
    assert as_span == (177, 180)
    # Start bound 695 is unmapped => lookup outwards, find {694: 177}.
    # Inclusive end bound 700-1 is unmapped => lookup outwards, find {700: 179} => +1.


def test_convert_span_from_pcode_to_actionscript_anchor_span_non_contiguous_actionscript_lines():
    srcmap: dict[int, int | None] = {
        705: None,
        706: None,
        707: 175,  # <- gap
        708: 177,  # <- gap
        709: 177,
        710: 178,
        711: 179,
        712: 179,
        713: 180,
    }

    as_span = _convert_span_from_pcode_to_actionscript((708, 708), srcmap)
    assert as_span == (177, 177)
    # Gaps in ActionScript source lines do not affect anything.


def test_convert_span_from_pcode_to_actionscript_span_non_contiguous_actionscript_lines():
    srcmap: dict[int, int | None] = {
        707: 176,
        708: 177,
        709: 177,
        710: 178,
        711: 179,
        712: 179,
        713: 180,  # <- gap
        714: 182,  # <- gap
        715: 183,
    }

    as_span = _convert_span_from_pcode_to_actionscript((711, 714), srcmap)
    assert as_span == (179, 181)
    # Gaps in ActionScript source lines do not affect anything.


def test_convert_span_from_pcode_to_actionscript_span_end_past_last_mapped_line():
    srcmap: dict[int, int | None] = {
        135: 60,
        136: 61,
        137: 61,
        138: 61,
        139: 61,
        140: 62,
        141: 63,
        142: 64,
    }

    as_span = _convert_span_from_pcode_to_actionscript((141, 146), srcmap)
    assert as_span == (63, 65)
    # Inclusive end bound 146-1 is unmapped => lookup outwards and find nothing
    # => lookup inwards, find {142: 64} => +1.


def test_convert_span_from_pcode_to_actionscript_span_with_jump():
    # Realistic sparse mapping for a small function block. {290: 84} is the function-definition
    # header in p-code, pointing to the function's closing brace in ActionScript.
    srcmap: dict[int, int | None] = {
        287: None,
        289: None,
        290: 84,
        291: 79,
        292: None,
        293: None,
        294: None,
        295: 81,
        296: None,
        297: None,
        298: 82,
        299: None,
        300: None,
    }

    # The function should detect the boundary inversion before returning and
    # fall back to the union of all mapped AS lines within the span instead.
    as_span = _convert_span_from_pcode_to_actionscript((287, 301), srcmap)
    assert as_span == (79, 85)


def test_convert_span_from_pcode_to_actionscript_span_entirely_on_jump():
    # Same context as above.
    srcmap: dict[int, int | None] = {
        287: None,
        289: None,
        290: 84,
        291: 79,
        292: None,
        293: None,
        294: None,
        295: 81,
        296: None,
        297: None,
        298: 82,
        299: None,
        300: None,
    }

    # When the requested span sits entirely on p-code lines that jump forward in AS (e.g. a
    # diff confined to loop condition p-code lines), there is no boundary inversion, and the
    # span must be considered correct as-is.
    as_span = _convert_span_from_pcode_to_actionscript((290, 291), srcmap)
    assert as_span == (84, 85)


def test_convert_span_from_pcode_to_actionscript_empty_source_maps():
    assert _convert_span_from_pcode_to_actionscript((0, 1), {}) is None

    assert _convert_span_from_pcode_to_actionscript((0, 1), {825: None, 826: None, 830: None}) is None


def test_merge_overlapping_span_pairs():
    spans = _merge_overlapping_span_pairs(
        [
            RenderDiffSpanPair(a=(8088, 8091), b=(8106, 8109)),
            RenderDiffSpanPair(a=(8092, 8096), b=(8110, 8114)),
            RenderDiffSpanPair(a=(8094, 8102), b=(8112, 8120)),
        ]
    )

    assert spans == [
        RenderDiffSpanPair(a=(8088, 8091), b=(8106, 8109)),
        RenderDiffSpanPair(a=(8092, 8102), b=(8110, 8120)),
    ]


def test_merge_overlapping_span_pairs_does_not_merge_if_not_both_sides_are_adjacent():
    spans = _merge_overlapping_span_pairs(
        [RenderDiffSpanPair(a=(128, 140), b=(130, 138)), RenderDiffSpanPair(a=(140, 150), b=(140, 151))]
    )

    assert spans == [RenderDiffSpanPair(a=(128, 140), b=(130, 138)), RenderDiffSpanPair(a=(140, 150), b=(140, 151))]


def test_merge_overlapping_span_pairs_merges_transitively():
    spans = _merge_overlapping_span_pairs(
        [
            RenderDiffSpanPair(a=(1312, 1337), b=(1310, 1337)),
            RenderDiffSpanPair(a=(1337, 1341), b=(1336, 1340)),
            RenderDiffSpanPair(a=(1340, 1402), b=(1340, 1406)),
        ]
    )

    assert spans == [
        RenderDiffSpanPair(a=(1312, 1402), b=(1310, 1406)),
    ]


def test_merge_overlapping_span_pairs_does_nothing_with_empty_list():
    assert _merge_overlapping_span_pairs([]) == []


def test_merge_overlapping_span_pairs_does_nothing_with_one_pair():
    spans = _merge_overlapping_span_pairs([RenderDiffSpanPair(a=(2281, 2298), b=(2003, 2023))])

    assert spans == [RenderDiffSpanPair(a=(2281, 2298), b=(2003, 2023))]


def test_merge_overlapping_hunk_pairs():
    hunk_pairs = [
        (
            None,
            TextHunk(
                [
                    _hunk_ln(0, 'ConstantPool "_global", "StashManager", "BoundVariantA", "BoundVariantB"'),
                    _hunk_ctx(1, 'Push "_global"'),
                    _hunk_ctx(2, "GetVariable"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ctx(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ctx(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(35, 'Push register2, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(35, 'Push register3, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc483n: Push 0.1, 0.0, register1, "ObtenirArgent"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1.0, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(40, "GetVariable"),
                    _hunk_ctx(41, 'Push "round"'),
                    _hunk_ctx(42, ""),
                    _hunk_ctx(43, "SetMember"),
                    _hunk_ln(44, 'Push register2, "GetMoney"'),
                    _hunk_ln(45, 'loc1312: DefineFunction2 "", 0 {'),
                    _hunk_ctx(46, "Push 0.0"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(40, "GetVariable"),
                    _hunk_ctx(41, 'Push "round"'),
                    _hunk_ctx(42, ""),
                    _hunk_ctx(43, "SetMember"),
                    _hunk_ln(44, 'Push register9, "ObtenirArgent"'),
                    _hunk_ln(45, 'loc0202: DefineFunction2 "", 0 {'),
                    _hunk_ctx(46, "Push 0.0"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(45, 'loc1312: DefineFunction2 "", 0 {'),
                    _hunk_ctx(46, "Push 0.0"),
                    _hunk_ln(47, "loc78f:"),
                    _hunk_ctx(48, "Push -1"),
                    _hunk_ctx(49, "Add2"),
                    _hunk_ln(50, "Push -1.3"),
                    _hunk_ctx(51, "Subtract"),
                    _hunk_ln(52, "Push register2"),
                    _hunk_ctx(53, 'Push "E_IS_Weight"'),
                    _hunk_ctx(54, "Push 2"),
                    _hunk_ctx(55, "SetMember"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(45, 'loc0202: DefineFunction2 "", 0 {'),
                    _hunk_ctx(46, "Push 0.0"),
                    _hunk_ctx(47, "Push -1"),
                    _hunk_ctx(48, "Add2"),
                    _hunk_ln(49, "Push -1.4"),
                    _hunk_ctx(50, "Subtract"),
                    _hunk_ln(51, "Push register9"),
                    _hunk_ctx(52, 'Push "E_IS_Weight"'),
                    _hunk_ctx(53, "Push 2"),
                    _hunk_ctx(54, "SetMember"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(57, 'Push "Array"'),
                    _hunk_ln(58, "NewObject"),
                    _hunk_ln(59, "StoreRegister 3"),
                    _hunk_ln(60, "Pop"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(57, "NewObject"),
                    _hunk_ln(58, "StoreRegister 3"),
                    _hunk_ln(59, "Pop"),
                    _hunk_ln(60, "Push 0"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(61, "Push register1"),
                    _hunk_ctx(62, 'Push "GetSlot"'),
                    _hunk_ctx(63, "CallMethod"),
                    _hunk_ln(64, "StoreRegister 8"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(62, 'Push "GetSlot"'),
                    _hunk_ctx(63, "CallMethod"),
                    _hunk_ln(64, "StoreRegister 9"),
                    _hunk_ctx(65, "Pop"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(124, "Push 0"),
                    _hunk_ctx(125, 'Push "init"'),
                    _hunk_ctx(126, "CallFunction"),
                    _hunk_ln(127, "Pop"),
                ]
            ),
            None,
        ),
    ]

    side_b_corpus = _fake_corpus_with_lines({61: "Push register1"})

    assert _merge_overlapping_hunk_pairs(hunk_pairs, [], side_b_corpus) == [
        (
            None,
            TextHunk(
                [
                    _hunk_ln(0, 'ConstantPool "_global", "StashManager", "BoundVariantA", "BoundVariantB"'),
                    _hunk_ctx(1, 'Push "_global"'),
                    _hunk_ctx(2, "GetVariable"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ctx(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ln(35, 'Push register2, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                    _hunk_ctx(41, 'Push "round"'),
                    _hunk_ctx(42, ""),
                    _hunk_ctx(43, "SetMember"),
                    _hunk_ln(44, 'Push register2, "GetMoney"'),
                    _hunk_ln(45, 'loc1312: DefineFunction2 "", 0 {'),
                    _hunk_ctx(46, "Push 0.0"),
                    _hunk_ln(47, "loc78f:"),
                    _hunk_ctx(48, "Push -1"),
                    _hunk_ctx(49, "Add2"),
                    _hunk_ln(50, "Push -1.3"),
                    _hunk_ctx(51, "Subtract"),
                    _hunk_ln(52, "Push register2"),
                    _hunk_ctx(53, 'Push "E_IS_Weight"'),
                    _hunk_ctx(54, "Push 2"),
                    _hunk_ctx(55, "SetMember"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ctx(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ln(35, 'Push register3, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc483n: Push 0.1, 0.0, register1, "ObtenirArgent"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1.0, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                    _hunk_ctx(41, 'Push "round"'),
                    _hunk_ctx(42, ""),
                    _hunk_ctx(43, "SetMember"),
                    _hunk_ln(44, 'Push register9, "ObtenirArgent"'),
                    _hunk_ln(45, 'loc0202: DefineFunction2 "", 0 {'),
                    _hunk_ctx(46, "Push 0.0"),
                    _hunk_ctx(47, "Push -1"),
                    _hunk_ctx(48, "Add2"),
                    _hunk_ln(49, "Push -1.4"),
                    _hunk_ctx(50, "Subtract"),
                    _hunk_ln(51, "Push register9"),
                    _hunk_ctx(52, 'Push "E_IS_Weight"'),
                    _hunk_ctx(53, "Push 2"),
                    _hunk_ctx(54, "SetMember"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(57, 'Push "Array"'),
                    _hunk_ln(58, "NewObject"),
                    _hunk_ln(59, "StoreRegister 3"),
                    _hunk_ln(60, "Pop"),
                    _hunk_ctx(61, "Push register1"),
                    _hunk_ctx(62, 'Push "GetSlot"'),
                    _hunk_ctx(63, "CallMethod"),
                    _hunk_ln(64, "StoreRegister 8"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(57, "NewObject"),
                    _hunk_ln(58, "StoreRegister 3"),
                    _hunk_ln(59, "Pop"),
                    _hunk_ln(60, "Push 0"),
                    _hunk_ctx(61, "Push register1"),
                    _hunk_ln(62, 'Push "GetSlot"'),
                    _hunk_ctx(63, "CallMethod"),
                    _hunk_ln(64, "StoreRegister 9"),
                    _hunk_ctx(65, "Pop"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(124, "Push 0"),
                    _hunk_ctx(125, 'Push "init"'),
                    _hunk_ctx(126, "CallFunction"),
                    _hunk_ln(127, "Pop"),
                ]
            ),
            None,
        ),
    ]


def test_merge_overlapping_hunk_pairs_both_sides_adjacent():
    hunk_pairs = [
        (
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ctx(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ctx(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(35, 'Push register2, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(35, 'Push register3, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc483n: Push 0.1, 0.0, register1, "ObtenirArgent"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1.0, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
        ),
    ]

    assert _merge_overlapping_hunk_pairs(hunk_pairs, [], []) == [
        (
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ctx(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ln(35, 'Push register2, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ctx(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ln(35, 'Push register3, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc483n: Push 0.1, 0.0, register1, "ObtenirArgent"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1.0, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
        ),
    ]


def test_merge_overlapping_hunk_pairs_both_sides_overlapping():
    hunk_pairs = [
        (
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ln(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ctx(35, 'Push register2, "GetMoneyForString"'),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ln(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ctx(35, 'Push register3, "GetMoneyForString"'),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(35, 'Push register2, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(35, 'Push register3, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc483n: Push 0.1, 0.0, register1, "ObtenirArgent"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1.0, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
        ),
    ]

    assert _merge_overlapping_hunk_pairs(hunk_pairs, [], []) == [
        (
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ln(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ln(35, 'Push register2, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc4vs5: Push 0.1, 0.0, register1, "GetMoney"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ln(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ln(35, 'Push register3, "GetMoneyForString"'),
                    _hunk_ctx(36, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(37, 'loc483n: Push 0.1, 0.0, register1, "ObtenirArgent"'),
                    _hunk_ctx(38, "CallMethod"),
                    _hunk_ln(39, 'Push 1.0, "Math"'),
                    _hunk_ctx(40, "GetVariable"),
                ]
            ),
        ),
    ]


def test_merge_overlapping_hunk_pairs_both_sides_gap():
    hunk_pairs = [
        (
            TextHunk(
                [
                    _hunk_ln(57, 'Push "Array"'),
                    _hunk_ln(58, "NewObject"),
                    _hunk_ln(59, "StoreRegister 3"),
                    _hunk_ln(60, "Pop"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(57, "NewObject"),
                    _hunk_ln(58, "StoreRegister 3"),
                    _hunk_ln(59, "Pop"),
                    _hunk_ln(60, "Push 0"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(124, "Push 0"),
                    _hunk_ln(125, 'Push "init"'),
                    _hunk_ctx(126, "CallFunction"),
                    _hunk_ln(127, "Pop"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(124, "Push 0"),
                    _hunk_ln(125, 'Push "_init_"'),
                    _hunk_ctx(126, "CallFunction"),
                    _hunk_ln(127, "Return"),
                ]
            ),
        ),
    ]

    assert _merge_overlapping_hunk_pairs(hunk_pairs, [], []) == [
        (
            TextHunk(
                [
                    _hunk_ln(57, 'Push "Array"'),
                    _hunk_ln(58, "NewObject"),
                    _hunk_ln(59, "StoreRegister 3"),
                    _hunk_ln(60, "Pop"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(57, "NewObject"),
                    _hunk_ln(58, "StoreRegister 3"),
                    _hunk_ln(59, "Pop"),
                    _hunk_ln(60, "Push 0"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(124, "Push 0"),
                    _hunk_ln(125, 'Push "init"'),
                    _hunk_ctx(126, "CallFunction"),
                    _hunk_ln(127, "Pop"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(124, "Push 0"),
                    _hunk_ln(125, 'Push "_init_"'),
                    _hunk_ctx(126, "CallFunction"),
                    _hunk_ln(127, "Return"),
                ]
            ),
        ),
    ]


def test_merge_overlapping_hunk_pairs_one_side_adjacent():
    hunk_pairs = [
        (
            TextHunk(
                [
                    _hunk_ctx(213, "SetMember"),
                    _hunk_ctx(214, "Push register2"),
                    _hunk_ln(215, 'Push "GetRemoveCount"'),
                    _hunk_ln(
                        216,
                        'DefineFunction2 "", 3, 12, false, false, true, false, true, false, false, true, false, 2, "index", 3, "count", 4, "remove" {',
                    ),
                    _hunk_ctx(
                        217,
                        'DefineFunction2 "computeTake", 2, 3, false, false, true, false, true, false, true, false, false, 1, "remaining", 2, "availableCount" {',
                    ),
                    _hunk_ctx(218, "Push register1"),
                    _hunk_ctx(219, "Push register2"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(213, "SetMember"),
                    _hunk_ln(214, "Push register2"),
                    _hunk_ln(215, 'Push "GetRemoveCount"'),
                    _hunk_ln(
                        216,
                        'DefineFunction2 "", 3, 12, false, false, true, false, true, false, false, true, false, 2, "index", 3, "count", 4, "remove" {',
                    ),
                    _hunk_ctx(
                        217,
                        'DefineFunction2 "computeTake", 2, 3, false, false, true, false, true, false, true, false, false, 1, "remaining", 2, "availableCount" {',
                    ),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(220, "Less2"),
                    _hunk_ctx(221, "Not"),
                    _hunk_ctx(222, "Not"),
                    _hunk_ln(223, "If loc0631"),
                    _hunk_ctx(224, "Push register2"),
                    _hunk_ln(225, "Jump loc0636"),
                    _hunk_ln(226, "loc0631:Push register1"),
                    _hunk_ln(227, "loc0636:Return"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(220, "Less2"),
                    _hunk_ctx(221, "Not"),
                    _hunk_ctx(222, "Not"),
                    _hunk_ln(223, "If loc0631"),
                    _hunk_ctx(224, "Push register2"),
                    _hunk_ln(225, "Jump loc0636"),
                    _hunk_ln(226, "loc0631:Push register1"),
                    _hunk_ln(227, "loc0636:Return"),
                ]
            ),
        ),
    ]

    side_b_pcode = _fake_corpus_with_lines({218: "Push register1", 219: "Push register2"})

    assert _merge_overlapping_hunk_pairs(hunk_pairs, [], side_b_pcode) == [
        (
            TextHunk(
                [
                    _hunk_ctx(213, "SetMember"),
                    _hunk_ctx(214, "Push register2"),
                    _hunk_ln(215, 'Push "GetRemoveCount"'),
                    _hunk_ln(
                        216,
                        'DefineFunction2 "", 3, 12, false, false, true, false, true, false, false, true, false, 2, "index", 3, "count", 4, "remove" {',
                    ),
                    _hunk_ctx(
                        217,
                        'DefineFunction2 "computeTake", 2, 3, false, false, true, false, true, false, true, false, false, 1, "remaining", 2, "availableCount" {',
                    ),
                    _hunk_ctx(218, "Push register1"),
                    _hunk_ctx(219, "Push register2"),
                    _hunk_ctx(220, "Less2"),
                    _hunk_ctx(221, "Not"),
                    _hunk_ctx(222, "Not"),
                    _hunk_ln(223, "If loc0631"),
                    _hunk_ctx(224, "Push register2"),
                    _hunk_ln(225, "Jump loc0636"),
                    _hunk_ln(226, "loc0631:Push register1"),
                    _hunk_ln(227, "loc0636:Return"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(213, "SetMember"),
                    _hunk_ln(214, "Push register2"),
                    _hunk_ln(215, 'Push "GetRemoveCount"'),
                    _hunk_ln(
                        216,
                        'DefineFunction2 "", 3, 12, false, false, true, false, true, false, false, true, false, 2, "index", 3, "count", 4, "remove" {',
                    ),
                    _hunk_ctx(
                        217,
                        'DefineFunction2 "computeTake", 2, 3, false, false, true, false, true, false, true, false, false, 1, "remaining", 2, "availableCount" {',
                    ),
                    _hunk_ctx(218, "Push register1"),
                    _hunk_ctx(219, "Push register2"),
                    _hunk_ctx(220, "Less2"),
                    _hunk_ctx(221, "Not"),
                    _hunk_ctx(222, "Not"),
                    _hunk_ln(223, "If loc0631"),
                    _hunk_ctx(224, "Push register2"),
                    _hunk_ln(225, "Jump loc0636"),
                    _hunk_ln(226, "loc0631:Push register1"),
                    _hunk_ln(227, "loc0636:Return"),
                ]
            ),
        ),
    ]


def test_merge_overlapping_hunk_pairs_one_side_overlapping():
    hunk_pairs = [
        (
            TextHunk(
                [
                    _hunk_ctx(527, 'Push "RemoveMoneySlot"'),
                    _hunk_ctx(528, "CallMethod"),
                    _hunk_ctx(529, "Pop"),
                    _hunk_ln(530, "loc0aa5:Push true"),
                    _hunk_ln(531, "Return"),
                    _hunk_ln(532, "loc0aab:Push false"),
                    _hunk_ctx(533, "Return"),
                    _hunk_ctx(534, "}"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(530, 'Push "RemoveMoneySlot"'),
                    _hunk_ctx(531, "CallMethod"),
                    _hunk_ctx(532, "Pop"),
                    _hunk_ctx(533, "loc0aaf:Push true"),
                    _hunk_ctx(534, "Return"),
                    _hunk_ctx(535, "loc0ab5:Push false"),
                    _hunk_ctx(536, "Return"),
                    _hunk_ctx(537, "}"),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(537, 'Push "DecrementProbe"'),
                    _hunk_ln(
                        538,
                        'DefineFunction2 "", 1, 4, false, false, true, false, true, false, true, false, false, 1, "value" {',
                    ),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(536, "Return"),
                    _hunk_ctx(537, "}"),
                    _hunk_ctx(538, "SetMember"),
                    _hunk_ln(539, "Push register2"),
                    _hunk_ln(540, 'Push "DecrementProbe"'),
                    _hunk_ctx(
                        541,
                        'DefineFunction2 "", 1, 4, false, false, true, false, true, false, true, false, false, 1, "value" {',
                    ),
                ]
            ),
        ),
    ]

    side_a_pcode = _fake_corpus_with_lines({535: "SetMember", 536: "Push register2"})

    assert _merge_overlapping_hunk_pairs(hunk_pairs, side_a_pcode, []) == [
        (
            TextHunk(
                [
                    _hunk_ctx(527, 'Push "RemoveMoneySlot"'),
                    _hunk_ctx(528, "CallMethod"),
                    _hunk_ctx(529, "Pop"),
                    _hunk_ln(530, "loc0aa5:Push true"),
                    _hunk_ln(531, "Return"),
                    _hunk_ln(532, "loc0aab:Push false"),
                    _hunk_ctx(533, "Return"),
                    _hunk_ctx(534, "}"),
                    _hunk_ctx(535, "SetMember"),
                    _hunk_ctx(536, "Push register2"),
                    _hunk_ln(537, 'Push "DecrementProbe"'),
                    _hunk_ln(
                        538,
                        'DefineFunction2 "", 1, 4, false, false, true, false, true, false, true, false, false, 1, "value" {',
                    ),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(530, 'Push "RemoveMoneySlot"'),
                    _hunk_ctx(531, "CallMethod"),
                    _hunk_ctx(532, "Pop"),
                    _hunk_ctx(533, "loc0aaf:Push true"),
                    _hunk_ctx(534, "Return"),
                    _hunk_ctx(535, "loc0ab5:Push false"),
                    _hunk_ctx(536, "Return"),
                    _hunk_ctx(537, "}"),
                    _hunk_ctx(538, "SetMember"),
                    _hunk_ln(539, "Push register2"),
                    _hunk_ln(540, 'Push "DecrementProbe"'),
                    _hunk_ctx(
                        541,
                        'DefineFunction2 "", 1, 4, false, false, true, false, true, false, true, false, false, 1, "value" {',
                    ),
                ]
            ),
        ),
    ]


def test_merge_overlapping_hunk_pairs_singletons_pass_through():
    hunk_pairs = [
        (
            None,
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ln(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ctx(35, 'Push register3, "GetMoneyForString"'),
                ]
            ),
        ),
    ]

    assert _merge_overlapping_hunk_pairs(hunk_pairs, [], []) == [
        (
            None,
            TextHunk(
                [
                    _hunk_ln(30, 'Push register1, "m_DisplayedData", 0.0, "Array"'),
                    _hunk_ctx(31, "NewObject"),
                    _hunk_ln(32, "SetMember"),
                    _hunk_ctx(33, "}"),
                    _hunk_ctx(34, "SetMember"),
                    _hunk_ctx(35, 'Push register3, "GetMoneyForString"'),
                ]
            ),
        ),
    ]


def test_merge_overlapping_hunk_pairs_empty():
    assert _merge_overlapping_hunk_pairs([], [], []) == []


def test_merge_overlapping_hunk_pairs_does_nothing_with_one_pair():
    pair = (
        TextHunk(
            [
                _hunk_ln(10, 'Push register1, "GetMoney"'),
                _hunk_ctx(11, "CallMethod"),
                _hunk_ln(12, 'Push 1, "Math"'),
            ]
        ),
        TextHunk(
            [
                _hunk_ln(10, 'Push register3, "ObtenirArgent"'),
                _hunk_ctx(11, "CallMethod"),
                _hunk_ln(12, 'Push 1.0, "Math"'),
            ]
        ),
    )

    assert _merge_overlapping_hunk_pairs([pair], [], []) == [pair]


def test_merge_overlapping_hunk_pairs_handles_unsorted_input_without_crashing():
    hunk_pairs = [
        (
            TextHunk(
                [
                    _hunk_ln(14, 'Push register2, "GetMoney"'),
                    _hunk_ctx(15, "CallMethod"),
                    _hunk_ln(16, 'Push 1, "Math"'),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(14, 'Push register9, "ObtenirArgent"'),
                    _hunk_ctx(15, "CallMethod"),
                    _hunk_ln(16, 'Push 1.0, "Math"'),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(10, "NewObject"),
                    _hunk_ctx(11, "SetMember"),
                    _hunk_ln(12, 'Push register1, "Array"'),
                    _hunk_ctx(13, 'DefineFunction2 "", 0 {'),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(10, "NewObject"),
                    _hunk_ctx(11, "SetMember"),
                    _hunk_ln(12, 'Push register1, "Tableau"'),
                    _hunk_ctx(13, 'DefineFunction2 "", 0 {'),
                ]
            ),
        ),
        (
            # This pair is unrealistic but it exercises an edge case that could crash
            # the function if not handled properly.
            TextHunk(
                [
                    _hunk_ctx(5, "Push 0"),
                    _hunk_ln(6, 'Push "m_MapLegend"'),
                    _hunk_ctx(7, "GetVariable"),
                    _hunk_ctx(8, 'Push "GetTrackingAsociativArray"'),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(14, 'Push register9, "ObtenirArgent"'),
                    _hunk_ctx(15, "CallMethod"),
                    _hunk_ln(16, 'Push 1.0, "Math"'),
                ]
            ),
        ),
        (
            # Mirror edge case.
            TextHunk(
                [
                    _hunk_ctx(9, "CallMethod"),
                    _hunk_ln(10, "NewObject"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(10, "NewObject"),
                    _hunk_ctx(11, "SetMember"),
                ]
            ),
        ),
    ]

    assert _merge_overlapping_hunk_pairs(hunk_pairs, [], []) == [
        (
            TextHunk(
                [
                    _hunk_ctx(10, "NewObject"),
                    _hunk_ctx(11, "SetMember"),
                    _hunk_ln(12, 'Push register1, "Array"'),
                    _hunk_ctx(13, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(14, 'Push register2, "GetMoney"'),
                    _hunk_ctx(15, "CallMethod"),
                    _hunk_ln(16, 'Push 1, "Math"'),
                ]
            ),
            TextHunk(
                [
                    _hunk_ctx(10, "NewObject"),
                    _hunk_ctx(11, "SetMember"),
                    _hunk_ln(12, 'Push register1, "Tableau"'),
                    _hunk_ctx(13, 'DefineFunction2 "", 0 {'),
                    _hunk_ln(14, 'Push register9, "ObtenirArgent"'),
                    _hunk_ctx(15, "CallMethod"),
                    _hunk_ln(16, 'Push 1.0, "Math"'),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(5, "Push 0"),
                    _hunk_ln(6, 'Push "m_MapLegend"'),
                    _hunk_ctx(7, "GetVariable"),
                    _hunk_ctx(8, 'Push "GetTrackingAsociativArray"'),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(14, 'Push register9, "ObtenirArgent"'),
                    _hunk_ctx(15, "CallMethod"),
                    _hunk_ln(16, 'Push 1.0, "Math"'),
                ]
            ),
        ),
        (
            TextHunk(
                [
                    _hunk_ctx(9, "CallMethod"),
                    _hunk_ln(10, "NewObject"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(10, "NewObject"),
                    _hunk_ctx(11, "SetMember"),
                ]
            ),
        ),
    ]


def test_merge_overlapping_hunk_pairs_handles_empty_hunks_without_crashing():
    hunk_pairs = [
        (
            TextHunk(
                [
                    _hunk_ln(14, 'Push register2, "GetMoney"'),
                    _hunk_ctx(15, "CallMethod"),
                    _hunk_ln(16, 'Push 1, "Math"'),
                ]
            ),
            TextHunk(),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(55, "Push 0"),
                    _hunk_ln(56, 'Push "Array"'),
                    _hunk_ln(57, "NewObject"),
                    _hunk_ln(58, "StoreRegister 3"),
                    _hunk_ln(59, "Pop"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(57, "NewObject"),
                    _hunk_ln(58, "StoreRegister 3"),
                    _hunk_ln(59, "Pop"),
                    _hunk_ln(60, "Push 0"),
                ]
            ),
        ),
    ]

    assert _merge_overlapping_hunk_pairs(hunk_pairs, [], []) == [
        (
            TextHunk(
                [
                    _hunk_ln(14, 'Push register2, "GetMoney"'),
                    _hunk_ctx(15, "CallMethod"),
                    _hunk_ln(16, 'Push 1, "Math"'),
                ]
            ),
            TextHunk(),
        ),
        (
            TextHunk(
                [
                    _hunk_ln(55, "Push 0"),
                    _hunk_ln(56, 'Push "Array"'),
                    _hunk_ln(57, "NewObject"),
                    _hunk_ln(58, "StoreRegister 3"),
                    _hunk_ln(59, "Pop"),
                ]
            ),
            TextHunk(
                [
                    _hunk_ln(57, "NewObject"),
                    _hunk_ln(58, "StoreRegister 3"),
                    _hunk_ln(59, "Pop"),
                    _hunk_ln(60, "Push 0"),
                ]
            ),
        ),
    ]
