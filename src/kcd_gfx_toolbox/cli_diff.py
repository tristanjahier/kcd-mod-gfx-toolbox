#!/usr/bin/env python3

from __future__ import annotations
from enum import StrEnum
import json
from typing import Annotated, Literal, cast
import typer

from .workspace import Workspace, temp_workspace_name_for_file
from .avm1.pcode_parsing import PcodeBlock, PcodeLine, merge_pcode_lines_sources, parse_pcode_file
from .swd import (
    build_pcode_to_actionscript_line_map,
    parse_swd_file,
    propagate_mapped_lines_to_subsequent_unmapped_lines,
)
from .gfx_diff import (
    GfxDiffSet,
    GfxDiffTreeNode,
    GfxDiffTreeNodeType,
    GfxScript,
    GfxScriptBlock,
    diff_normalized_script_trees,
    refine_block_diffs,
)
from .extraction import (
    extract_gfx_contents,
    resolve_ffdec,
)
from .avm1.pcode_normalization import NormalizationResult, normalize_file
from .file_diff import (
    align_hunk_pairs,
    cut_text_hunks_with_context,
    diff_file_trees_basic,
)
from .utils import (
    console,
    ensure_empty_dir,
    print_error,
    print_warning,
    read_file_lines,
)
from .split_diff_view import SplitDiffView, SplitDiffViewMessagePane
from pathlib import Path
import shutil
import subprocess
from rich.table import Table
from rich import box
from rich.rule import Rule
from rich.markup import escape
from pygments.lexer import Lexer
from pygments.lexers import ActionScriptLexer


class DiffSortOrder(StrEnum):
    NATURAL = "natural"
    CHANGES_DESC = "changes_desc"
    CHANGES_ASC = "changes_asc"


def format_script_path(path: Path | str, path_rename: Path | str | None = None) -> str:
    """Format a GFx script path for display, optionally showing a rename."""
    path = Path(path)

    if path.parent != Path("."):
        text = f"{path.parent.as_posix()}/[bright_cyan]{path.name}[/bright_cyan]"
    else:
        text = f"[bright_cyan]{path.name}[/bright_cyan]"

    if path_rename is not None and path != Path(path_rename):
        text += " [bright_white]→[/bright_white] " + format_script_path(path_rename)

    return text


def format_script_block_name(name: str, rename: str | None = None) -> str:
    """Format a script block name for display, optionally showing a rename."""
    text = "[bright_yellow]❖[/bright_yellow] " + name

    if rename is not None and name != rename:
        text += " [bright_yellow]→[/bright_yellow] " + rename

    return text


def extract_gfx_file(ffdec_path: Path, gfx_file: Path, workspace: Workspace, read_cache: bool):
    extraction_dir = workspace.extraction_dir()
    console.print(
        f"{escape(str(gfx_file))} -> [link={escape(extraction_dir.as_uri())}]{escape(str(extraction_dir))}[/link]"
    )

    if read_cache and workspace.extraction_dir_has_content():
        if workspace.extraction_dir_has_valid_contents():
            console.print("Extracted content already present in the target directory. Skipping.")
            return
        else:
            print_warning(
                "Extraction directory is not empty, but it appears partial, corrupted, or unrelated. Re-extracting."
            )

    try:
        shutil.rmtree(extraction_dir)
    except FileNotFoundError:
        pass

    extraction_dir.mkdir(parents=True, exist_ok=True)

    try:
        extract_gfx_contents(ffdec_path, gfx_file, extraction_dir)
    except subprocess.CalledProcessError as e:
        print_error(f"ffdec failed with code {e.returncode}:")
        if e.stderr:
            print_error(escape(str(e.stderr)))
        raise typer.Exit(code=1)


