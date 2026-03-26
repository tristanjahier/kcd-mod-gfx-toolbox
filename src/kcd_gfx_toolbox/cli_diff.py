#!/usr/bin/env python3

from __future__ import annotations
from itertools import zip_longest
import json
import re
from typing import Annotated, Literal, cast
import typer

from .workspace import Workspace
from .avm1.pcode_parsing import PcodeBlock, PcodeLine, parse_pcode_file
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
    AnsiColor,
    ensure_empty_dir,
    list_tree_files,
    print_error,
    print_warning,
    read_file_lines,
)
from pathlib import Path
import shutil
import subprocess
from rich.console import Console
from rich.table import Table
from rich import box
from rich.rule import Rule


def extract_gfx_file(ffdec_path: Path, gfx_file: Path, workspace: Workspace, read_cache: bool):
    extraction_dir = workspace.extraction_dir()
    print(f"{gfx_file} -> \033]8;;{extraction_dir.as_uri()}\033\\{extraction_dir}\033]8;;\033\\")

    if read_cache and workspace.extraction_dir_has_content():
        if workspace.extraction_dir_has_valid_contents():
            print("Extracted content already present in the target directory. Skipping.")
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
            print_error(e.stderr)
        raise typer.Exit(code=1)


def read_cached_normalized_blocks(cache_dir: Path) -> NormalizationResult:
    """
    Compute normalization stats from an existing normalized-blocks directory.
    """
    if not cache_dir.is_dir():
        raise FileNotFoundError(f"Missing normalization cache directory: {cache_dir}.")

    pcode_blocks: list[PcodeBlock] = []
    total_blocks = named_blocks = anonymous_blocks = toplevel_blocks = 0

    for block_file in sorted(list_tree_files(cache_dir, glob="*.pcode")):
        block_file = (cache_dir / block_file).resolve()

        total_blocks += 1

        block_name = re.sub(r"^\d+_", "", block_file.stem)

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
                norm_stats = read_cached_normalized_blocks(normalized_script_dir)
            except FileNotFoundError:
                print_warning(f"Normalization cache missing: {normalized_script_dir}.")  # Not fatal

        if norm_stats is None:
            ensure_empty_dir(normalized_script_dir)

            try:
                norm_stats = normalize_file(raw_script_path, normalized_script_dir)
            except Exception as e:
                print_error(f"Normalization failed: {raw_script_path}")
                print_error(e)
                raise typer.Exit(code=1)

        results.append((script_path, norm_stats))
        normalized_script_blocks[script_path] = norm_stats.blocks

    print(f"{gfx_file}:")

    result_table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, show_header=False)
    result_table.add_column("p-code file")
    result_table.add_column("Blocks", justify="right")
    result_table.add_column("Named", justify="right")
    result_table.add_column("Anonymous", justify="right")
    result_table.add_column("Top-level", justify="right")

    for rel_path, stats in results:
        result_table.add_row(
            str(rel_path),
            f"{stats.total_blocks} blocks",
            f"{stats.named_blocks} named",
            f"{stats.anonymous_blocks} anonymous",
            f"{stats.toplevel_blocks} top-level",
        )

    console = Console()
    console.print(result_table)

    return normalized_script_blocks


def unfold_diff_tree_in_table(tree: GfxDiffTreeNode, table: Table):
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
            return str(script.side_a_path or script.side_b_path)
        elif n.type == GfxDiffTreeNodeType.SCRIPT_BLOCK:
            block = cast(GfxScriptBlock, n.value)
            return (-block.refined_changed, str(block.side_a_name or block.side_b_name))
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
                if script.was_renamed():
                    node_text = f"{script.side_a_path.name} [white]→[/white] {script.side_b_path.name}"
                    node_state = "[yellow]modified[/yellow], [bright_blue]renamed[/bright_blue]"
                else:
                    node_text = script.side_a_path.name
                    node_state = "[yellow]modified[/yellow]"
            elif script.side_b_path is None:  # unmatched from side A
                node_text = script.side_a_path.name
                node_state = "[red]deleted[/red]"
            else:  # unmatched from side B
                node_text = script.side_b_path.name
                node_state = "[green]new[/green]"

            node_text = f"[bold cyan]{node_text}[/bold cyan]"

        elif node.type == GfxDiffTreeNodeType.SCRIPT_BLOCK:
            block = cast(GfxScriptBlock, node.value)
            if block.is_paired():
                if block.was_renamed():
                    node_text = f"{block.side_a_name} [bright_yellow]→[/bright_yellow] {block.side_b_name}"
                    node_state = "[yellow]modified[/yellow], [bright_blue]renamed[/bright_blue]"
                else:
                    node_text = block.side_a_name
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
                node_text = block.side_a_name
                node_state = "[red]deleted[/red]"
                node_change_values = ("-", "-")
            else:  # unmatched from side B
                node_text = block.side_b_name
                node_state = "[green]new[/green]"
                node_change_values = ("-", "-")

            node_text = f"[bright_yellow]❖[/bright_yellow] {node_text}"

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


