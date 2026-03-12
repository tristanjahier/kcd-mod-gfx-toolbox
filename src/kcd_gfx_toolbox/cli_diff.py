#!/usr/bin/env python3

from __future__ import annotations
from typing import Annotated, Literal, cast
import typer
from .gfx_diff import (
    GfxDiffSet,
    GfxDiffTreeNode,
    GfxDiffTreeNodeType,
    GfxScript,
    GfxScriptBlock,
    diff_normalized_script_trees,
    refine_block_diffs,
)
from .extraction import extract_gfx_contents, extraction_cache_key, resolve_ffdec
from .avm1.pcode_normalization import NormalizationStats, normalize_file
from .file_diff import diff_file_trees_basic
from .utils import AnsiColor, ensure_empty_dir, print_error, get_temp_dir, print_warning
from pathlib import Path
import shutil
import subprocess
from rich.console import Console
from rich.table import Table
from rich import box


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


def normalize_script(script_src: Path, output_dir: Path, read_cache: bool) -> NormalizationStats:
    """
    Perform normalization for a given script, or read the cached data if applicable.
    """
    if read_cache:
        try:
            return collect_normalization_stats_from_cache(output_dir)
        except FileNotFoundError:
            print_warning(f"Normalization cache missing: {output_dir}.")
            # Not a fatal error.

    ensure_empty_dir(output_dir)

    try:
        return normalize_file(script_src, output_dir)
    except Exception as e:
        print_error(f"Normalization failed: {script_src}")
        print_error(e)
        raise typer.Exit(code=1)


def collect_normalization_stats_from_cache(blocks_dir: Path) -> NormalizationStats:
    """
    Compute normalization stats from an existing normalized-blocks directory.
    """
    if not blocks_dir.is_dir():
        raise FileNotFoundError(f"Missing normalization cache directory: {blocks_dir}.")

    total_blocks = named_blocks = anonymous_blocks = toplevel_blocks = 0

    for block_file in blocks_dir.iterdir():
        if not block_file.is_file() or block_file.suffix.lower() != ".pcode":
            continue

        total_blocks += 1

        stem = block_file.stem
        first_underscore_idx = stem.find("_")
        block_name = stem[first_underscore_idx + 1 :] if first_underscore_idx != -1 else stem

        if block_name.startswith("__toplevel"):
            toplevel_blocks += 1
        elif block_name.startswith("__anonymous"):
            anonymous_blocks += 1
        else:
            named_blocks += 1

    if total_blocks == 0:
        raise FileNotFoundError(f"Normalization cache directory is empty: {blocks_dir}.")

    return NormalizationStats(
        total_blocks=total_blocks,
        named_blocks=named_blocks,
        anonymous_blocks=anonymous_blocks,
        toplevel_blocks=toplevel_blocks,
    )


