#!/usr/bin/env python3

from pathlib import Path
import subprocess
from typing import Annotated
from rich.markup import escape
import typer

from .extraction import extract_gfx_contents, resolve_ffdec
from .utils import console, ensure_empty_dir, print_error
from .workspace import Workspace


def command(
    input_file: Annotated[Path, typer.Argument(help="The GFx file to extract.")],
    output_dir: Annotated[
        Path | None,
        typer.Argument(
            help="Destination directory for extracted files. Any existing contents will be deleted. If omitted, a temporary directory is used."
        ),
    ] = None,
    ffdec_path: Annotated[
        Path | None,
        typer.Option("--ffdec", help="Path to the ffdec binary. Only required if it is not in the system PATH."),
    ] = None,
):
    """
    Extract scripts from a GFx file into a directory.
    """
    input_file = input_file.resolve()

    if not input_file.is_file():
        print_error(f"Invalid input: {escape(str(input_file))} does not exist or is not a file.")
        raise typer.Exit(code=1)

    if output_dir is None:
        output_dir = Workspace.create_as_temporary_directory(input_file).extraction_dir()
    else:
        output_dir = output_dir.resolve()

    try:
        ffdec_path = resolve_ffdec(ffdec_path)
    except FileNotFoundError as e:
        print_error(e)
        raise typer.Exit(code=1)

    console.print(f"Using ffdec at {escape(str(ffdec_path))}")

    console.print(f"Extracting {escape(input_file.name)} contents in: {escape(str(output_dir))}")

    ensure_empty_dir(output_dir)

    try:
        extract_gfx_contents(ffdec_path, input_file, output_dir)
    except subprocess.CalledProcessError as e:
        print_error(f"ffdec failed with code {e.returncode}:")
        if e.stderr:
            print_error(escape(str(e.stderr)))
        raise typer.Exit(code=1)

    console.print("[green]Extraction complete.[/green]")