def display_detailed_diff_in_pcode(
    diffset: GfxDiffSet, sort_order: Literal["default", "changes_desc", "changes_asc"] = "default", max_lines: int = 0
):
    """
    Display line-by-line differences for each modified script block.
    """
    console = Console()
    line_count = 0

    sorted_pairs: list[tuple[GfxScript, GfxScriptBlock]] = []

    scripts = sorted(diffset.get_scripts_with_differing_blocks(), key=lambda s: (s.side_a_path, s.side_b_path))

    for script in scripts:
        blocks = sorted(
            diffset.paired_scripts_block_diffs[script].paired_blocks,
            key=lambda b: (-b.refined_changed, b.side_a_name, b.side_b_name),
        )

        for block in blocks:
            if block.is_paired() and block.unified_diff:
                sorted_pairs.append((script, block))

    if sort_order == "changes_asc":
        sorted_pairs.sort(key=lambda p: (p[1].refined_changed, p[1].side_a_name, p[1].side_b_name))
    elif sort_order == "changes_desc":
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
                console.print(f"[bold]{line}[/bold]", highlight=False)
            elif line.startswith("+++"):
                line = f"+++ b/{script.side_b_path.as_posix()}:{block.side_b_name}"
                console.print(f"[bold]{line}[/bold]", highlight=False)
            elif line.startswith("@@"):
                console.print(f"[cyan]{line}[/cyan]", highlight=False)
            elif line.startswith("+"):
                console.print(f"[green]{line}[/green]", highlight=False)
            elif line.startswith("-"):
                console.print(f"[red]{line}[/red]", highlight=False)
            else:
                console.print(line, highlight=False)

            line_count += 1


