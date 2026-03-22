"""
SWD file parsing implementation was adapted from JPEXS' flashdebugger library.
https://github.com/jindrapetrik/flashdebugger
In particular, this file: src/com/jpexs/debugger/flash/SWD.java
"""

import struct
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SwdScript:
    module: int
    bitmap: int
    name: str
    text: str


@dataclass
class SwdOffset:
    module: int
    line: int
    offset: int


@dataclass
class SwdRegisters:
    offset: int
    registers: dict[int, str]  # {regindex -> name}


@dataclass
class SwdFile:
    scripts: list[SwdScript]
    offsets: list[SwdOffset]
    registers: list[SwdRegisters]

    def to_json(self) -> str:
        """
        Transform a SWD object into a JSON document. Useful for manual debug.
        """
        return json.dumps(
            {
                "scripts": [
                    {"module": s.module, "bitmap": s.bitmap, "name": s.name, "text": s.text} for s in self.scripts
                ],
                "offsets": [{"module": o.module, "line": o.line, "offset": o.offset} for o in self.offsets],
                "registers": [{"offset": r.offset, "registers": r.registers} for r in self.registers],
            },
            indent=4,
        )


def _read_ui8(data: bytes, pos: int) -> tuple[int, int]:
    return data[pos], pos + 1


def _read_ui32(data: bytes, pos: int) -> tuple[int, int]:
    (val,) = struct.unpack_from("<I", data, pos)
    return val, pos + 4


def _read_string(data: bytes, pos: int) -> tuple[str, int]:
    end = data.index(b"\x00", pos)
    return data[pos:end].decode("utf-8"), end + 1


def parse_swd_file(path: Path) -> SwdFile:
    """
    Parse a binary SWD file into a structured SwdFile object.
    """
    data = path.read_bytes()
    pos = 0

    # Header
    assert data[0:3] == b"FWD", "Invalid SWD header"
    swf_version = data[3]
    assert swf_version >= 6, f"SWD version {swf_version} unsupported"
    pos = 4

    scripts: list[SwdScript] = []
    offsets: list[SwdOffset] = []
    registers: list[SwdRegisters] = []

    while pos < len(data):
        tag, pos = _read_ui32(data, pos)

        if tag == 0:  # DebugScript
            module, pos = _read_ui32(data, pos)
            bitmap, pos = _read_ui32(data, pos)
            name, pos = _read_string(data, pos)
            text, pos = _read_string(data, pos)
            scripts.append(SwdScript(module=module, bitmap=bitmap, name=name, text=text))

        elif tag == 1:  # DebugOffset
            module, pos = _read_ui32(data, pos)
            line, pos = _read_ui32(data, pos)
            offset, pos = _read_ui32(data, pos)
            offsets.append(SwdOffset(module=module, line=line, offset=offset))

        elif tag == 2:  # DebugBreakpoint — ignored
            pos += 4  # UI16 file + UI16 line

        elif tag == 3:  # DebugId — ignored
            pos += 16

        elif tag == 5:  # DebugRegisters
            offset, pos = _read_ui32(data, pos)
            size, pos = _read_ui8(data, pos)
            regs = {}
            for _ in range(size):
                regindex, pos = _read_ui8(data, pos)
                name, pos = _read_string(data, pos)
                regs[regindex] = name
            registers.append(SwdRegisters(offset=offset, registers=regs))

        else:
            raise ValueError(f"Unknown SWD tag {tag} at position {pos}.")

    return SwdFile(scripts, offsets, registers)


def build_pcode_to_actionscript_line_map(
    swd_pcode_file: SwdFile, swd_actionscript_file: SwdFile, script_filter: set[str] | None = None
) -> dict[str, dict[int, int | None]]:
    """
    Build a map from p-code lines to ActionScript lines for all scripts.
    Line numbers in the resulting map are 0-based (whereas they are 1-based in SWD).
    """
    # Map module IDs to script names (normalized as posix paths).
    module_id_to_script: dict[int, str] = {}

    for script in swd_actionscript_file.scripts:
        script_path = script.name.replace("\\", "/").removeprefix("main:").removeprefix("#PCODE ").lstrip("/")

        if script_filter is None or script_path in script_filter:
            module_id_to_script[script.module] = script_path

    # Build an offset to ActionScript line lookup.
    offset_to_as_line: dict[int, dict[int, int]] = {}

    for o in swd_actionscript_file.offsets:
        if o.module in module_id_to_script:
            offset_to_as_line.setdefault(o.module, {})[o.offset] = o.line

    # Map each p-code line to an ActionScript line via the shared offset.
    line_map: dict[str, dict[int, int | None]] = {}

    for o in swd_pcode_file.offsets:
        if o.module not in module_id_to_script:
            continue

        script_name = module_id_to_script[o.module]
        mapped_line = offset_to_as_line.get(o.module, {}).get(o.offset)
        # Make line numbers 0-based instead of 1-based.
        line_map.setdefault(script_name, {})[o.line - 1] = (mapped_line - 1) if mapped_line is not None else None

    return line_map


def propagate_mapped_lines_to_subsequent_unmapped_lines(line_map: dict[int, int | None]) -> dict[int, int | None]:
    """
    Propagate mapped lines to all subsequent unmapped lines, to make line mapping less sparse.
    It is a naive approach, but it works well.
    """
    extended_line_map: dict[int, int | None] = {}

    last_mapped_line = None

    for ln in line_map:
        mapped_line = line_map[ln]
        if mapped_line is not None:
            last_mapped_line = mapped_line

        extended_line_map[ln] = last_mapped_line

    return extended_line_map
