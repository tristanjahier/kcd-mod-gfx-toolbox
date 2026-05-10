"""
Data preparation and Rich component builders for rendering a GfxDiffSet: sorting/filtering, resolving ActionScript
source, slicing differing blocks into hunks, and assembling renderable split or unified layouts.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal
from rich.markup import escape
from pygments.lexer import Lexer
from pygments.lexers import ActionScriptLexer

from kcd_gfx_toolbox.avm1.pcode_alignment import align_labels_in_text, align_registers_in_text
from kcd_gfx_toolbox.avm1.pcode_parsing import PcodeBlock, merge_pcode_lines_sources
from kcd_gfx_toolbox.swd import (
    build_pcode_to_actionscript_line_map,
    parse_swd_file,
    propagate_mapped_lines_to_subsequent_unmapped_lines,
)
from kcd_gfx_toolbox.utils import read_file_lines
from kcd_gfx_toolbox.workspace import Workspace
from .core import (
    DiffAnnotatedHunk,
    TextHunk,
    align_hunk_pairs,
    cut_text_hunks_with_context,
    diff_text_hunks,
    diff_texts,
)
from .gfx import GfxDiffSet, GfxScript, GfxScriptBlock
from .split_layout import SplitLayout, SplitLayoutMessagePane
from .unified_layout import UnifiedLayout


class DiffSortOrder(StrEnum):
    NATURAL = "natural"
    CHANGES_DESC = "changes_desc"
    CHANGES_ASC = "changes_asc"


@dataclass(kw_only=True, frozen=True)
class DiffFilter:
    script: str | None = None
    block: str | None = None

    def __bool__(self) -> bool:
        return self.script is not None or self.block is not None


class DiffLayout(StrEnum):
    UNIFIED = "unified"
    SPLIT = "split"


@dataclass(frozen=True, slots=True)
class RenderDiffSpanPair:
    """
    Represent a pair of diff spans to render with two sides (A and B).
    Pairing is loose so that it can represent unmatched blocks spans.
    """

    a: tuple[int, int] | None
    b: tuple[int, int] | None

    def __post_init__(self):
        if self.a is None and self.b is None:
            raise ValueError(f"{self.__class__.__name__} must have at least one side defined.")

    def __iter__(self):
        yield self.a
        yield self.b

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(a={self.a}, b={self.b})"


def get_sorted_and_filtered_script_block_pairs(
    diffset: GfxDiffSet, sort_order: DiffSortOrder, filters: DiffFilter
) -> list[tuple[GfxScript, GfxScriptBlock]]:
    """
    List pairs of differing scripts and blocks, applying desired filters and sorting.
    """
    pairs: list[tuple[GfxScript, GfxScriptBlock]] = []
    scripts: list[GfxScript] = []

    for script in diffset.get_scripts_with_differing_blocks():
        if filters.script is None:
            scripts.append(script)
            continue

        if (script.side_a_path is not None and filters.script in script.side_a_path.as_posix().lower()) or (
            script.side_b_path is not None and filters.script in script.side_b_path.as_posix().lower()
        ):
            scripts.append(script)

    scripts.sort(key=lambda s: s.path_sort_key())

    for script in scripts:
        blocks = sorted(
            diffset.paired_scripts_block_diffs[script].get_differing_blocks(),
            key=lambda b: (b.position, b.name_sort_key()),
        )

        for block in blocks:
            if (
                filters.block is None
                or (block.side_a_name is not None and filters.block in block.side_a_name.lower())
                or (block.side_b_name is not None and filters.block in block.side_b_name.lower())
            ):
                pairs.append((script, block))

    if sort_order == DiffSortOrder.CHANGES_ASC:
        pairs.sort(key=lambda p: (p[1].refined_changed, p[0].path_sort_key(), p[1].name_sort_key()))
    elif sort_order == DiffSortOrder.CHANGES_DESC:
        pairs.sort(key=lambda p: (-p[1].refined_changed, p[0].path_sort_key(), p[1].name_sort_key()))

    return pairs


@dataclass(kw_only=True, frozen=True)
class RenderableBlockDiff:
    script: GfxScript
    block: GfxScriptBlock
    hunk_pairs: list[tuple[TextHunk, TextHunk]]
    prologue_messages: list[str] = field(default_factory=list)
    lang: Literal["actionscript", "pcode"]
    # The two following fields only make sense when targeting ActionScript.
    side_a_resolved: bool
    side_b_resolved: bool


def _find_pcode_block_by_name(blocks: Iterable, name: str | None) -> PcodeBlock | None:
    if name is None:
        return None
    try:
        return next(block for block in blocks if block.name == name)
    except StopIteration:
        raise LookupError(f"Block {name!r} not found in normalized blocks.")


def _pcode_block_render_data(
    block: GfxScriptBlock, block_side_a: PcodeBlock | None, block_side_b: PcodeBlock | None
) -> tuple[list[str], list[str], list[RenderDiffSpanPair]]:
    """
    For a given block, align side B's labels and registers to side A, compute the differences,
    then return plain-text block lines and diff spans for each side.
    """
    block_a_lines = [ln.render() for ln in block_side_a.lines] if block_side_a else []
    block_b_lines = [ln.render() for ln in block_side_b.lines] if block_side_b else []
    block_b_lines = align_labels_in_text(block_b_lines, anchor_lines=block_a_lines)
    block_b_lines = align_registers_in_text(block_b_lines, anchor_lines=block_a_lines)

    diff_spans: list[RenderDiffSpanPair] = []

    if block.is_paired():
        # Recompute diff spans on aligned lines: block.diff_spans was computed on normalized but
        # unaligned block content and would reference lines that, after label/register alignment,
        # no longer actually differ, producing spurious hunks of unchanged content.
        diff_spans = [RenderDiffSpanPair(a, b) for a, b in diff_texts(block_a_lines, block_b_lines).spans]
    else:
        # For unmatched blocks there are no diff spans, so we have no choice but to display the whole block.
        if block_side_a is not None:
            diff_spans.append(RenderDiffSpanPair(a=(0, len(block_side_a)), b=None))

        if block_side_b is not None:
            diff_spans.append(RenderDiffSpanPair(a=None, b=(0, len(block_side_b))))

    return block_a_lines, block_b_lines, diff_spans


def prepare_diffset_pcode_render(
    diffset: GfxDiffSet,
    normalized_script_blocks_a: dict[Path, list[PcodeBlock]],
    normalized_script_blocks_b: dict[Path, list[PcodeBlock]],
    sort_order: DiffSortOrder,
    filters: DiffFilter,
) -> list[RenderableBlockDiff]:
    """
    Build the renderable elements for a p-code diff.

    Sort and filter differing script blocks, then slice each block into context-padded p-code hunk pairs.
    """
    renderables: list[RenderableBlockDiff] = []
    sorted_pairs = get_sorted_and_filtered_script_block_pairs(diffset, sort_order, filters)

    if filters and not sorted_pairs:
        raise RuntimeError("No script or block name matches the provided filters.")

    for script, block in sorted_pairs:
        assert script.side_a_path is not None  # type guard for static analyzers
        assert script.side_b_path is not None

        script_a_blocks = normalized_script_blocks_a.get(script.side_a_path, [])
        script_b_blocks = normalized_script_blocks_b.get(script.side_b_path, [])
        block_side_a = _find_pcode_block_by_name(script_a_blocks, block.side_a_name)
        block_side_b = _find_pcode_block_by_name(script_b_blocks, block.side_b_name)

        block_a_lines, block_b_lines, diff_spans = _pcode_block_render_data(block, block_side_a, block_side_b)

        hunk_pairs = align_hunk_pairs(
            cut_text_hunks_with_context(
                block_a_lines, [ds.a for ds in diff_spans if ds.a is not None], context_length=5, merge=True
            ),
            cut_text_hunks_with_context(
                block_b_lines, [ds.b for ds in diff_spans if ds.b is not None], context_length=5, merge=True
            ),
        )

        renderables.append(
            RenderableBlockDiff(
                script=script,
                block=block,
                hunk_pairs=hunk_pairs,
                lang="pcode",
                side_a_resolved=True,
                side_b_resolved=True,
            )
        )

    return renderables


def _build_block_source_map(
    pcode_block: PcodeBlock | None, script_source_map: dict[int, int | None]
) -> dict[int, int | None]:
    """
    Build a denser source map for a p-code block from the SWD-extracted sparse source map.

    Gaps in ActionScript source lines coverage is "forward-filled".
    """
    if pcode_block is None:
        return {}

    block_first_line = min(pcode_block.lines[0].source_lines)
    block_last_line = max(pcode_block.lines[-1].source_lines)

    # Mapped lines in ActionScript are sparse. Simple naive improvement: propagate mapped
    # lines to subsequent unmapped lines, within the boundaries of the block.
    return propagate_mapped_lines_to_subsequent_unmapped_lines(
        {k: v for k, v in script_source_map.items() if block_first_line <= k <= block_last_line}
    )


def _convert_span_from_normalized_pcode_to_raw(span: tuple[int, int], pcode: PcodeBlock) -> tuple[int, int]:
    """
    Convert a normalized p-code span to a raw p-code relative span.

    When multiple raw lines were collapsed into a single one through normalization, it creates
    an ambiguous case and this function cannot resolve the exact original diff span.
    It will include the whole collapsed line source span.
    """
    if len(pcode) == 0:
        raise ValueError("P-code block must not be empty.")
    if span[0] > span[1] or span[0] < 0 or span[1] > len(pcode):
        raise ValueError(f"Provided line span is invalid: {span!r}")

    if span[0] == span[1]:  # zero-width span (= anchor for pure deletions/insertions)
        # A zero-width span at the very end of a block references a line index
        # that is out of bounds. However it is a valid span in a diff context.
        if span[0] == len(pcode):
            src_line = merge_pcode_lines_sources(pcode.lines[-1])[-1]
            return (src_line + 1, src_line + 1)

        src_line = merge_pcode_lines_sources(pcode.lines[span[0]])[0]
        return (src_line, src_line)

    src_lines = merge_pcode_lines_sources(*pcode.lines[span[0] : span[1]])
    return (src_lines[0], src_lines[-1] + 1)


def _convert_span_from_pcode_to_actionscript(
    span: tuple[int, int], source_map: dict[int, int | None], fallback_window: int = 10
) -> tuple[int, int] | None:
    """
    Convert a p-code span to an ActionScript relative span.

    The function expects the source map to have been forward-filled to work better.
    It returns None if the ActionScript line span could not be resolved.
    """

    def _backward_lookup(start_ln: int) -> int | None:
        ln = start_ln
        while ln > (start_ln - fallback_window) and ln >= 0:
            if (srcln := source_map.get(ln)) is not None:
                return srcln
            ln -= 1
        return None

    def _forward_lookup(start_ln: int) -> int | None:
        ln = start_ln
        while ln < (start_ln + fallback_window):
            if (srcln := source_map.get(ln)) is not None:
                return srcln
            ln += 1
        return None

    if not source_map or all(v is None for v in source_map.values()):
        return None

    # Zero-width span (= anchor for pure deletions/insertions)
    if span[0] == span[1]:
        if span[0] > (last_block_line := max(source_map.keys())):
            # The span anchor is at the very end of the block.
            end = source_map.get(last_block_line)

            if end is None:  # If unmapped, look for a mapped line backwards.
                end = _backward_lookup(last_block_line - 1)

            return (end + 1, end + 1) if end is not None else None

        anchor = source_map.get(span[0])

        if anchor is None:  # If unmapped, look for a mapped line forwards.
            anchor = _forward_lookup(span[0] + 1)

        return (anchor, anchor) if anchor is not None else None

    start = source_map.get(span[0])

    if start is None:  # If unmapped, look for a mapped line outwards.
        start = _backward_lookup(span[0] - 1)
    if start is None:  # If still unmapped, look for a mapped line inwards.
        start = _forward_lookup(span[0] + 1)

    end_inclusive = source_map.get(span[1] - 1)

    if end_inclusive is None:  # If unmapped, look for a mapped line outwards.
        end_inclusive = _forward_lookup(span[1])
    if end_inclusive is None:  # If still unmapped, look for a mapped line inwards.
        end_inclusive = _backward_lookup(span[1] - 2)

    if start is not None and end_inclusive is not None:
        if start > end_inclusive:
            # Inverted span: some p-code line in the range points further forward in ActionScript than
            # its immediate neighbors. Typically it is a loop condition p-code line or a function
            # definition header mapping to its closing brace.
            # Simple fix: fall back to the union of all mapped AS lines within the span.
            mapped = [v for k, v in source_map.items() if span[0] <= k < span[1] and v is not None]
            return (min(mapped), max(mapped) + 1) if mapped else None

        return (start, end_inclusive + 1)

    return None


def _merge_overlapping_span_pairs(diff_span_pairs: list[RenderDiffSpanPair]) -> list[RenderDiffSpanPair]:
    """
    Merge line span pairs when they are adjacent or overlapping on both sides.

    Require pairs to be sorted in ascending order to work properly.
    """
    if len(diff_span_pairs) < 2:
        return diff_span_pairs

    merged_pairs: list[RenderDiffSpanPair] = []
    last_pair: RenderDiffSpanPair | None = None

    for pair in diff_span_pairs:
        if last_pair is None:
            last_pair = pair
            continue

        assert pair.a is not None and pair.b is not None
        assert last_pair.a is not None and last_pair.b is not None

        if (
            last_pair.a[1] >= pair.a[0]
            and pair.a[1] >= last_pair.a[0]
            and last_pair.b[1] >= pair.b[0]
            and pair.b[1] >= last_pair.b[0]
        ):
            last_pair = RenderDiffSpanPair(
                a=(min(last_pair.a[0], pair.a[0]), max(last_pair.a[1], pair.a[1])),
                b=(min(last_pair.b[0], pair.b[0]), max(last_pair.b[1], pair.b[1])),
            )
        else:
            merged_pairs.append(last_pair)
            last_pair = pair

    assert last_pair is not None
    merged_pairs.append(last_pair)

    return merged_pairs


def _resolve_actionscript_block_spans(
    script: GfxScript,
    block: GfxScriptBlock,
    block_side_a: PcodeBlock | None,
    block_side_b: PcodeBlock | None,
    source_map_a: dict[int, int | None],
    source_map_b: dict[int, int | None],
    script_a_actionscript_line_count: int,
    script_b_actionscript_line_count: int,
) -> list[RenderDiffSpanPair]:
    """
    Translate a block's diff spans from normalized p-code coordinates into ActionScript line spans.

    Spans that cannot be resolved properly against the source map are dropped.
    Resulting span pairs are sorted in ascending order like so:
      1. by start line on side A
      2. then by start line on side B
      3. then by end line on side A
      4. then by end line on side B
    Resulting spans are also merged and deduplicated.
    """
    as_diff_spans: list[RenderDiffSpanPair] = []

    def _assert_valid_span(_span: tuple[int, int], _side: Literal["a", "b"], _orig_span: tuple[int, int]):
        _len = script_a_actionscript_line_count if _side == "a" else script_b_actionscript_line_count
        _script = (script.side_a_path if _side == "a" else script.side_b_path).as_posix()
        _blk = block.side_a_name if _side == "a" else block.side_b_name
        assert 0 <= _span[0] <= _span[1] <= _len, (
            f"ActionScript line span [{_span[0]}, {_span[1]}[ is malformed or out of range. The script has {_len} lines. "
            f"(origin span: [{_orig_span[0]}, {_orig_span[1]}[, side: {_side.upper()}, script: '{_script}', block: '{_blk}')"
        )

    if block.is_paired():
        assert block_side_a is not None
        assert block_side_b is not None

        diff_spans_in_raw_block = []

        # From normalized diff spans, retrieve the source (raw) p-code lines that are differing.
        for norm_span_a, norm_span_b in block.diff_spans:
            raw_span_a = _convert_span_from_normalized_pcode_to_raw(norm_span_a, block_side_a)
            raw_span_b = _convert_span_from_normalized_pcode_to_raw(norm_span_b, block_side_b)
            diff_spans_in_raw_block.append(RenderDiffSpanPair(a=raw_span_a, b=raw_span_b))

        # Now from p-code diff spans, retrieve the decompiled ActionScript source lines.
        for pcode_span_a, pcode_span_b in diff_spans_in_raw_block:
            as_span_a = _convert_span_from_pcode_to_actionscript(pcode_span_a, source_map_a)
            as_span_b = _convert_span_from_pcode_to_actionscript(pcode_span_b, source_map_b)
            if as_span_a is not None and as_span_b is not None:
                _assert_valid_span(as_span_a, "a", pcode_span_a)
                _assert_valid_span(as_span_b, "b", pcode_span_b)
                as_diff_spans.append(RenderDiffSpanPair(a=as_span_a, b=as_span_b))

    elif block.side_a_name is not None:
        assert block_side_a is not None
        raw_span_a = _convert_span_from_normalized_pcode_to_raw((0, len(block_side_a)), block_side_a)
        as_span_a = _convert_span_from_pcode_to_actionscript(raw_span_a, source_map_a)
        if as_span_a is not None:
            _assert_valid_span(as_span_a, "a", raw_span_a)
            as_diff_spans.append(RenderDiffSpanPair(a=as_span_a, b=None))

    elif block.side_b_name is not None:
        assert block_side_b is not None
        raw_span_b = _convert_span_from_normalized_pcode_to_raw((0, len(block_side_b)), block_side_b)
        as_span_b = _convert_span_from_pcode_to_actionscript(raw_span_b, source_map_b)
        if as_span_b is not None:
            _assert_valid_span(as_span_b, "b", raw_span_b)
            as_diff_spans.append(RenderDiffSpanPair(a=None, b=as_span_b))

    if not block.is_paired():
        # Unmatched blocks only produce one pair by construction, so there is no need to sort.
        return as_diff_spans

    as_diff_spans.sort(key=lambda p: (p.a[0], p.b[0], p.a[1], p.b[1]))  # pyright: ignore[reportOptionalSubscript]

    return _merge_overlapping_span_pairs(as_diff_spans)


def prepare_diffset_actionscript_render(
    diffset: GfxDiffSet,
    workspace_a: Workspace,
    normalized_script_blocks_a: dict[Path, list[PcodeBlock]],
    workspace_b: Workspace,
    normalized_script_blocks_b: dict[Path, list[PcodeBlock]],
    sort_order: DiffSortOrder,
    filters: DiffFilter,
) -> list[RenderableBlockDiff]:
    """
    Build the renderable elements for an ActionScript diff.

    Sort and filter differing script blocks, resolve decompiled ActionScript via SWD line maps (falling back to p-code
    when unmapped), then slice each block into context-padded ActionScript hunk pairs.
    """
    renderables: list[RenderableBlockDiff] = []
    sorted_pairs = get_sorted_and_filtered_script_block_pairs(diffset, sort_order, filters)

    if filters and not sorted_pairs:
        raise RuntimeError("No script or block name matches the provided filters.")

    # Cache for ActionScript sources.
    actionscript_cache: dict[Path, list[str]] = {}

    def _read_actionscript_source_lines(file: Path) -> list[str]:
        if file not in actionscript_cache:
            if not file.is_file():
                raise FileNotFoundError(f"ActionScript file not found: {escape(str(file))}.")
            actionscript_cache[file] = read_file_lines(file)

        return actionscript_cache[file]

    file_a_swd_pcode = parse_swd_file(workspace_a.find_debug_pcode_swd_file())
    file_a_swd_as = parse_swd_file(workspace_a.find_debug_actionscript_swd_file())
    file_b_swd_pcode = parse_swd_file(workspace_b.find_debug_pcode_swd_file())
    file_b_swd_as = parse_swd_file(workspace_b.find_debug_actionscript_swd_file())

    file_a_pcode_to_as_line_map = build_pcode_to_actionscript_line_map(
        file_a_swd_pcode, file_a_swd_as, {script.side_a_path.as_posix() for script, _ in sorted_pairs}
    )

    file_b_pcode_to_as_line_map = build_pcode_to_actionscript_line_map(
        file_b_swd_pcode, file_b_swd_as, {script.side_b_path.as_posix() for script, _ in sorted_pairs}
    )

    for script, block in sorted_pairs:
        assert script.side_a_path is not None  # type guard for static analyzers
        assert script.side_b_path is not None

        script_a_blocks = normalized_script_blocks_a.get(script.side_a_path, [])
        script_b_blocks = normalized_script_blocks_b.get(script.side_b_path, [])
        block_side_a = _find_pcode_block_by_name(script_a_blocks, block.side_a_name)
        block_side_b = _find_pcode_block_by_name(script_b_blocks, block.side_b_name)

        script_a_name = script.side_a_path.as_posix()
        script_b_name = script.side_b_path.as_posix()

        if script_a_name not in file_a_pcode_to_as_line_map:
            raise RuntimeError(f"Script {script_a_name!r} not found in SWD file.")

        if script_b_name not in file_b_pcode_to_as_line_map:
            raise RuntimeError(f"Script {script_b_name!r} not found in SWD file.")

        # Prepare source line mapping from raw p-code to ActionScript.
        block_a_pcode_to_as_map: dict[int, int | None] = _build_block_source_map(
            block_side_a, file_a_pcode_to_as_line_map[script_a_name]
        )

        block_b_pcode_to_as_map: dict[int, int | None] = _build_block_source_map(
            block_side_b, file_b_pcode_to_as_line_map[script_b_name]
        )

        script_a_actionscript_lines = _read_actionscript_source_lines(
            workspace_a.find_actionscript_file(script.side_a_path)
        )

        script_b_actionscript_lines = _read_actionscript_source_lines(
            workspace_b.find_actionscript_file(script.side_b_path)
        )

        # Resolve ActionScript diff spans from normalized p-code spans.
        diff_spans_in_as_source = _resolve_actionscript_block_spans(
            script,
            block,
            block_side_a,
            block_side_b,
            block_a_pcode_to_as_map,
            block_b_pcode_to_as_map,
            len(script_a_actionscript_lines),
            len(script_b_actionscript_lines),
        )

        # Finally, extract the differing hunks of ActionScript that we need to display.
        # Sometimes we will not be able to resolve ActionScript code, then we will fall back to p-code.
        block_a_corpus_lines: list[str]
        block_b_corpus_lines: list[str]
        diff_spans: list[RenderDiffSpanPair]
        block_lang: Literal["actionscript", "pcode"]
        side_a_resolved: bool
        side_b_resolved: bool
        prologue_messages: list[str] = []

        if diff_spans_in_as_source:
            # If we could resolve AS code for one side at least.
            block_a_corpus_lines = script_a_actionscript_lines
            block_b_corpus_lines = script_b_actionscript_lines
            diff_spans = diff_spans_in_as_source
            block_lang = "actionscript"
            side_a_resolved = block.side_a_name is None or any(ds.a is not None for ds in diff_spans)
            side_b_resolved = block.side_b_name is None or any(ds.b is not None for ds in diff_spans)
        else:
            # If we could not resolve ActionScript code at all, we fall back to p-code instead.
            block_a_corpus_lines, block_b_corpus_lines, diff_spans = _pcode_block_render_data(
                block, block_side_a, block_side_b
            )

            block_lang = "pcode"
            side_a_resolved = block.side_a_name is None or bool(diff_spans)
            side_b_resolved = block.side_b_name is None or bool(diff_spans)

            prologue_messages.append(
                "[yellow]Unable to map pcode lines to ActionScript source for this block. Falling back to normalized p-code.[/yellow]"
            )

        hunk_pairs = align_hunk_pairs(
            cut_text_hunks_with_context(
                block_a_corpus_lines, [ds.a for ds in diff_spans if ds.a is not None], context_length=5, merge=True
            ),
            cut_text_hunks_with_context(
                block_b_corpus_lines, [ds.b for ds in diff_spans if ds.b is not None], context_length=5, merge=True
            ),
        )

        renderables.append(
            RenderableBlockDiff(
                script=script,
                block=block,
                hunk_pairs=hunk_pairs,
                lang=block_lang,
                side_a_resolved=side_a_resolved,
                side_b_resolved=side_b_resolved,
                prologue_messages=prologue_messages,
            )
        )

    return renderables


def build_split_layout_for_hunk_pair(
    hunk_a: TextHunk, hunk_b: TextHunk, block_diff: RenderableBlockDiff
) -> SplitLayout:
    """
    Take a pair of hunks, annotate their differences, and build a SplitLayout Rich renderable component.
    """
    side_a: DiffAnnotatedHunk | SplitLayoutMessagePane
    side_b: DiffAnnotatedHunk | SplitLayoutMessagePane

    if block_diff.block.is_paired():
        if block_diff.side_a_resolved and block_diff.side_b_resolved:
            side_a, side_b = diff_text_hunks(hunk_a, hunk_b)
        elif not block_diff.side_a_resolved:
            side_a = SplitLayoutMessagePane(
                "[yellow]Unable to map pcode lines to ActionScript source on this side.[/yellow]"
            )
            side_b = DiffAnnotatedHunk.wrap(
                TextHunk([(ln.reannotate(is_addition=True) if not ln.is_context else ln) for ln in hunk_b])
            )
        elif not block_diff.side_b_resolved:
            side_a = DiffAnnotatedHunk.wrap(
                TextHunk([(ln.reannotate(is_deletion=True) if not ln.is_context else ln) for ln in hunk_a])
            )
            side_b = SplitLayoutMessagePane(
                "[yellow]Unable to map pcode lines to ActionScript source on this side.[/yellow]"
            )
    else:
        if block_diff.block.side_a_name is None:
            side_a = SplitLayoutMessagePane("[dim]This block does not exist on side A.[/dim]")
            _, side_b = diff_text_hunks(TextHunk(), hunk_b)
        else:
            side_a, _ = diff_text_hunks(hunk_a, TextHunk())
            side_b = SplitLayoutMessagePane("[dim]This block does not exist on side B.[/dim]")

    syntax_lexer: Lexer | None = None

    if block_diff.lang == "actionscript":
        syntax_lexer = ActionScriptLexer()

    return SplitLayout.from_pair(side_a, side_b, syntax_lexer=syntax_lexer, word_wrap=True)


def build_unified_layout_for_block_diff(block_diff: RenderableBlockDiff) -> UnifiedLayout:
    """
    Build a UnifiedLayout for a whole block diff: one `--- / +++` header pair, and one `@@` header
    per `(hunk_a, hunk_b)` pair.

    Each pair is classified into context / deletion / insertion segments via `diff_text_hunks`.
    """
    script = block_diff.script
    block = block_diff.block

    def _side_path(script_path: Path | None, block_name: str | None) -> str | None:
        if script_path is not None and block_name is not None:
            return f"{script_path.as_posix()}:{block_name}"
        else:
            return None

    return UnifiedLayout(
        _side_path(script.side_a_path, block.side_a_name),
        _side_path(script.side_b_path, block.side_b_name),
        [diff_text_hunks(hunk_a, hunk_b) for hunk_a, hunk_b in block_diff.hunk_pairs],
    )
