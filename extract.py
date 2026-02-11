#!/usr/bin/env python3

import argparse
from pathlib import Path
import shutil
import subprocess
from lib.util import AnsiColor, ensure_empty_dir, print_error, sha256_str


def read_arguments():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("input_file", type=Path)
    argument_parser.add_argument("--ffdec", type=Path)
    return argument_parser.parse_args()


def resolve_ffdec(arg: Path | None) -> Path:
    ffdec_path = arg

    if ffdec_path is None:
        # If nothing was provided as an argument, we try to auto-discover it (via PATH).
        found_path = shutil.which("ffdec-cli") or shutil.which("ffdec-cli.exe")
        if found_path:
            return Path(found_path)
        raise FileNotFoundError("Unable to automatically resolve the path to ffdec-cli.")
    else:
        # If a path was provided, we just need to validate it.
        ffdec_path = ffdec_path.resolve()
        if not ffdec_path.is_file():
            raise FileNotFoundError(f"The provided ffdec binary path ({ffdec_path}) does not exist or is not a file.")

    return ffdec_path


def extraction_cache_key(path: Path) -> str:
    st = path.stat()
    sig = f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    return sha256_str(sig)


def extract_gfx_contents(ffdec_bin_path: Path, file_path: Path, output_dir: Path):
    return subprocess.run(
        [str(ffdec_bin_path), "-format", "script:pcode", "-export", "script", str(output_dir), str(file_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )


def main() -> int:
    args = read_arguments()

    input_file = args.input_file.resolve()

    if not input_file.is_file():
        print_error(f"Invalid input: {input_file} does not exist or is not a file.")
        return 1

    script_dir = Path(__file__).resolve().parent
    temp_dir = script_dir / "temp"

    if not temp_dir.is_dir():
        print_error("Temp directory does not exist or is not a directory.")
        return 1

    try:
        ffdec_path = resolve_ffdec(args.ffdec)
    except FileNotFoundError as e:
        print_error(e)
        return 1

    print(f"Using ffdec at {ffdec_path}")

    input_file_hash = extraction_cache_key(input_file)
    output_dir = (temp_dir / f"{input_file.stem}_{input_file_hash}" / "raw").resolve()

    print(f"Extracting {input_file.name} contents in: {output_dir}")

    ensure_empty_dir(output_dir)

    try:
        extract_gfx_contents(ffdec_path, input_file, output_dir)
    except subprocess.CalledProcessError as e:
        print_error(f"ffdec-cli.exe failed with code {e.returncode}:")
        if e.stderr:
            print_error(e.stderr)
        return 1

    print(f"{AnsiColor.GREEN}Extraction complete.{AnsiColor.RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