def display_detailed_diff(
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
    truncate_detailed_diff: Annotated[
        int,
        typer.Option(
            "--details-truncate",
            min=0,
            help="Truncate display of diff details after N lines. 0 = unlimited.",
        ),
    ] = 256,
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

    temp_dir = get_temp_dir()

    if temp_dir.exists() and not temp_dir.is_dir():
        print_error(f"Temp path exists but is not a directory: {temp_dir}")
        raise typer.Exit(code=1)

    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        ffdec_path = resolve_ffdec(ffdec_path)
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1)

    print(f"{AnsiColor.LIGHT_YELLOW}File A:{AnsiColor.RESET} {file_a}")
    print(f"{AnsiColor.LIGHT_YELLOW}File B:{AnsiColor.RESET} {file_b}")
    print(
        f"{AnsiColor.LIGHT_YELLOW}Temp dir:{AnsiColor.RESET} \033]8;;{temp_dir.as_uri()}\033\\{temp_dir}\033]8;;\033\\"
    )
    print(f"{AnsiColor.LIGHT_YELLOW}Using ffdec:{AnsiColor.RESET} {ffdec_path}")

    # ================================================================
    # Step 1: extract contents from both files.
    # For that we use "JPEXS Free Flash Decompiler" aka ffdec.

    print(f"\n{AnsiColor.BLUE}» 1: Extraction of GFX scripts as p-code{AnsiColor.RESET}\n")

    # Extraction of file A.
    file_a_path_hash = extraction_cache_key(file_a)
    extraction_dir_a = (temp_dir / f"{file_a.stem}_{file_a_path_hash}" / "raw").resolve()
    print(f"{file_a} -> {extraction_dir_a}")

    if not use_extraction_cache or not extraction_dir_a.is_dir():
        try:
            shutil.rmtree(extraction_dir_a)
        except FileNotFoundError:
            pass

        extraction_dir_a.mkdir(parents=True, exist_ok=True)

        try:
            extract_gfx_contents(ffdec_path, file_a, extraction_dir_a)
        except subprocess.CalledProcessError as e:
            print_error(f"ffdec failed with code {e.returncode}:")
            if e.stderr:
                print_error(e.stderr)
            raise typer.Exit(code=1)
    else:
        print("Extraction directory already exists. Reusing.")

    # Extraction of file B.
    file_b_path_hash = extraction_cache_key(file_b)
    extraction_dir_b = (temp_dir / f"{file_b.stem}_{file_b_path_hash}" / "raw").resolve()
    print(f"{file_b} -> {extraction_dir_b}")

    if not use_extraction_cache or not extraction_dir_b.is_dir():
        try:
            shutil.rmtree(extraction_dir_b)
        except FileNotFoundError:
            pass

        extraction_dir_b.mkdir(parents=True, exist_ok=True)

        try:
            extract_gfx_contents(ffdec_path, file_b, extraction_dir_b)
        except subprocess.CalledProcessError as e:
            print_error(f"ffdec failed with code {e.returncode}:")
            if e.stderr:
                print_error(e.stderr)
            raise typer.Exit(code=1)
    else:
        print("Extraction directory already exists. Reusing.")

    # ================================================================
    # Step 2: perform a naive diff between the two directory trees.

    print(f"\n{AnsiColor.BLUE}» 2: Searching for file differences{AnsiColor.RESET}\n")

    common, only_in_a, only_in_b = diff_file_trees_basic(extraction_dir_a, extraction_dir_b)

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

    normalization_dir_a = (temp_dir / f"{file_a.stem}_{file_a_path_hash}" / "normalized").resolve()
    normalization_dir_b = (temp_dir / f"{file_b.stem}_{file_b_path_hash}" / "normalized").resolve()

    # We should only try to read the cache if:
    #   1. it is the expected behaviour for the command.
    #   2. normalization has already been cached for that file.
    should_read_cache_file_a = use_normalization_cache and normalization_dir_a.is_dir()
    should_read_cache_file_b = use_normalization_cache and normalization_dir_b.is_dir()

    normalization_dir_a.mkdir(parents=True, exist_ok=True)
    normalization_dir_b.mkdir(parents=True, exist_ok=True)

    print(f"\n{AnsiColor.BLUE}» 3: Normalizing differing scripts into p-code blocks{AnsiColor.RESET}\n")

    normalization_results_a: list[tuple[Path, NormalizationStats]] = []
    normalization_results_b: list[tuple[Path, NormalizationStats]] = []

    # Preserve tree structure and transform file "XXXX.pcode" into directory "XXXX/".

    for script_path in common_path_scripts | unmatched_a_scripts:
        full_path = (extraction_dir_a / script_path).with_suffix(".pcode")
        norm_stats = normalize_script(full_path, normalization_dir_a / script_path, should_read_cache_file_a)
        normalization_results_a.append((script_path, norm_stats))

    for script_path in common_path_scripts | unmatched_b_scripts:
        full_path = (extraction_dir_b / script_path).with_suffix(".pcode")
        norm_stats = normalize_script(full_path, normalization_dir_b / script_path, should_read_cache_file_b)
        normalization_results_b.append((script_path, norm_stats))

    print(f"{file_a}:")

    norm_table1 = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, show_header=False)
    norm_table1.add_column("p-code file")
    norm_table1.add_column("Blocks", justify="right")
    norm_table1.add_column("Named", justify="right")
    norm_table1.add_column("Anonymous", justify="right")
    norm_table1.add_column("Top-level", justify="right")

    for rel_path, stats in normalization_results_a:
        norm_table1.add_row(
            str(rel_path),
            f"{stats.total_blocks} blocks",
            f"{stats.named_blocks} named",
            f"{stats.anonymous_blocks} anonymous",
            f"{stats.toplevel_blocks} top-level",
        )

    console.print(norm_table1)

    print(f"\n{file_b}:")

    norm_table2 = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, show_header=False)
    norm_table2.add_column("p-code file")
    norm_table2.add_column("Blocks", justify="right")
    norm_table2.add_column("Named", justify="right")
    norm_table2.add_column("Anonymous", justify="right")
    norm_table2.add_column("Top-level", justify="right")

    for rel_path, stats in normalization_results_b:
        norm_table2.add_row(
            str(rel_path),
            f"{stats.total_blocks} blocks",
            f"{stats.named_blocks} named",
            f"{stats.anonymous_blocks} anonymous",
            f"{stats.toplevel_blocks} top-level",
        )

    console.print(norm_table2)

    # ================================================================
    # Step 4: compare normalized p-code blocks to spot the real differences.

    print(f"\n{AnsiColor.BLUE}» 4: Comparison of normalized code{AnsiColor.RESET}\n")

    diffset = diff_normalized_script_trees(
        common_path_scripts | unmatched_a_scripts,
        common_path_scripts | unmatched_b_scripts,
        normalization_dir_a,
        normalization_dir_b,
    )

    # Refine the final difference score on block-level using more noise-reduction tweaks.
    refine_block_diffs(diffset, normalization_dir_a, normalization_dir_b)

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
        display_detailed_diff(diffset, sort_order=sort_detailed_diff, max_lines=truncate_detailed_diff)
