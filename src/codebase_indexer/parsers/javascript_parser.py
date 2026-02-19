"""
parsers/javascript_parser.py
=============================
JavaScript / TypeScript / JSX / TSX parser using regex heuristics.

Why regex and not tree-sitter?
  tree-sitter requires a compiled native extension per language.  For a
  production system we recommend installing tree-sitter, but for zero-
  dependency operation this parser uses carefully crafted regular expressions
  that handle the most common patterns (functions, classes, arrow functions,
  React components).

Patterns recognised
-------------------
  function foo(...)         → FUNCTION
  const foo = (...) =>      → FUNCTION
  class Foo                 → CLASS
  export default function   → FUNCTION
  export const foo = () =>  → FUNCTION
  // JSDoc comments         → captured as docstring

Limitations
-----------
- Nested functions are NOT extracted (only top-level + class methods)
- Template literals containing code are not parsed
- Decorators (TypeScript) are not captured
"""

from __future__ import annotations

import re
from typing import Optional

from ..models.chunk import ChunkKind, Language
from ..utils.logging import get_logger
from .base import BaseParser, ParsedSymbol

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches: function foo(...) {   /   export function foo(...) {
#          async function foo(...)
_FUNC_DEF = re.compile(
    r"^(?:export\s+)?(?:async\s+)?function\s+\*?(\w+)\s*\(",
    re.MULTILINE,
)

# Matches: const foo = (...) => {   /   const foo = async (...) =>
#          export const foo = () =>
_ARROW_FUNC = re.compile(
    r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(",
    re.MULTILINE,
)

# Matches: class Foo {   /   export class Foo extends Bar {
_CLASS_DEF = re.compile(
    r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)",
    re.MULTILINE,
)

# Matches import statements
_IMPORT_STMT = re.compile(
    r"^(?:import\s+|const\s+\w+\s*=\s*require\()",
    re.MULTILINE,
)

# JSDoc: /** ... */
_JSDOC = re.compile(r"/\*\*[\s\S]*?\*/", re.MULTILINE)


def _find_block_end(lines: list[str], start_idx: int) -> int:
    """
    Find the closing brace of a block starting at `start_idx`.

    Uses a simple brace counter to track nesting depth.  Returns the
    0-based index of the line containing the matching `}`.
    """
    depth = 0
    for i in range(start_idx, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0 and i > start_idx:
            return i
    return len(lines) - 1


class JavaScriptParser(BaseParser):
    """Regex-based parser for JS / TS / JSX / TSX."""

    language = Language.JAVASCRIPT

    def parse(self, source: str, rel_path: str) -> list[ParsedSymbol]:
        lines = source.splitlines()
        symbols: list[ParsedSymbol] = []

        # Build a map: line number (1-based) → JSDoc comment preceding it
        jsdoc_map = self._build_jsdoc_map(source)

        # Extract import block
        imp = self.extract_imports(source)
        if imp:
            symbols.append(imp)

        # Classes
        for m in _CLASS_DEF.finditer(source):
            start_line = source[:m.start()].count("\n") + 1
            start_idx = start_line - 1
            end_idx = _find_block_end(lines, start_idx)
            end_line = end_idx + 1
            text = "\n".join(lines[start_idx:end_line])

            sym = ParsedSymbol(
                kind=ChunkKind.CLASS,
                name=m.group(1),
                start_line=start_line,
                end_line=end_line,
                text=text,
                docstring=jsdoc_map.get(start_line),
                signature=lines[start_idx].strip(),
            )
            symbols.append(sym)

        # Named functions
        for m in _FUNC_DEF.finditer(source):
            start_line = source[:m.start()].count("\n") + 1
            start_idx = start_line - 1
            end_idx = _find_block_end(lines, start_idx)
            end_line = end_idx + 1
            text = "\n".join(lines[start_idx:end_line])

            symbols.append(ParsedSymbol(
                kind=ChunkKind.FUNCTION,
                name=m.group(1),
                start_line=start_line,
                end_line=end_line,
                text=text,
                docstring=jsdoc_map.get(start_line),
                signature=lines[start_idx].strip(),
            ))

        # Arrow functions (const foo = () => {...})
        for m in _ARROW_FUNC.finditer(source):
            start_line = source[:m.start()].count("\n") + 1
            start_idx = start_line - 1
            end_idx = _find_block_end(lines, start_idx)
            end_line = end_idx + 1
            text = "\n".join(lines[start_idx:end_line])

            symbols.append(ParsedSymbol(
                kind=ChunkKind.FUNCTION,
                name=m.group(1),
                start_line=start_line,
                end_line=end_line,
                text=text,
                docstring=jsdoc_map.get(start_line),
                signature=lines[start_idx].strip(),
            ))

        return symbols

    def _build_jsdoc_map(self, source: str) -> dict[int, str]:
        """
        Return a mapping of {line_number → jsdoc_text} where line_number is
        the line immediately following the JSDoc comment.
        """
        result: dict[int, str] = {}
        for m in _JSDOC.finditer(source):
            end_line = source[:m.end()].count("\n") + 2  # line after the comment
            result[end_line] = m.group(0)
        return result

    def extract_imports(self, source: str) -> Optional[ParsedSymbol]:
        lines = source.splitlines()
        import_line_nums: list[int] = []
        for i, line in enumerate(lines, 1):
            if _IMPORT_STMT.match(line.strip()):
                import_line_nums.append(i)
            elif import_line_nums and line.strip() and not _IMPORT_STMT.match(line.strip()):
                break  # stop at first non-import line after imports started

        if not import_line_nums:
            return None

        start = import_line_nums[0]
        end = import_line_nums[-1]
        text = "\n".join(lines[start - 1:end])
        return ParsedSymbol(
            kind=ChunkKind.IMPORT,
            name="__imports__",
            start_line=start,
            end_line=end,
            text=text,
        )
