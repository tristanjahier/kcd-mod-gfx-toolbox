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
    DiffHunk,
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
) -> tuple[list[str], set[int], list[str], set[int]]:
    """
    For a given block, align side B's labels and registers to side A, compute the differences,
    then return plain-text block lines and anchor line indices for each side.
    """
    block_a_lines = [ln.render() for ln in block_side_a.lines] if block_side_a else []
    block_b_lines = [ln.render() for ln in block_side_b.lines] if block_side_b else []
    block_b_lines = align_labels_in_text(block_b_lines, anchor_lines=block_a_lines)
    block_b_lines = align_registers_in_text(block_b_lines, anchor_lines=block_a_lines)

    # Recompute diff spans on aligned lines: block.diff_spans was computed on normalized but
    # unaligned block content and would reference lines that, after label/register alignment,
    # no longer actually differ, producing spurious hunks of unchanged content.
    block_a_diff_lines: set[int] = set()
    block_b_diff_lines: set[int] = set()

    if block.is_paired():
        aligned_diff = diff_texts(block_a_lines, block_b_lines)

        for diff_span_a, diff_span_b in aligned_diff.spans:
            block_a_diff_lines.update(range(diff_span_a[0], diff_span_a[1]))
            block_b_diff_lines.update(range(diff_span_b[0], diff_span_b[1]))

            # For pure insertions/deletions, add a line anchor on the "empty" side
            # so cut_text_hunks_with_context captures context lines there, allowing
            # align_hunk_pairs to produce a side-by-side hunk instead of an empty column.
            if diff_span_a[0] == diff_span_a[1] and block_a_lines:
                block_a_diff_lines.add(min(diff_span_a[0], len(block_a_lines) - 1))
            if diff_span_b[0] == diff_span_b[1] and block_b_lines:
                block_b_diff_lines.add(min(diff_span_b[0], len(block_b_lines) - 1))
    else:
        # For unmatched blocks there are no diff spans, so we have no choice but to display the whole block.
        if block_side_a is not None:
            block_a_diff_lines = set(range(0, len(block_side_a.lines)))

        if block_side_b is not None:
            block_b_diff_lines = set(range(0, len(block_side_b.lines)))

    return block_a_lines, block_a_diff_lines, block_b_lines, block_b_diff_lines


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

        block_a_lines, block_a_diff_lines, block_b_lines, block_b_diff_lines = _pcode_block_render_data(
            block, block_side_a, block_side_b
        )

        hunk_pairs = align_hunk_pairs(
            cut_text_hunks_with_context(block_a_lines, block_a_diff_lines, context_length=5, merge=True),
            cut_text_hunks_with_context(block_b_lines, block_b_diff_lines, context_length=5, merge=True),
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

        script_a_pcode_to_as = file_a_pcode_to_as_line_map[script_a_name]
        script_b_pcode_to_as = file_b_pcode_to_as_line_map[script_b_name]

        # Prepare source line mapping from normalized p-code to raw p-code.
        # Mapped lines in ActionScript are sparse. Simple naive improvement: propagate mapped
        # lines to subsequent unmapped lines, within the boundaries of the block.
        block_a_pcode_to_as: dict[int, int | None] = {}
        block_b_pcode_to_as: dict[int, int | None] = {}

        if block_side_a is not None:
            block_a_first_line = min(block_side_a.lines[0].source_lines)
            block_a_last_line = max(block_side_a.lines[-1].source_lines)
            block_a_pcode_to_as = propagate_mapped_lines_to_subsequent_unmapped_lines(
                {k: v for k, v in script_a_pcode_to_as.items() if block_a_first_line <= k <= block_a_last_line}
            )

        if block_side_b is not None:
            block_b_first_line = min(block_side_b.lines[0].source_lines)
            block_b_last_line = max(block_side_b.lines[-1].source_lines)
            block_b_pcode_to_as = propagate_mapped_lines_to_subsequent_unmapped_lines(
                {k: v for k, v in script_b_pcode_to_as.items() if block_b_first_line <= k <= block_b_last_line}
            )

        # From normalized diff spans, retrieve the source (raw) p-code lines that are differing.
        diff_lines_in_raw_block_a: set[int] = set()
        diff_lines_in_raw_block_b: set[int] = set()

        if block.is_paired():
            for diff_span_a, diff_span_b in block.diff_spans:
                for pcode_line in block_side_a.lines[diff_span_a[0] : diff_span_a[1]]:
                    diff_lines_in_raw_block_a.update(pcode_line.source_lines)

                for pcode_line in block_side_b.lines[diff_span_b[0] : diff_span_b[1]]:
                    diff_lines_in_raw_block_b.update(pcode_line.source_lines)
        else:
            if block_side_a is not None:
                diff_lines_in_raw_block_a = set(merge_pcode_lines_sources(*block_side_a.lines))
            if block_side_b is not None:
                diff_lines_in_raw_block_b = set(merge_pcode_lines_sources(*block_side_b.lines))

        # Now from p-code diff spans, retrieve the decompiled ActionScript source lines.
        diff_lines_in_as_source_a: set[int] = set()
        diff_lines_in_as_source_b: set[int] = set()

        script_a_actionscript_lines = _read_actionscript_source_lines(
            workspace_a.find_actionscript_file(script.side_a_path)
        )

        script_b_actionscript_lines = _read_actionscript_source_lines(
            workspace_b.find_actionscript_file(script.side_b_path)
        )

        for ln in diff_lines_in_raw_block_a:
            as_src_line = block_a_pcode_to_as.get(ln)
            if as_src_line is not None:
                assert 0 <= as_src_line < len(script_a_actionscript_lines), (
                    f"Mapped ActionScript line {as_src_line} is out of bounds! Side A script {script_a_name} has {len(script_a_actionscript_lines)} lines."
                )
                diff_lines_in_as_source_a.add(as_src_line)

        for ln in diff_lines_in_raw_block_b:
            as_src_line = block_b_pcode_to_as.get(ln)
            if as_src_line is not None:
                assert 0 <= as_src_line < len(script_b_actionscript_lines), (
                    f"Mapped ActionScript line {as_src_line} is out of bounds! Side B script {script_b_name} has {len(script_b_actionscript_lines)} lines."
                )
                diff_lines_in_as_source_b.add(as_src_line)

        # Finally, extract the differing hunks of ActionScript that we need to display.
        # Sometimes we will not be able to resolve ActionScript code, then we will fall back to p-code.
        block_a_corpus_lines: list[str]
        block_a_diff_lines: set[int]
        block_b_corpus_lines: list[str]
        block_b_diff_lines: set[int]
        block_lang: Literal["actionscript", "pcode"]
        side_a_resolved: bool
        side_b_resolved: bool
        prologue_messages: list[str] = []

        if diff_lines_in_as_source_a or diff_lines_in_as_source_b:
            # If we could resolve AS code for one side at least.
            block_a_corpus_lines = script_a_actionscript_lines
            block_a_diff_lines = diff_lines_in_as_source_a
            block_b_corpus_lines = script_b_actionscript_lines
            block_b_diff_lines = diff_lines_in_as_source_b
            block_lang = "actionscript"
            side_a_resolved = block.side_a_name is None or bool(diff_lines_in_as_source_a)
            side_b_resolved = block.side_b_name is None or bool(diff_lines_in_as_source_b)
        else:
            # If we could not resolve ActionScript code at all, we fall back to p-code instead.
            block_a_corpus_lines, block_a_diff_lines, block_b_corpus_lines, block_b_diff_lines = (
                _pcode_block_render_data(block, block_side_a, block_side_b)
            )

            block_lang = "pcode"
            side_a_resolved = block.side_a_name is None or bool(block_a_diff_lines)
            side_b_resolved = block.side_b_name is None or bool(block_b_diff_lines)

            prologue_messages.append(
                "[yellow]Unable to map pcode lines to ActionScript source for this block. Falling back to normalized p-code.[/yellow]"
            )

        hunk_pairs = align_hunk_pairs(
            cut_text_hunks_with_context(block_a_corpus_lines, block_a_diff_lines, context_length=5, merge=True),
            cut_text_hunks_with_context(block_b_corpus_lines, block_b_diff_lines, context_length=5, merge=True),
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
    side_a: DiffHunk | SplitLayoutMessagePane
    side_b: DiffHunk | SplitLayoutMessagePane

    if block_diff.block.is_paired():
        if block_diff.side_a_resolved and block_diff.side_b_resolved:
            side_a, side_b = diff_text_hunks(hunk_a, hunk_b)
        elif not block_diff.side_a_resolved:
            side_a = SplitLayoutMessagePane(
                "[yellow]Unable to map pcode lines to ActionScript source on this side.[/yellow]"
            )
            side_b = DiffHunk.wrap(
                TextHunk([(ln.reannotate(is_addition=True) if not ln.is_context else ln) for ln in hunk_b])
            )
        elif not block_diff.side_b_resolved:
            side_a = DiffHunk.wrap(
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
