#!/usr/bin/env python3

from __future__ import annotations
from typing import Annotated, Callable, Iterable
import typer
from .gfx_diff import GfxScript, diff_normalized_script_trees
from .extraction import extract_gfx_contents, extraction_cache_key, resolve_ffdec
from .avm1_pcode_normalization import NormalizationStats, normalize_file
from .file_diff import diff_file_trees_basic
from .utils import AnsiColor, ensure_empty_dir, print_error, get_temp_dir, print_warning
from pathlib import Path
import shutil
import subprocess
from rich.console import Console, RenderableType
from rich.table import Table
from rich import box


def build_script_path_tree_rows(scripts: set[GfxScript]) -> list[tuple[str, GfxScript | None, str]]:
    """
    Render script paths as a directory/file tree.
    Return tuples:
        1. rendered tree row
        2. matched script path for this row, or None for intermediate nodes
        3. prefix to use for children rows under this node
    """
    tree: dict[str, dict] = {}
    segments_to_script: dict[tuple[str, ...], GfxScript] = {}

    for script in scripts:
        p = script.side_a_path or script.side_b_path
        assert p is not None

        segments = p.parts

        # Build a lookup table for later.
        segments_to_script[segments] = script

        # Create the tree structure as a dict, where keys are path segments.
        node = tree
        for segment in segments:
            node = node.setdefault(segment, {})

    def render_tree_node(
        tree_node: dict[str, dict],
        prefix: str = "",
        path_prefix_segments: tuple[str, ...] = (),
    ) -> list[tuple[str, GfxScript | None, str]]:
        rows: list[tuple[str, GfxScript | None, str]] = []
        children = sorted(tree_node.keys())  # sort paths in alphabetical order.

        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            path_segments = (*path_prefix_segments, child)
            leaf_script = segments_to_script.get(path_segments)

            if leaf_script is None:
                child_text = f"{child}/"
            else:
                if leaf_script.was_renamed():
                    script_text = f"{leaf_script.side_a_path.name} => {leaf_script.side_b_path.name}"
                elif leaf_script.side_b_path is None:
                    script_text = leaf_script.side_a_path.name  # common not renamed or unmatched from side A
                else:
                    script_text = leaf_script.side_b_path.name  # unmatched from side B
                child_text = f"[bold cyan]{script_text}[/bold cyan]"

            if not path_prefix_segments:
                # Roots do not need a tree connector character.
                row_text = child_text
                child_prefix = "    "
            else:
                connector = "└── " if is_last else "├── "
                row_text = f"{prefix}{connector}{child_text}"
                child_prefix = prefix + ("    " if is_last else "│   ")

            rows.append((row_text, leaf_script, child_prefix))

            # Recursively render all tree nodes, depth-first.
            rows.extend(render_tree_node(tree_node[child], child_prefix, path_segments))

        return rows

    return render_tree_node(tree)


def unfold_script_tree_in_table(
    scripts: set[GfxScript],
    table: Table,
    get_block_rows: Callable[[GfxScript], Iterable[tuple[RenderableType | None, ...]]],
) -> None:
    """
    Append script paths and blocks as a tree to a Rich table.
    Script paths are sorted in alphabetical order.
    Append block rows to each leaf script using `get_block_rows`.
    """
    tree_rows = build_script_path_tree_rows(scripts)

    for row_text, script, leaf_prefix in tree_rows:
        if script is None:
            table.add_row(row_text, "", "")
            continue  # continue unfolding the tree until we reached a script

        if script.side_a_path is not None and script.side_b_path is not None:
            state = "[italic yellow]modified[/italic yellow]"
        elif script.side_b_path is None:
            state = "[italic red]deleted[/italic red]"  # unmatched on side A
        else:
            state = "[italic green]created[/italic green]"  # unmatched on side B

        table.add_row(row_text, state, "")

        for block_text, *block_attr in get_block_rows(script):
            block_text = f"{leaf_prefix}[bright_yellow]◈[/bright_yellow] {block_text}"
            table.add_row(block_text, *block_attr)


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
        f"➥ Within modified scripts: "
        f"[yellow]{changed_count} blocks modified[/yellow], "
        f"[red]{deleted_count} blocks deleted[/red], "
        f"[green]{created_count} blocks created[/green] "
        f"({changed_lines_total} changed lines)\n"
    )

    diff_table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, header_style=None)
    diff_table.add_column("Script block relative path")
    diff_table.add_column("State")
    diff_table.add_column("Lines changed", justify="right")

    diff_table.add_section()

    def _get_modified_block_rows(script: GfxScript):
        block_change_rows: list[tuple[str, int]] = []

        if script not in diffset.paired_scripts_block_diffs:
            return []

        for ch in diffset.paired_scripts_block_diffs[script].paired_blocks:
            if ch.changed == 0:
                continue  # ignore pure renames
            display_text = (
                f"{ch.side_a_name} [bright_yellow]=>[/bright_yellow] {ch.side_b_name}"
                if ch.was_renamed()
                else ch.side_a_name
            )
            block_change_rows.append((display_text, ch.changed))

        # Sort by largest changes first, then by name.
        block_change_rows.sort(key=lambda row: (-row[1], row[0]))

        for display_text, changed in block_change_rows:
            yield (display_text, "[italic yellow]modified[/italic yellow]", str(changed))

        # Then display unmatched blocks.
        unmatched_block_rows = []

        for block in diffset.paired_scripts_block_diffs[script].unmatched_a_blocks:
            unmatched_block_rows.append((block.side_a_name, "[italic red]deleted[/italic red]", "-"))

        for block in diffset.paired_scripts_block_diffs[script].unmatched_b_blocks:
            unmatched_block_rows.append((block.side_b_name, "[italic green]created[/italic green]", "-"))

        # Sort by block name.
        yield from sorted(unmatched_block_rows, key=lambda row: row[0])

    unfold_script_tree_in_table(diffset.get_differing_scripts(), diff_table, _get_modified_block_rows)

    console.print(diff_table)
