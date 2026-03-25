from __future__ import annotations
from typing import Annotated
from pathlib import Path
from rich.rule import Rule
import typer
from rich.console import Console
from rich.table import Table

from .avm1.pcode_parsing import parse_pcode_file
from .avm1.pcode_normalization import split_into_blocks, normalize_block
from .swd import build_pcode_to_actionscript_line_map, parse_swd_file
from .utils import print_error, read_file_lines
from .workspace import Workspace


def command(
    gfx_file: Annotated[Path, typer.Argument(help="Path to the GFx file.")],
    script_path: Annotated[
        str, typer.Argument(help="Internal script path, without a leading slash (e.g. 'frame_1/DoAction').")
    ],
    block_name: Annotated[str | None, typer.Argument(help="Block name to inspect.")] = None,
    workspace_dir: Annotated[
        Path | None,
        typer.Argument(
            help="Workspace directory to extract and analyze the contents of the GFx file. If omitted, a temporary directory is automatically inferred based on the source file."
        ),
    ] = None,
    normalized: Annotated[
        bool,
        typer.Option("--normalized", help="Show normalized p-code instead of raw."),
    ] = False,
):
    """
    Inspect the sourcemap for a GFx file (and a specific script and p-code block),
    showing the correspondence between p-code lines and their decompiled ActionScript source lines.
    """
    console = Console()

    gfx_file = gfx_file.resolve()

    if not gfx_file.is_file():
        print_error(f"Invalid input: {gfx_file} is not a file.")
        raise typer.Exit(code=1)

    if workspace_dir is None:
        workspace = Workspace.create_as_temporary_directory(gfx_file)
    else:
        if not workspace_dir.is_dir():
            print_error(f"Workspace directory not found: {workspace_dir}. Run 'kcd-gfx extract' first.")
            raise typer.Exit(code=1)

        workspace = Workspace(workspace_dir)

    script_file = workspace.extraction_path(f"scripts/{script_path}.pcode")

    if not script_file.exists():
        print_error(f"Script {script_path!r} was not found within extracted GFx files.")
        raise typer.Exit(code=1)

    pcode_file = parse_pcode_file(script_file)
    blocks = split_into_blocks(pcode_file)

    if block_name is None:
        console.print("Available blocks:")
        for b in blocks:
            console.print(f"  {b.name}")
        raise typer.Exit(code=0)

    block = next((b for b in blocks if b.name == block_name), None)

    if block is None:
        print_error(f"Block {block_name!r} not found in script {script_path!r}.")
        print_error(f"Available blocks: {', '.join(b.name for b in blocks if b.name is not None)}")
        raise typer.Exit(code=1)

    if normalized:
        block = normalize_block(block)

    try:
        swd_pcode = parse_swd_file(workspace.find_debug_pcode_swd_file())
        swd_actionscript = parse_swd_file(workspace.find_debug_actionscript_swd_file())
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1)

    pcode_to_as_line_map = build_pcode_to_actionscript_line_map(swd_pcode, swd_actionscript, {script_path})

    if script_path not in pcode_to_as_line_map:
        print_error(f"Script {script_path!r} not found in SWD file.")
        raise typer.Exit(code=1)

    script_pcode_to_as = pcode_to_as_line_map[script_path]

    actionscript_file = workspace.extraction_path(f"scripts/{script_path}.as")

    if not actionscript_file.is_file():
        print_error(f"ActionScript file not found: {actionscript_file}")
        raise typer.Exit(code=1)

    actionscript_lines = read_file_lines(actionscript_file)

    script_title = f"[bold cyan]{script_path}[/bold cyan]"
    block_title = f"[bright_yellow]❖[/bright_yellow] {block_name}"

    console.print(
        Rule(
            f"[dim white]────[/dim white] {script_title} [dim white]──[/dim white] {block_title}",
            align="left",
            style="dim white",
        )
    )

    console.line()

    table = Table(box=None, show_edge=False, pad_edge=False, show_header=False, width=console.width)
    table.add_column("", justify="right", style="dim")
    table.add_column("", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("", justify="right", style="dim")
    table.add_column("", ratio=1, no_wrap=True, overflow="ellipsis")

    table.add_row(style="on #17171a")

    last_known_as_line: int | None = None

    for pcode_line in block.lines:
        for src_line in pcode_line.source_lines:
            as_line = script_pcode_to_as.get(src_line)
            is_direct = as_line is not None

            if is_direct:
                last_known_as_line = as_line
            else:
                as_line = last_known_as_line

            as_text = (
                actionscript_lines[as_line] if as_line is not None and as_line <= len(actionscript_lines) else ""
            ).strip()

            if not is_direct:
                as_text = f"[dim]{as_text}[/dim]"

            as_line = as_line if as_line is not None else "~"

            table.add_row(f"{src_line:>6}", pcode_line.render(), f"{as_line:>6}", as_text, style="on #17171a")

    table.add_row(style="on #17171a")
    console.print(table)
