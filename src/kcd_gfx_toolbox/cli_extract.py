#!/usr/bin/env python3

from pathlib import Path
import subprocess
from typing import Annotated
import typer

from .extraction import extract_gfx_contents, resolve_ffdec
from .utils import AnsiColor, ensure_empty_dir, print_error
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
        print_error(f"Invalid input: {input_file} does not exist or is not a file.")
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

    print(f"Using ffdec at {ffdec_path}")

    print(f"Extracting {input_file.name} contents in: {output_dir}")

    ensure_empty_dir(output_dir)

    try:
        extract_gfx_contents(ffdec_path, input_file, output_dir)
    except subprocess.CalledProcessError as e:
        print_error(f"ffdec failed with code {e.returncode}:")
        if e.stderr:
            print_error(e.stderr)
        raise typer.Exit(code=1)

    print(f"{AnsiColor.GREEN}Extraction complete.{AnsiColor.RESET}")