def read_cached_normalized_script_blocks(workspace: Workspace, script_path: Path) -> NormalizationResult:
    """
    Compute normalization stats from an existing normalized-blocks directory.
    """
    cache_dir = workspace.normalization_path(script_path)

    if not cache_dir.is_dir():
        raise FileNotFoundError(f"Missing normalization cache directory: {cache_dir}.")

    pcode_blocks: list[PcodeBlock] = []
    total_blocks = named_blocks = anonymous_blocks = toplevel_blocks = 0

    for block_file in workspace.list_normalized_block_files(script_path):
        block_file = cache_dir / block_file
        total_blocks += 1
        block_name = block_file.stem

        if block_name.startswith("__toplevel"):
            toplevel_blocks += 1
        elif block_name.startswith("__anonymous"):
            anonymous_blocks += 1
        else:
            named_blocks += 1

        block_sourcemap = json.loads(block_file.with_suffix(".pcode.map").read_text(encoding="utf-8"))
        sourced_pcode_lines: list[PcodeLine] = []

        for i, pcode_line in enumerate(parse_pcode_file(block_file).lines):
            sourced_pcode_lines.append(pcode_line.replace(source_lines=block_sourcemap[i]))

        pcode_blocks.append(PcodeBlock(name=block_name, lines=sourced_pcode_lines))

    if total_blocks == 0:
        raise FileNotFoundError(f"Normalization cache directory is empty: {cache_dir}.")

    block_list = workspace.find_block_order_file(script_path).read_text(encoding="utf-8").splitlines()
    block_order_dict = {name: i for i, name in enumerate(block_list) if name.strip()}

    if {b.name for b in pcode_blocks} != set(block_order_dict.keys()):
        raise FileNotFoundError(f"Normalization cache directory is corrupted: {cache_dir}.")

    pcode_blocks.sort(key=lambda b: block_order_dict[b.name])

    return NormalizationResult(
        blocks=pcode_blocks,
        total_blocks=total_blocks,
        named_blocks=named_blocks,
        anonymous_blocks=anonymous_blocks,
        toplevel_blocks=toplevel_blocks,
    )


def normalize_scripts(
    gfx_file: Path, workspace: Workspace, scripts: set[Path], read_cache: bool
) -> dict[Path, list[PcodeBlock]]:
    """
    Perform normalization on given scripts, or reuse the cached data if applicable.
    """
    results: list[tuple[Path, NormalizationResult]] = []
    normalized_script_blocks: dict[Path, list[PcodeBlock]] = {}
    read_cache = read_cache and workspace.normalization_dir_has_content()

    for script_path in scripts:
        raw_script_path = workspace.find_raw_pcode_file(script_path)
        normalized_script_dir = workspace.normalization_path(script_path)
        norm_stats = None

        if read_cache:
            try:
                norm_stats = read_cached_normalized_script_blocks(workspace, script_path)
            except FileNotFoundError:
                print_warning(f"Normalization cache missing: {escape(str(normalized_script_dir))}.")  # Not fatal

        if norm_stats is None:
            ensure_empty_dir(normalized_script_dir)

            try:
                norm_stats = normalize_file(raw_script_path, normalized_script_dir)
            except Exception as e:
                print_error(f"Normalization failed: {escape(str(raw_script_path))}")
                print_error(e)
                raise typer.Exit(code=1)

        results.append((script_path, norm_stats))
        normalized_script_blocks[script_path] = norm_stats.blocks

    console.print(f"{escape(str(gfx_file))}:")

    result_table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, show_header=False)
    result_table.add_column("p-code file")
    result_table.add_column("Blocks", justify="right")
    result_table.add_column("Named", justify="right")
    result_table.add_column("Anonymous", justify="right")
    result_table.add_column("Top-level", justify="right")

    results.sort(key=lambda res: res[0])

    for rel_path, stats in results:
        result_table.add_row(
            format_script_path(rel_path),
            f"{stats.total_blocks} blocks",
            f"{stats.named_blocks} named",
            f"{stats.anonymous_blocks} anonymous",
            f"{stats.toplevel_blocks} top-level",
        )

    console.print(result_table)

    return normalized_script_blocks