def display_detailed_diff_in_actionscript(
    workspace_a: Workspace,
    normalized_script_blocks_a: dict[Path, list[PcodeBlock]],
    workspace_b: Workspace,
    normalized_script_blocks_b: dict[Path, list[PcodeBlock]],
    diffset: GfxDiffSet,
    sort_order: Literal["default", "changes_desc", "changes_asc"] = "default",
    max_lines: int = 0,
):
    console = Console()
    line_count = 0

    sorted_pairs: list[tuple[GfxScript, GfxScriptBlock]] = []

    scripts = sorted(diffset.get_scripts_with_differing_blocks(), key=lambda s: (s.side_a_path, s.side_b_path))

    for script in scripts:
        blocks = sorted(
            diffset.paired_scripts_block_diffs[script].paired_blocks,
            key=lambda b: (-b.refined_changed, b.side_a_name, b.side_b_name),
        )

        for block in blocks:
            if block.is_paired():
                sorted_pairs.append((script, block))

    if sort_order == "changes_asc":
        sorted_pairs.sort(key=lambda p: (p[1].refined_changed, p[1].side_a_name, p[1].side_b_name))
    elif sort_order == "changes_desc":
        sorted_pairs.sort(key=lambda p: (-p[1].refined_changed, p[1].side_a_name, p[1].side_b_name))

    # Cache for ActionScript sources.
    actionscript_cache: dict[Path, list[str]] = {}

    def _read_actionscript_source_lines(file: Path) -> list[str]:
        if file not in actionscript_cache:
            if not file.is_file():
                print_error(f"ActionScript file not found: {file}.")
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
        assert block.side_a_name is not None
        assert block.side_b_name is not None

        if max_lines != 0 and line_count >= max_lines:
            console.print(
                Rule(
                    f"[bold yellow]✀  Diff details truncated at {line_count} lines (soft limit is {max_lines}). Use [italic]--details-truncate=0[/italic] to remove this limit.[/bold yellow]",
                    align="center",
                    style="bold yellow",
                    characters="-",
                )
            )
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

        if block.changed == 0:
            continue

        if not context_first_block_diff_display:
            console.line()
            line_count += 1

        if script.was_renamed():
            script_title = f"[bold cyan]{script.side_a_path} [white]→[/white] {script.side_b_path}[/bold cyan]"
        else:
            script_title = f"[bold cyan]{script.side_a_path}[/bold cyan]"

        if block.was_renamed():
            block_title = f"[bright_yellow]❖[/bright_yellow] {block.side_a_name} [bright_yellow]→[/bright_yellow] {block.side_b_name}"
        else:
            block_title = f"[bright_yellow]❖[/bright_yellow] {block.side_a_name}"

        console.print(
            Rule(
                f"[dim white]────[/dim white] {script_title} [dim white]──[/dim white] {block_title}",
                align="left",
                style="dim white",
            )
        )
        line_count += 1

        block_name_side_a = re.sub(r"^\d+_", "", block.side_a_name)
        block_name_side_b = re.sub(r"^\d+_", "", block.side_b_name)
        block_side_a = next((b for b in script_a_blocks if b.name == block_name_side_a), None)
        block_side_b = next((b for b in script_b_blocks if b.name == block_name_side_b), None)
        assert block_side_a is not None
        assert block_side_b is not None

        # Mapped lines in ActionScript are sparse. Simple naive improvement: propagate mapped
        # lines to subsequent unmapped lines, within the boundaries of the block.
        block_a_first_line = min(block_side_a.lines[0].source_lines)
        block_a_last_line = max(block_side_a.lines[-1].source_lines)
        block_a_pcode_to_as = propagate_mapped_lines_to_subsequent_unmapped_lines(
            {k: v for k, v in script_a_pcode_to_as.items() if block_a_first_line <= k <= block_a_last_line}
        )

        block_b_first_line = min(block_side_b.lines[0].source_lines)
        block_b_last_line = max(block_side_b.lines[-1].source_lines)
        block_b_pcode_to_as = propagate_mapped_lines_to_subsequent_unmapped_lines(
            {k: v for k, v in script_b_pcode_to_as.items() if block_b_first_line <= k <= block_b_last_line}
        )

        concerned_lines_in_raw_block_a = []
        concerned_lines_in_raw_block_b = []

        for diff_span_a, diff_span_b in block.diff_spans:
            for pcode_line in block_side_a.lines[diff_span_a[0] : diff_span_a[1]]:
                concerned_lines_in_raw_block_a.extend(pcode_line.source_lines)

            for pcode_line in block_side_b.lines[diff_span_b[0] : diff_span_b[1]]:
                concerned_lines_in_raw_block_b.extend(pcode_line.source_lines)

        concerned_lines_in_raw_block_a = sorted(set(concerned_lines_in_raw_block_a))
        concerned_lines_in_raw_block_b = sorted(set(concerned_lines_in_raw_block_b))

        concerned_lines_in_as_source_a = []
        for ln in concerned_lines_in_raw_block_a:
            as_src_line = block_a_pcode_to_as.get(ln)
            if as_src_line is not None and as_src_line <= len(script_a_actionscript_lines):
                concerned_lines_in_as_source_a.append(as_src_line)

        concerned_lines_in_as_source_b = []
        for ln in concerned_lines_in_raw_block_b:
            as_src_line = block_b_pcode_to_as.get(ln)
            if as_src_line is not None and as_src_line <= len(script_b_actionscript_lines):
                concerned_lines_in_as_source_b.append(as_src_line)

        concerned_lines_in_as_source_a = set(concerned_lines_in_as_source_a)
        concerned_lines_in_as_source_b = set(concerned_lines_in_as_source_b)

        if not concerned_lines_in_as_source_a and not concerned_lines_in_as_source_b:
            console.line()
            console.print("[yellow]Unable to map pcode lines to ActionScript source for this block.[/yellow]")
            console.line()
            line_count += 3
            continue

        block_a_as_hunks = cut_text_hunks_with_context(
            script_a_actionscript_lines, concerned_lines_in_as_source_a, context_length=5, merge=True
        )
        block_b_as_hunks = cut_text_hunks_with_context(
            script_b_actionscript_lines, concerned_lines_in_as_source_b, context_length=5, merge=True
        )
        hunk_pairs = align_hunk_pairs(block_a_as_hunks, block_b_as_hunks)

        for block_a_hunk, block_b_hunk in hunk_pairs:
            table = Table(box=None, show_edge=False, pad_edge=False, show_header=False, width=console.width)
            table.add_column("", justify="right", style="dim")
            table.add_column("", ratio=1, no_wrap=True, overflow="ellipsis")
            table.add_column("", justify="right", style="dim")
            table.add_column("", ratio=1, no_wrap=True, overflow="ellipsis")

            table.add_row(style="on #17171a")
            line_count += 1

            line_pairs = zip_longest(block_a_hunk, block_b_hunk, fillvalue=(None, None))

            for (a_line, a_text), (b_line, b_text) in line_pairs:
                if a_line is not None:
                    a_text = (
                        f"[bold white]{a_text}[/bold white]"
                        if a_line in concerned_lines_in_as_source_a
                        else f"[dim white]{a_text}[/dim white]"
                    )
                else:
                    a_line = a_text = ""

                if b_line is not None:
                    b_text = (
                        f"[bold white]{b_text}[/bold white]"
                        if b_line in concerned_lines_in_as_source_b
                        else f"[dim white]{b_text}[/dim white]"
                    )
                else:
                    b_line = b_text = ""

                table.add_row(f"{a_line:>6}", a_text, f"{b_line:>6}", b_text, style="on #17171a")
                line_count += 1

            table.add_row(style="on #17171a")

            console.line()
            console.print(table)
            console.line()
            line_count += 3

        context_first_block_diff_display = False


