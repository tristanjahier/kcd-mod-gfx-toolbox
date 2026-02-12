# GFX toolbox for Kingdom Come: Deliverance modding

This repository contains a small Python CLI toolkit to compare two `.gfx` files by extracting their AVM1 p-code, normalizing decompiler noise, and surfacing the real script logic differences.

`.gfx` files are Scaleform GFx assets: compiled Adobe Flash/ActionScript content used to build game UIs (menus, HUD) in Kingdom Come: Deliverance and many other games. `.gfx` files are `.swf` files optimised for games.

## Requirements

Python 3.11+.

JPEXS Free Flash Decompiler, in particular the `ffdec` binary (`ffdec-cli.exe` on Windows). Download it here: https://github.com/jindrapetrik/jpexs-decompiler. Any version that supports:
```sh
ffdec -format script:pcode -export script output_dir myfile.gfx
```

## Usage

### Compare two `.gfx` files (main utility)

```sh
python diff.py a/path/to/file1.gfx a/path/to/file2.gfx --ffdec "/the/path/to/ffdec"
```

This script is intended for comparing two `.gfx` files that are mostly similar, such as a modded file and its vanilla game counterpart. It helps pinpoint the script-level changes introduced by the mod.

`--ffdec` is only required if the `ffdec` binary is not in your `PATH`.

The command proceeds in four steps:
1. Extract scripts from both files as p-code text.
2. Find different scripts between both files.
3. Split those scripts into logical blocks and normalize them.
4. Compare normalized blocks and report the most changed blocks (by line count).

Temporary files will be written in the `temp/` directory at the root of this repository.

### Extract scripts only

```sh
python extract.py a/path/to/file.gfx --ffdec "/the/path/to/ffdec"
```

Currently, extraction output is always written under the repository’s `temp/` directory.

### Normalize a `.pcode` file into blocks

```sh
python normalize.py a/path/to/MyScript.pcode a/path/to/output_dir
```

One file is written per normalized block at the root of the output directory.