def unfold_diff_tree_in_table(tree: GfxDiffTreeNode, table: Table, sort_order: DiffSortOrder):
    """
    Append script paths and blocks as a tree to a Rich table.
    Script paths are sorted in alphabetical order.
    Script blocks are sorted by number of lines changed.
    """

    def _node_sort_key(n: GfxDiffTreeNode):
        if n.type == GfxDiffTreeNodeType.DIRECTORY:
            return cast(str, n.value)
        elif n.type == GfxDiffTreeNodeType.SCRIPT:
            script = cast(GfxScript, n.value)
            return (
                f"{script.side_a_path}|{script.side_b_path}"
                if script.is_paired()
                else str(script.side_a_path or script.side_b_path)
            )
        elif n.type == GfxDiffTreeNodeType.SCRIPT_BLOCK:
            block = cast(GfxScriptBlock, n.value)
            block_name_key = (
                f"{block.side_a_name}|{block.side_b_name}"
                if block.is_paired()
                else str(block.side_a_name or block.side_b_name)
            )
            if sort_order == DiffSortOrder.NATURAL:
                return (block.position, block_name_key)
            elif sort_order == DiffSortOrder.CHANGES_ASC:
                return (block.refined_changed, block_name_key)
            return (-block.refined_changed, block_name_key)
        assert False, "must never reach this code."

    def _render_node(node: GfxDiffTreeNode, line_prefix: str = "", depth: int = 0, is_last_child: bool = False):
        if depth == 0:
            connector = ""
            children_line_prefix = " "
        else:
            connector = "└── " if is_last_child else "├── "
            children_line_prefix = line_prefix + ("    " if is_last_child else "│   ") + " "

        node_text = ""
        node_state = ""
        node_change_values = ()

        if node.type == GfxDiffTreeNodeType.DIRECTORY:
            node_text = f"🗁  {node.value}/"

        elif node.type == GfxDiffTreeNodeType.SCRIPT:
            script = cast(GfxScript, node.value)
            if script.is_paired():
                node_text = format_script_path(script.side_a_path.name, script.side_b_path.name)
                if script.was_renamed():
                    node_state = "[yellow]modified[/yellow], [bright_blue]renamed[/bright_blue]"
                else:
                    node_state = "[yellow]modified[/yellow]"
            elif script.side_b_path is None:  # unmatched from side A
                node_text = format_script_path(script.side_a_path.name)
                node_state = "[red]deleted[/red]"
            else:  # unmatched from side B
                node_text = format_script_path(script.side_b_path.name)
                node_state = "[green]new[/green]"

        elif node.type == GfxDiffTreeNodeType.SCRIPT_BLOCK:
            block = cast(GfxScriptBlock, node.value)
            node_text = format_script_block_name(block.side_a_name or block.side_b_name, block.side_b_name)
            if block.is_paired():
                if block.was_renamed():
                    node_state = "[yellow]modified[/yellow], [bright_blue]renamed[/bright_blue]"
                else:
                    node_state = "[yellow]modified[/yellow]"

                refine_ratio = block.refined_changed / block.changed
                refined_text = str(block.refined_changed)

                if refine_ratio < 1:
                    percent = round((1 - refine_ratio) * 100)
                    refined_text = f"[bold green]🡖 {percent}%[/bold green] {block.refined_changed}"
                elif refine_ratio > 1:
                    percent = round((refine_ratio - 1) * 100)
                    refined_text = f"[bold red]🡕 {percent}%[/bold red] {block.refined_changed}"

                node_change_values = (str(block.changed), refined_text)
            elif block.side_b_name is None:  # unmatched from side A
                node_state = "[red]deleted[/red]"
                node_change_values = ("-", "-")
            else:  # unmatched from side B
                node_state = "[green]new[/green]"
                node_change_values = ("-", "-")

        table.add_row(f"{line_prefix}{connector}{node_text}", f"[italic]{node_state}[/italic]", *node_change_values)

        # Then we recursively render all node children, sorted in a node-type-specific logic.
        children = sorted(node.children, key=_node_sort_key)

        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            _render_node(child, children_line_prefix, is_last_child=is_last, depth=depth + 1)

    # The tree root is virtual and must not be rendered itself.
    # Instead we render its children directly.
    root_children = sorted(tree.children, key=_node_sort_key)

    for i, child in enumerate(root_children):
        is_last = i == len(root_children) - 1
        _render_node(child, is_last_child=is_last)