def command(
    file_a: Annotated[Path, typer.Argument(help="The left (A) file of the comparison.")],
    file_b: Annotated[Path, typer.Argument(help="The right (B) file of the comparison.")],
    ffdec_path: Annotated[
        Path | None,
        typer.Option("--ffdec", help="Path to the ffdec binary. Only required if it is not in the system PATH."),
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
    show_detailed_diff: Annotated[
        bool, typer.Option("--detailed", help="Show line-by-line differences for each modified script block.")
    ] = False,
    detailed_diff_format: Annotated[
        Literal["as", "pcode"], typer.Option("--details-format", help="Set the format for detailed diff.")
    ] = "as",
    truncate_detailed_diff: Annotated[
        int,
        typer.Option(
            "--details-truncate",
            min=0,
            help="Truncate display of diff details after N lines. 0 = unlimited.",
        ),
    ] = 512,
    sort_detailed_diff: Annotated[
        Literal["default", "changes_desc", "changes_asc"],
        typer.Option(
            "--details-sort",
            help="Control sort order for detailed diffs. 'changes_desc' shows most modified blocks first, 'changes_asc' does the opposite. 'default' groups by script (sorted alphabetically), then orders blocks by most modified first.",
        ),
    ] = "default",
):
    """
    Compare scripts between two GFx files to surface meaningful changes through normalization.
    """
    console = Console()

    # ================================================================
    # Sanity checks

    file_a = file_a.resolve()
    file_b = file_b.resolve()

    if not file_a.is_file():
        print_error(f"Invalid input: {file_a} is not a file.")
        raise typer.Exit(code=1)

    if not file_b.is_file():
        print_error(f"Invalid input: {file_b} is not a file.")
        raise typer.Exit(code=1)

    workspace_a = Workspace.create_as_temporary_directory(file_a)
    workspace_b = Workspace.create_as_temporary_directory(file_b)

    try:
        ffdec_path = resolve_ffdec(ffdec_path)
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1)

    print(f"{AnsiColor.LIGHT_YELLOW}File A:{AnsiColor.RESET} {file_a}")
    print(f"{AnsiColor.LIGHT_YELLOW}File B:{AnsiColor.RESET} {file_b}")
    print(f"{AnsiColor.LIGHT_YELLOW}Using ffdec:{AnsiColor.RESET} {ffdec_path}")

    # ================================================================
    # Step 1: extract contents from both files.
    # For that we use "JPEXS Free Flash Decompiler" aka ffdec.

    print(f"\n{AnsiColor.BLUE}» 1: Extraction of GFX scripts as p-code{AnsiColor.RESET}\n")

    extract_gfx_file(ffdec_path, file_a, workspace_a, use_extraction_cache)
    extract_gfx_file(ffdec_path, file_b, workspace_b, use_extraction_cache)

    # ================================================================
    # Step 2: perform a naive diff between the two directory trees.

    print(f"\n{AnsiColor.BLUE}» 2: Searching for file differences{AnsiColor.RESET}\n")

    common, only_in_a, only_in_b = diff_file_trees_basic(
        workspace_a.extraction_path("scripts"), workspace_b.extraction_path("scripts"), "**/*.pcode"
    )

    common_path_scripts: set[Path] = {p.with_suffix("") for p in common}
    unmatched_a_scripts: set[Path] = {p.with_suffix("") for p in only_in_a}
    unmatched_b_scripts: set[Path] = {p.with_suffix("") for p in only_in_b}

    if not common_path_scripts and not unmatched_a_scripts and not unmatched_b_scripts:
        print(f"{AnsiColor.GREEN}Both files are identical.{AnsiColor.RESET}")
        return

    if unmatched_a_scripts:
        print(f"Scripts only present in {file_a}:")
        for path in sorted(unmatched_a_scripts):
            print(f"{path}")
        print()

    if unmatched_b_scripts:
        print(f"Scripts only present in {file_b}:")
        for path in sorted(unmatched_b_scripts):
            print(f"{path}")
        print()

    if common_path_scripts:
        print("Common scripts that differ:")
        for path in sorted(common_path_scripts):
            print(f"{path}")

    # ================================================================
    # Step 3: normalize the differing scripts (common and unmatched), to remove the noise in p-codes due to
    # decompilation, and to highlight the real logical differences. The normalization is done at a "block level".
    # Files are split into blocks (top level scope, functions).

    print(f"\n{AnsiColor.BLUE}» 3: Normalizing differing scripts into p-code blocks{AnsiColor.RESET}\n")

    normalized_script_blocks_a = normalize_scripts(
        file_a, workspace_a, common_path_scripts | unmatched_a_scripts, use_normalization_cache
    )

    console.line()

    normalized_script_blocks_b = normalize_scripts(
        file_b, workspace_b, common_path_scripts | unmatched_b_scripts, use_normalization_cache
    )

    # ================================================================
    # Step 4: compare normalized p-code blocks to spot the real differences.

    print(f"\n{AnsiColor.BLUE}» 4: Comparison of normalized code{AnsiColor.RESET}\n")

    diffset = diff_normalized_script_trees(
        common_path_scripts | unmatched_a_scripts,
        common_path_scripts | unmatched_b_scripts,
        workspace_a.normalization_dir(),
        workspace_b.normalization_dir(),
    )

    # Refine the final difference score on block-level using more noise-reduction tweaks.
    refine_block_diffs(diffset, workspace_a.normalization_dir(), workspace_b.normalization_dir())

    if diffset.is_empty():
        print(
            f"{AnsiColor.GREEN}Normalized trees are identical. The difference might be decompilation noise only.{AnsiColor.RESET}"
        )
        return

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

    unfold_diff_tree_in_table(diffset.to_tree(), diff_table)

    console.print(diff_table)

    if show_detailed_diff:
        console.line()

        if detailed_diff_format == "as":
            display_detailed_diff_in_actionscript(
                workspace_a,
                normalized_script_blocks_a,
                workspace_b,
                normalized_script_blocks_b,
                diffset,
                sort_order=sort_detailed_diff,
                max_lines=truncate_detailed_diff,
            )
        elif detailed_diff_format == "pcode":
            display_detailed_diff_in_pcode(diffset, sort_order=sort_detailed_diff, max_lines=truncate_detailed_diff)
