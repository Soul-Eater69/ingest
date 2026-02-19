"""
parsers/go_parser.py
====================
Regex-based Go parser.

Handles:
  func Foo(...)               → FUNCTION
  func (r *Receiver) Bar(...) → METHOD
  type Foo struct {           → CLASS (struct)
  type Foo interface {        → BLOCK (interface)
  import ( ... )              → IMPORT
"""

from __future__ import annotations

import re
from typing import Optional

from ..models.chunk import ChunkKind, Language
from ..utils.logging import get_logger
from .base import BaseParser, ParsedSymbol

logger = get_logger(__name__)

# func <name>(...) { or func (recv *T) <name>(...) {
_FUNC = re.compile(
    r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(",
    re.MULTILINE,
)

# type Foo struct {
_STRUCT = re.compile(r"^type\s+(\w+)\s+struct\s*\{", re.MULTILINE)

# type Foo interface {
_INTERFACE = re.compile(r"^type\s+(\w+)\s+interface\s*\{", re.MULTILINE)

# Go comment block (// ...) immediately before a declaration
_COMMENT_BLOCK = re.compile(r"((?:^//[^\n]*\n)+)", re.MULTILINE)


def _block_end(lines: list[str], start_idx: int) -> int:
    depth = 0
    for i in range(start_idx, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0 and i > start_idx:
            return i
    return len(lines) - 1


def _preceding_comment(source: str, start: int) -> Optional[str]:
    """Return the comment block immediately before position `start`."""
    before = source[:start]
    lines = before.splitlines()
    comment_lines: list[str] = []
    for line in reversed(lines):
        s = line.strip()
        if s.startswith("//"):
            comment_lines.insert(0, s[2:].strip())
        elif not s:
            continue
        else:
            break
    return "\n".join(comment_lines) if comment_lines else None


class GoParser(BaseParser):
    language = Language.GO

    def parse(self, source: str, rel_path: str) -> list[ParsedSymbol]:
        lines = source.splitlines()
        symbols: list[ParsedSymbol] = []

        imp = self.extract_imports(source)
        if imp:
            symbols.append(imp)

        for m in _FUNC.finditer(source):
            start_line = source[:m.start()].count("\n") + 1
            start_idx = start_line - 1
            end_line = _block_end(lines, start_idx) + 1
            text = "\n".join(lines[start_idx:end_line])
            doc = _preceding_comment(source, m.start())

            # Detect method vs function via receiver
            line_text = lines[start_idx]
            is_method = bool(re.match(r"^func\s+\(", line_text))

            symbols.append(ParsedSymbol(
                kind=ChunkKind.METHOD if is_method else ChunkKind.FUNCTION,
                name=m.group(1),
                start_line=start_line,
                end_line=end_line,
                text=text,
                docstring=doc,
                signature=line_text.strip(),
            ))

        for m in _STRUCT.finditer(source):
            start_line = source[:m.start()].count("\n") + 1
            start_idx = start_line - 1
            end_line = _block_end(lines, start_idx) + 1
            text = "\n".join(lines[start_idx:end_line])
            doc = _preceding_comment(source, m.start())

            symbols.append(ParsedSymbol(
                kind=ChunkKind.CLASS,
                name=m.group(1),
                start_line=start_line,
                end_line=end_line,
                text=text,
                docstring=doc,
                signature=lines[start_idx].strip(),
            ))

        for m in _INTERFACE.finditer(source):
            start_line = source[:m.start()].count("\n") + 1
            start_idx = start_line - 1
            end_line = _block_end(lines, start_idx) + 1
            text = "\n".join(lines[start_idx:end_line])
            doc = _preceding_comment(source, m.start())

            symbols.append(ParsedSymbol(
                kind=ChunkKind.BLOCK,
                name=m.group(1),
                start_line=start_line,
                end_line=end_line,
                text=text,
                docstring=doc,
                signature=lines[start_idx].strip(),
            ))

        return symbols

    def extract_imports(self, source: str) -> Optional[ParsedSymbol]:
        lines = source.splitlines()
        # Single import: import "fmt"
        # Block import: import ( ... )
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import"):
                start = i + 1
                if "(" in stripped:
                    # block import – find closing )
                    for j in range(i, len(lines)):
                        if ")" in lines[j]:
                            end = j + 1
                            text = "\n".join(lines[i:end])
                            return ParsedSymbol(
                                kind=ChunkKind.IMPORT,
                                name="__imports__",
                                start_line=start,
                                end_line=end,
                                text=text,
                            )
                else:
                    return ParsedSymbol(
                        kind=ChunkKind.IMPORT,
                        name="__imports__",
                        start_line=start,
                        end_line=start,
                        text=stripped,
                    )
        return None