def display_detailed_diff_in_pcode(diffset: GfxDiffSet, sort_order: DiffSortOrder, max_lines: int = 0):
    """
    Display line-by-line differences for each modified script block.
    """
    line_count = 0

    sorted_pairs: list[tuple[GfxScript, GfxScriptBlock]] = []

    scripts = sorted(diffset.get_scripts_with_differing_blocks(), key=lambda s: (s.side_a_path, s.side_b_path))

    for script in scripts:
        blocks = sorted(
            diffset.paired_scripts_block_diffs[script].paired_blocks,
            key=lambda b: (b.position, b.side_a_name, b.side_b_name),
        )

        for block in blocks:
            if block.is_paired() and block.unified_diff:
                sorted_pairs.append((script, block))

    if sort_order == DiffSortOrder.CHANGES_ASC:
        sorted_pairs.sort(key=lambda p: (p[1].refined_changed, p[1].side_a_name, p[1].side_b_name))
    elif sort_order == DiffSortOrder.CHANGES_DESC:
        sorted_pairs.sort(key=lambda p: (-p[1].refined_changed, p[1].side_a_name, p[1].side_b_name))

    for script, block in sorted_pairs:
        if line_count > 0:
            console.line()
            line_count += 1

        for line in block.unified_diff:
            line = line.rstrip("\n")

            if max_lines != 0 and line_count >= max_lines:
                console.print(
                    f"[bold yellow]---- Diff details truncated at {line_count} lines. Use [italic]--details-truncate=0[/italic] to remove this limit. ----[/bold yellow]"
                )
                return

            if line.startswith("---"):
                line = f"--- a/{script.side_a_path.as_posix()}:{block.side_a_name}"
                console.print(f"[bold]{escape(line)}[/bold]", highlight=False)
            elif line.startswith("+++"):
                line = f"+++ b/{script.side_b_path.as_posix()}:{block.side_b_name}"
                console.print(f"[bold]{escape(line)}[/bold]", highlight=False)
            elif line.startswith("@@"):
                console.print(f"[cyan]{escape(line)}[/cyan]", highlight=False)
            elif line.startswith("+"):
                console.print(f"[green]{escape(line)}[/green]", highlight=False)
            elif line.startswith("-"):
                console.print(f"[red]{escape(line)}[/red]", highlight=False)
            else:
                console.print(escape(line), highlight=False)

            line_count += 1


