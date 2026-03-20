from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Literal, Self, TypeGuard
from .pcode_utils import extract_label_from_line


@dataclass(frozen=True, kw_only=True)
class PcodeOperand:
    type: Literal["symbol", "string", "numeric", "boolean"]
    value: str | bool

    def render(self) -> str:
        if self.type == "string":
            assert isinstance(self.value, str)
            return '"' + self.value + '"'

        if self.type == "boolean":
            assert isinstance(self.value, bool)
            return "true" if self.value else "false"

        return str(self.value)


@dataclass(frozen=True, kw_only=True)
class PcodeLine(ABC):
    source_lines: list[int]
    label: str | None = None

    def replace(self, **kwargs) -> Self:
        return replace(self, **kwargs)

    @abstractmethod
    def render(self) -> str: ...


@dataclass(frozen=True, kw_only=True)
class PcodeInstruction(PcodeLine):
    opcode: str
    operands: list[PcodeOperand] = field(default_factory=list)

    def is_function_definition(self) -> bool:
        return self.opcode in ["DefineFunction", "DefineFunction2"]

    def render(self) -> str:
        line = ""

        if self.label:
            line = self.label + ":"

        line += self.opcode

        if self.operands:
            line += " " + ", ".join([op.render() for op in self.operands])

        if self.is_function_definition():
            line += " {"

        return line


@dataclass(frozen=True, kw_only=True)
class PcodeStructural(PcodeLine):
    value: str

    def render(self) -> str:
        return (f"{self.label}:" if self.label else "") + self.value


@dataclass(frozen=True, kw_only=True)
class PcodeBlankLineWithLabel(PcodeLine):
    def __post_init__(self):
        if self.label is None or self.label.strip() == "":
            raise ValueError(f"Label cannot be None or blank in {self.__class__.__name__}.")

    def render(self) -> str:
        return self.label + ":"


@dataclass(frozen=True)
class PcodeBlock:
    """
    A self-contained sequence of AVM1 p-code lines.
    """

    lines: list[PcodeLine]
    name: str | None = None

    def render(self) -> str:
        """
        Transform a PcodeBlock instance back to text representation.
        """
        text_lines: list[str] = []

        for pcode_line in self.lines:
            text_lines.append(pcode_line.render())

        return "\n".join(text_lines)


def tokenize_line(line: str) -> list[tuple[int, str]]:
    """
    Split a line in a sequence of tokens.

    Backslash escaping is honored while scanning quoted text.
    Whitespace is ignored.

    Example:
        `label56:Push register1, "cagada, ahah", 0.0, 6 {`
    =>
        label56 | : | Push | register1 | , | "cagada, ahah" | 0.0 | 6 | {
    """
    tokens: list[tuple[int, str]] = []
    separators = [":", ",", "{", "}"]
    buffer = []  # characters encountered before a token separator
    buffer_start = 0
    quoting = False
    escaping = False

    for pos, char in enumerate(line):
        if escaping:
            buffer.append(char)
            escaping = False
            continue
        if char == "\\" and quoting:
            buffer.append(char)
            escaping = True
            continue
        if char == '"':
            buffer.append(char)
            quoting = not quoting
            continue
        if (char.isspace() or char in separators) and not quoting:
            # We are not inside a string, and we met a token separator (or a whitespace).
            token = "".join(buffer)
            if token:
                tokens.append((buffer_start, token))

            if char in separators:
                tokens.append((pos, char))

            buffer = []  # we just met a separator, so we reset the buffer
            buffer_start = pos + 1
            continue

        buffer.append(char)

    if token := "".join(buffer):
        tokens.append((buffer_start, token))

    return tokens


def parse_pcode_lines(lines: list[str]) -> PcodeBlock:
    pcode_lines: list[PcodeLine] = []
    numeric_literal_re = re.compile(r"\-?\d+(\.\d+)?\b")

    for i, line in enumerate(lines):
        if line.strip() == "":
            # Ignore blank lines
            continue

        labelless_line, label_def = extract_label_from_line(line)

        if label_def and labelless_line.strip() == "":
            pcode_lines.append(PcodeBlankLineWithLabel(source_lines=[i], label=label_def))
            continue

        if labelless_line.strip() == "}":
            # Very specific case of a non-instruction line: the function block delimiter '}'.
            pcode_lines.append(PcodeStructural(source_lines=[i], value="}", label=label_def))
            continue

        tokens = tokenize_line(labelless_line)
        opcode = tokens.pop(0)[1]
        operands = []

        for _, token in tokens:
            if token in [",", "{"]:
                # Ignore purely syntactic tokens.
                continue

            if token.startswith('"'):
                assert token.endswith('"')
                assert len(token) >= 2
                type = "string"
                token = token[1:-1]
            elif numeric_literal_re.fullmatch(token):
                type = "numeric"
            elif token.lower() in ["true", "false"]:
                type = "boolean"
                token = True if token.lower() == "true" else False
            else:
                type = "symbol"

            operands.append(PcodeOperand(type=type, value=token))

        pcode_lines.append(PcodeInstruction(source_lines=[i], opcode=opcode, operands=operands, label=label_def))

    return PcodeBlock(lines=pcode_lines)


def parse_pcode_text(text: str) -> PcodeBlock:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    return parse_pcode_lines(lines)


def parse_pcode_file(input_file: Path) -> PcodeBlock:
    """
    Read a text file, normalize line endings, and split into lines and parse them as p-code.
    """
    text = input_file.read_text(encoding="utf-8", errors="replace")
    return parse_pcode_text(text)


def is_pcode_instruction(pcode_line: PcodeLine | None) -> TypeGuard[PcodeInstruction]:
    return isinstance(pcode_line, PcodeInstruction)


def merge_pcode_lines_sources(*lines: PcodeLine) -> list[int]:
    """
    Merge source lines from multiple PcodeLine objects, without duplicates, and sorted.
    """
    return sorted({ln for line in lines for ln in line.source_lines})
