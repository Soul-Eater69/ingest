"""
parsers/rust_parser.py
======================
Regex-based Rust parser.

Handles:
  fn foo(...)                 → FUNCTION
  pub fn foo(...)             → FUNCTION
  impl Foo { ... }            → CLASS (impl block)
  struct Foo { ... }          → CLASS
  trait Foo { ... }           → BLOCK
  /// doc comments            → captured as docstring
"""

from __future__ import annotations

import re
from typing import Optional

from ..models.chunk import ChunkKind, Language
from .base import BaseParser, ParsedSymbol

_FN   = re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?fn\s+(\w+)", re.MULTILINE)
_IMPL = re.compile(r"^(?:pub\s+)?impl(?:<[^>]+>)?\s+(\w+)", re.MULTILINE)
_STRUCT = re.compile(r"^(?:pub\s+)?struct\s+(\w+)", re.MULTILINE)
_TRAIT  = re.compile(r"^(?:pub\s+)?trait\s+(\w+)", re.MULTILINE)
_DOC_COMMENT = re.compile(r"((?:^///[^\n]*\n)+)", re.MULTILINE)


def _block_end(lines: list[str], start_idx: int) -> int:
    depth = 0
    for i in range(start_idx, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0 and i > start_idx:
            return i
    return len(lines) - 1


def _preceding_doc(source: str, start: int) -> Optional[str]:
    before = source[:start]
    lines = before.splitlines()
    doc_lines: list[str] = []
    for line in reversed(lines):
        s = line.strip()
        if s.startswith("///"):
            doc_lines.insert(0, s[3:].strip())
        elif not s or s.startswith("#["):
            continue
        else:
            break
    return "\n".join(doc_lines) if doc_lines else None


class RustParser(BaseParser):
    language = Language.RUST

    def parse(self, source: str, rel_path: str) -> list[ParsedSymbol]:
        lines = source.splitlines()
        symbols: list[ParsedSymbol] = []

        for pattern, kind in [(_FN, ChunkKind.FUNCTION), (_IMPL, ChunkKind.CLASS),
                               (_STRUCT, ChunkKind.CLASS), (_TRAIT, ChunkKind.BLOCK)]:
            for m in pattern.finditer(source):
                start_line = source[:m.start()].count("\n") + 1
                start_idx = start_line - 1
                line_text = lines[start_idx]

                # structs without braces end at semicolon
                if "{" not in line_text and kind == ChunkKind.CLASS:
                    end_line = start_line
                    text = line_text
                else:
                    end_line = _block_end(lines, start_idx) + 1
                    text = "\n".join(lines[start_idx:end_line])

                doc = _preceding_doc(source, m.start())
                symbols.append(ParsedSymbol(
                    kind=kind,
                    name=m.group(1),
                    start_line=start_line,
                    end_line=end_line,
                    text=text,
                    docstring=doc,
                    signature=line_text.strip(),
                ))

        return symbols