def display_detailed_diff_in_actionscript(
    workspace_a: Workspace,
    normalized_script_blocks_a: dict[Path, list[PcodeBlock]],
    workspace_b: Workspace,
    normalized_script_blocks_b: dict[Path, list[PcodeBlock]],
    diffset: GfxDiffSet,
    sort_order: DiffSortOrder,
    max_lines: int = 0,
):
    line_count = 0

    sorted_pairs: list[tuple[GfxScript, GfxScriptBlock]] = []

    scripts = sorted(diffset.get_scripts_with_differing_blocks(), key=lambda s: (s.side_a_path, s.side_b_path))

    for script in scripts:
        blocks = sorted(
            diffset.paired_scripts_block_diffs[script].get_differing_blocks(),
            key=lambda b: (b.position, b.side_a_name or b.side_b_name),
        )

        for block in blocks:
            sorted_pairs.append((script, block))

    if sort_order == DiffSortOrder.CHANGES_ASC:
        sorted_pairs.sort(key=lambda p: (p[1].refined_changed, p[1].side_a_name or p[1].side_b_name))
    elif sort_order == DiffSortOrder.CHANGES_DESC:
        sorted_pairs.sort(key=lambda p: (-p[1].refined_changed, p[1].side_a_name or p[1].side_b_name))

    # Cache for ActionScript sources.
    actionscript_cache: dict[Path, list[str]] = {}

    def _read_actionscript_source_lines(file: Path) -> list[str]:
        if file not in actionscript_cache:
            if not file.is_file():
                print_error(f"ActionScript file not found: {escape(str(file))}.")
                raise typer.Exit(code=1)
            actionscript_cache[file] = read_file_lines(file)

        return actionscript_cache[file]

    try:
        file_a_swd_pcode = parse_swd_file(workspace_a.find_debug_pcode_swd_file())
        file_a_swd_as = parse_swd_file(workspace_a.find_debug_actionscript_swd_file())
        file_b_swd_pcode = parse_swd_file(workspace_b.find_debug_pcode_swd_file())
        file_b_swd_as = parse_swd_file(workspace_b.find_debug_actionscript_swd_file())
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1)

    file_a_pcode_to_as_line_map = build_pcode_to_actionscript_line_map(
        file_a_swd_pcode, file_a_swd_as, {script.side_a_path.as_posix() for script in scripts}
    )

    file_b_pcode_to_as_line_map = build_pcode_to_actionscript_line_map(
        file_b_swd_pcode, file_b_swd_as, {script.side_b_path.as_posix() for script in scripts}
    )

    context_first_block_diff_display = True

    for script, block in sorted_pairs:
        assert script.side_a_path is not None  # type guard for static analyzers
        assert script.side_b_path is not None

        if max_lines != 0 and line_count >= max_lines:
            console.print(
                Rule(
                    f"[bold yellow]✀  Diff details truncated at {line_count} lines (soft limit is {max_lines}). Use [italic]--details-truncate=0[/italic] to remove this limit.[/bold yellow]",
                    align="center",
                    style="bold yellow",
                    characters="-",
                )
            )
            console.line()
            return

        script_a_actionscript_lines = _read_actionscript_source_lines(
            workspace_a.find_actionscript_file(script.side_a_path)
        )

        script_b_actionscript_lines = _read_actionscript_source_lines(
            workspace_b.find_actionscript_file(script.side_b_path)
        )

        script_a_name = script.side_a_path.as_posix()
        if script_a_name not in file_a_pcode_to_as_line_map:
            print_error(f"Script {script_a_name!r} not found in SWD file.")
            raise typer.Exit(code=1)
        script_a_pcode_to_as = file_a_pcode_to_as_line_map[script_a_name]

        script_b_name = script.side_b_path.as_posix()
        if script_b_name not in file_b_pcode_to_as_line_map:
            print_error(f"Script {script_b_name!r} not found in SWD file.")
            raise typer.Exit(code=1)
        script_b_pcode_to_as = file_b_pcode_to_as_line_map[script_b_name]

        script_a_blocks = normalized_script_blocks_a.get(script.side_a_path, [])
        script_b_blocks = normalized_script_blocks_b.get(script.side_b_path, [])

        if not context_first_block_diff_display:
            console.line()
            line_count += 1

        script_title = format_script_path(script.side_a_path, script.side_b_path)
        block_title = format_script_block_name(block.side_a_name or block.side_b_name, block.side_b_name)

        console.print(
            Rule(
                f"[dim white]────[/dim white] {script_title} [dim white]──[/dim white] {block_title}",
                align="left",
                style="dim white",
            )
        )
        line_count += 1

        block_side_a = next((b for b in script_a_blocks if b.name == block.side_a_name), None)
        block_side_b = next((b for b in script_b_blocks if b.name == block.side_b_name), None)

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

        concerned_lines_in_raw_block_a: set[int] = set()
        concerned_lines_in_raw_block_b: set[int] = set()

        if block.is_paired():
            for diff_span_a, diff_span_b in block.diff_spans:
                for pcode_line in block_side_a.lines[diff_span_a[0] : diff_span_a[1]]:
                    concerned_lines_in_raw_block_a.update(pcode_line.source_lines)

                for pcode_line in block_side_b.lines[diff_span_b[0] : diff_span_b[1]]:
                    concerned_lines_in_raw_block_b.update(pcode_line.source_lines)
        else:
            if block_side_a is not None:
                concerned_lines_in_raw_block_a = set(merge_pcode_lines_sources(*block_side_a.lines))
            if block_side_b is not None:
                concerned_lines_in_raw_block_b = set(merge_pcode_lines_sources(*block_side_b.lines))

        concerned_lines_in_as_source_a: set[int] = set()
        for ln in concerned_lines_in_raw_block_a:
            as_src_line = block_a_pcode_to_as.get(ln)
            if as_src_line is not None:
                assert 0 <= as_src_line < len(script_a_actionscript_lines), (
                    f"Mapped ActionScript line {as_src_line} is out of bounds! Side A script {script_a_name} has {len(script_a_actionscript_lines)} lines."
                )
                concerned_lines_in_as_source_a.add(as_src_line)

        concerned_lines_in_as_source_b: set[int] = set()
        for ln in concerned_lines_in_raw_block_b:
            as_src_line = block_b_pcode_to_as.get(ln)
            if as_src_line is not None:
                assert 0 <= as_src_line < len(script_b_actionscript_lines), (
                    f"Mapped ActionScript line {as_src_line} is out of bounds! Side B script {script_b_name} has {len(script_b_actionscript_lines)} lines."
                )
                concerned_lines_in_as_source_b.add(as_src_line)

        block_a_corpus_lines: list[str]
        block_a_diff_lines: set[int]
        block_b_corpus_lines: list[str]
        block_b_diff_lines: set[int]
        syntax_lexer: Lexer | None

        if concerned_lines_in_as_source_a or concerned_lines_in_as_source_b:
            block_a_corpus_lines = script_a_actionscript_lines
            block_a_diff_lines = concerned_lines_in_as_source_a
            block_b_corpus_lines = script_b_actionscript_lines
            block_b_diff_lines = concerned_lines_in_as_source_b
            syntax_lexer = ActionScriptLexer()
        else:
            console.line()
            console.print(
                "[yellow]Unable to map pcode lines to ActionScript source for this block. Falling back to normalized p-code.[/yellow]"
            )
            line_count += 2

            concerned_lines_in_normalized_block_a: set[int] = set()
            concerned_lines_in_normalized_block_b: set[int] = set()

            block_a_corpus_lines = [ln.render() for ln in block_side_a.lines] if block_side_a is not None else []
            block_b_corpus_lines = [ln.render() for ln in block_side_b.lines] if block_side_b is not None else []

            if block.is_paired():
                for diff_span_a, diff_span_b in block.diff_spans:
                    concerned_lines_in_normalized_block_a.update(range(diff_span_a[0], diff_span_a[1]))
                    concerned_lines_in_normalized_block_b.update(range(diff_span_b[0], diff_span_b[1]))
            else:
                # For unmatched blocks with no mapped ActionScript source lines, simply display the whole p-code block.
                # This branch is probably practically dead, even though, in theory, it could happen.
                if block_side_a is not None:
                    concerned_lines_in_normalized_block_a = set(range(0, len(block_side_a.lines)))

                if block_side_b is not None:
                    concerned_lines_in_normalized_block_b = set(range(0, len(block_side_b.lines)))

            block_a_diff_lines = concerned_lines_in_normalized_block_a
            block_b_diff_lines = concerned_lines_in_normalized_block_b
            syntax_lexer = None

        hunk_pairs = align_hunk_pairs(
            cut_text_hunks_with_context(block_a_corpus_lines, block_a_diff_lines, context_length=5, merge=True),
            cut_text_hunks_with_context(block_b_corpus_lines, block_b_diff_lines, context_length=5, merge=True),
        )

        for block_a_hunk, block_b_hunk in hunk_pairs:
            if not block.is_paired():
                if block.side_a_name is None:
                    block_a_hunk = SplitDiffViewMessagePane("[dim]This block does not exist on side A.[/dim]")
                else:
                    block_b_hunk = SplitDiffViewMessagePane("[dim]This block does not exist on side B.[/dim]")
            elif not block_a_diff_lines:
                block_a_hunk = SplitDiffViewMessagePane(
                    "[yellow]Unable to map pcode lines to ActionScript source on this side.[/yellow]"
                )
            elif not block_b_diff_lines:
                block_b_hunk = SplitDiffViewMessagePane(
                    "[yellow]Unable to map pcode lines to ActionScript source on this side.[/yellow]"
                )

            diff_view = SplitDiffView.from_pair(
                block_a_hunk,
                block_b_hunk,
                left_highlighted_lines=block_a_diff_lines,
                right_highlighted_lines=block_b_diff_lines,
                syntax_lexer=syntax_lexer,
                word_wrap=True,
            )

            console.line()
            console.print(diff_view)
            console.line()
            line_count += diff_view.get_last_render_height() + 2

        context_first_block_diff_display = False


