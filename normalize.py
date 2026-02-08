#!/usr/bin/env python3

import argparse
from pathlib import Path
from lib.avm1_pcode_normalization import normalize_file
from lib.util import AnsiColor, print_error

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_pcode", type=Path)
    ap.add_argument("output_dir", type=Path)
    args = ap.parse_args()

    input_pcode = args.input_pcode.resolve()

    if not input_pcode.is_file():
        print_error(f"Invalid input: {input_pcode} does not exist or is not a file.")
        return 1

    output_dir = args.output_dir.resolve()

    stats = normalize_file(input_pcode, output_dir)

    print(
        f"{input_pcode.name}: split into {stats.total_blocks} blocks",
        f"({stats.named_blocks} named, {stats.anonymous_blocks} anonymous, {stats.toplevel_blocks} top-level)"
    )

    print(f"{AnsiColor.GREEN}Normalization complete.{AnsiColor.RESET}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