def display_summary(diffset: GfxDiffSet, sort_order: DiffSortOrder):
    console.print(
        f"Summary: "
        f"[yellow]{len(diffset.get_scripts_with_differing_blocks())} scripts modified[/yellow], "
        f"[red]{len(diffset.unmatched_a_scripts)} scripts deleted[/red], "
        f"[green]{len(diffset.unmatched_b_scripts)} scripts created[/green]"
    )

    changed_count = diffset.get_modified_block_count()
    deleted_count = diffset.get_unmatched_block_side_a_count()
    created_count = diffset.get_unmatched_block_side_b_count()
    changed_lines_total = diffset.get_modified_block_line_count()

    console.print(
        f"➥  Within modified scripts: "
        f"[yellow]{changed_count} blocks modified[/yellow], "
        f"[red]{deleted_count} blocks deleted[/red], "
        f"[green]{created_count} blocks created[/green] "
        f"({changed_lines_total} changed lines)\n"
    )

    diff_table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, header_style=None)
    diff_table.add_column("Script block relative path")
    diff_table.add_column("State")
    diff_table.add_column("Lines changed (baseline)", justify="right")
    diff_table.add_column("(+ label/register alignment)", justify="right")

    diff_table.add_section()

    unfold_diff_tree_in_table(diffset.to_tree(), diff_table, sort_order=sort_order)

    console.print(diff_table)


def command(
    file_a: Annotated[Path, typer.Argument(help="The left (A) file of the comparison.")],
    file_b: Annotated[Path, typer.Argument(help="The right (B) file of the comparison.")],
    ffdec_path: Annotated[
        Path | None,
        typer.Option("--ffdec", help="Path to the ffdec binary. Only required if it is not in the system PATH."),
    ] = None,
    workspace_root_dir: Annotated[
        Path | None,
        typer.Option(
            "--workspace-root",
            help="Directory where intermediate files will be written. If omitted, a temporary directory is used.",
        ),
    ] = None,
    use_extraction_cache: Annotated[
        bool,
        typer.Option(
            "--cache-extraction/--no-extraction-cache",
            help="Use extraction cache (default). Disable to force re-extraction.",
        ),
    ] = True,
    use_normalization_cache: Annotated[
        bool,
        typer.Option(
            "--cache-normalization/--no-normalization-cache",
            help="Enable to reuse cached normalized blocks. Disable to force re-normalization.",
        ),
    ] = False,
    show_summary_only: Annotated[
        bool, typer.Option("--summary-only", help="Only show a summary, not detailed file differences.")
    ] = False,
    diff_format: Annotated[
        Literal["actionscript", "pcode"], typer.Option("--format", help="Set the format for detailed diff.")
    ] = "actionscript",
    truncate_detailed_diff: Annotated[
        int,
        typer.Option(
            "--details-truncate",
            min=0,
            help="Truncate display of diff details after N lines. 0 = unlimited.",
        ),
    ] = 512,
    sort_order: Annotated[
        DiffSortOrder,
        typer.Option(
            "--sort",
            help="Control sort order for diffs. 'natural' preserves the original order of blocks within each script. 'changes_desc' shows most modified blocks first, 'changes_asc' does the opposite.",
        ),
    ] = DiffSortOrder.CHANGES_DESC,
):
    """
    Compare scripts between two GFx files to surface meaningful changes through normalization.
    """
    file_a = file_a.resolve()
    file_b = file_b.resolve()

    if not file_a.is_file():
        print_error(f"Invalid input: {escape(str(file_a))} is not a file.")
        raise typer.Exit(code=1)

    if not file_b.is_file():
        print_error(f"Invalid input: {escape(str(file_b))} is not a file.")
        raise typer.Exit(code=1)

    if workspace_root_dir is not None:
        workspace_root_dir = workspace_root_dir.resolve()

        if not workspace_root_dir.is_dir():
            print_error(f"Invalid input: {escape(str(workspace_root_dir))} does not exist or is not a directory.")
            raise typer.Exit(code=1)

        workspace_a = Workspace(workspace_root_dir / temp_workspace_name_for_file(file_a))
        workspace_b = Workspace(workspace_root_dir / temp_workspace_name_for_file(file_b))
    else:
        workspace_a = Workspace.create_as_temporary_directory(file_a)
        workspace_b = Workspace.create_as_temporary_directory(file_b)

    try:
        ffdec_path = resolve_ffdec(ffdec_path)
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1)

    console.print(f"[bold yellow]File A:[/bold yellow] {escape(str(file_a))}")
    console.print(f"[bold yellow]File B:[/bold yellow] {escape(str(file_b))}")
    console.print(f"[bold yellow]Using ffdec:[/bold yellow] {escape(str(ffdec_path))}")

    # ================================================================
    # Step 1: extract contents from both files.
    # For that we use "JPEXS Free Flash Decompiler" aka ffdec.

    console.line()
    console.print("[cyan]» 1: Extraction of GFX scripts as p-code[/cyan]", highlight=False)
    console.line()

    extract_gfx_file(ffdec_path, file_a, workspace_a, use_extraction_cache)
    extract_gfx_file(ffdec_path, file_b, workspace_b, use_extraction_cache)

    # ================================================================
    # Step 2: perform a naive diff between the two directory trees.

    console.line()
    console.print("[cyan]» 2: Searching for file differences[/cyan]", highlight=False)
    console.line()

    common, only_in_a, only_in_b = diff_file_trees_basic(
        workspace_a.extraction_path("scripts"), workspace_b.extraction_path("scripts"), "**/*.pcode"
    )

    common_path_scripts: set[Path] = {p.with_suffix("") for p in common}
    unmatched_a_scripts: set[Path] = {p.with_suffix("") for p in only_in_a}
    unmatched_b_scripts: set[Path] = {p.with_suffix("") for p in only_in_b}

    if not common_path_scripts and not unmatched_a_scripts and not unmatched_b_scripts:
        console.print("[green]Both files are identical.[/green]")
        return

    if unmatched_a_scripts:
        console.print(f"Scripts only present in {escape(str(file_a))}:")
        for path in sorted(unmatched_a_scripts):
            console.print(format_script_path(path))
        console.print()

    if unmatched_b_scripts:
        console.print(f"Scripts only present in {escape(str(file_b))}:")
        for path in sorted(unmatched_b_scripts):
            console.print(format_script_path(path))
        console.print()

    if common_path_scripts:
        console.print("Common scripts that differ:")
        for path in sorted(common_path_scripts):
            console.print(format_script_path(path))

    # ================================================================
    # Step 3: normalize the differing scripts (common and unmatched), to remove the noise in p-codes due to
    # decompilation, and to highlight the real logical differences. The normalization is done at a "block level".
    # Files are split into blocks (top level scope, functions).

    console.line()
    console.print("[cyan]» 3: Normalizing differing scripts into p-code blocks[/cyan]", highlight=False)
    console.line()

    normalized_script_blocks_a = normalize_scripts(
        file_a, workspace_a, common_path_scripts | unmatched_a_scripts, use_normalization_cache
    )

    console.line()

    normalized_script_blocks_b = normalize_scripts(
        file_b, workspace_b, common_path_scripts | unmatched_b_scripts, use_normalization_cache
    )

    # ================================================================
    # Step 4: compare normalized p-code blocks to spot the real differences.

    console.line()
    console.print("[cyan]» 4: Comparison of normalized code[/cyan]", highlight=False)
    console.line()

    diffset = diff_normalized_script_trees(
        common_path_scripts | unmatched_a_scripts,
        common_path_scripts | unmatched_b_scripts,
        workspace_a.normalization_dir(),
        workspace_b.normalization_dir(),
    )

    # Reassign original positions to script block diffs.
    for script in diffset.get_differing_scripts():
        if not script.is_paired():
            continue

        block_order_a = {b.name: i for i, b in enumerate(normalized_script_blocks_a[script.side_a_path])}
        block_order_b = {b.name: i for i, b in enumerate(normalized_script_blocks_b[script.side_b_path])}

        for block in diffset.paired_scripts_block_diffs[script].get_blocks():
            if block.side_a_name is not None:  # side A has priority
                block.position = block_order_a[block.side_a_name]
            elif block.side_b_name is not None:
                block.position = block_order_b[block.side_b_name]

    # Refine the final difference score on block-level using more noise-reduction tweaks.
    refine_block_diffs(diffset, workspace_a.normalization_dir(), workspace_b.normalization_dir())

    if diffset.is_empty():
        console.print(
            "[green]Normalized trees are identical. The difference might be decompilation noise only.[/green]"
        )
        return

    if not show_summary_only:
        if diff_format == "actionscript":
            display_detailed_diff_in_actionscript(
                workspace_a,
                normalized_script_blocks_a,
                workspace_b,
                normalized_script_blocks_b,
                diffset,
                sort_order=sort_order,
                max_lines=truncate_detailed_diff,
            )
        elif diff_format == "pcode":
            display_detailed_diff_in_pcode(diffset, sort_order=sort_order, max_lines=truncate_detailed_diff)

    console.line()
    display_summary(diffset, sort_order)
