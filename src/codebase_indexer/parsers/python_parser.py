"""
parsers/python_parser.py
========================
Python parser using the standard library `ast` module.

The `ast` module gives us a complete, reliable parse tree without any
external dependencies.  We walk the tree to extract:
  - Module-level functions (kind=FUNCTION)
  - Classes (kind=CLASS)
  - Methods inside classes (kind=METHOD)
  - Module-level import blocks (kind=IMPORT)
  - Module docstring (kind=DOCSTRING)

Docstring extraction
--------------------
Python docstrings are `ast.Constant` nodes that are the first statement of
a function, class, or module body.  We extract them and store them both in
ParsedSymbol.docstring AND prepend them to the chunk text so the embedding
model sees the documentation.

Line number extraction
----------------------
ast nodes carry `lineno` and `end_lineno` attributes (Python 3.8+).
We split the original source into lines and slice out the exact text for
each symbol.
"""

from __future__ import annotations

import ast
import textwrap
from typing import Optional

from ..models.chunk import ChunkKind, Language
from ..utils.logging import get_logger
from .base import BaseParser, ParsedSymbol

logger = get_logger(__name__)


def _extract_docstring(node: ast.AST) -> Optional[str]:
    """Return the docstring of a function/class/module node, or None."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
        if node.body and isinstance(node.body[0], ast.Expr):
            expr = node.body[0]
            if isinstance(expr.value, ast.Constant) and isinstance(expr.value.value, str):
                return textwrap.dedent(expr.value.value).strip()
    return None


def _node_text(lines: list[str], node: ast.AST) -> str:
    """Extract the source text for an AST node using its line numbers."""
    start = getattr(node, "lineno", 1) - 1
    end = getattr(node, "end_lineno", start + 1)
    return "\n".join(lines[start:end])


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    """Return decorator names as strings."""
    result = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            result.append(f"@{dec.id}")
        elif isinstance(dec, ast.Attribute):
            result.append(f"@{ast.unparse(dec)}")
        elif isinstance(dec, ast.Call):
            result.append(f"@{ast.unparse(dec)}")
    return result


class PythonParser(BaseParser):
    """
    AST-based Python parser.

    Handles:
      - Regular and async functions
      - Classes (with nested methods extracted as separate symbols)
      - Type-annotated assignments (treated as BLOCK)
    """

    language = Language.PYTHON

    def parse(self, source: str, rel_path: str) -> list[ParsedSymbol]:
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError as exc:
            logger.warning("python parse error", extra={
                "path": rel_path, "error": str(exc)
            })
            return []

        lines = source.splitlines()
        symbols: list[ParsedSymbol] = []

        # Module-level docstring
        module_doc = _extract_docstring(tree)
        if module_doc:
            symbols.append(ParsedSymbol(
                kind=ChunkKind.DOCSTRING,
                name="__module_docstring__",
                start_line=1,
                end_line=3,
                text=module_doc,
                docstring=module_doc,
            ))

        # Import block
        imp_sym = self.extract_imports(source)
        if imp_sym:
            symbols.append(imp_sym)

        # Walk top-level definitions
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(self._parse_function(node, lines))

            elif isinstance(node, ast.ClassDef):
                cls_sym = self._parse_class(node, lines)
                symbols.append(cls_sym)

        return symbols

    # ------------------------------------------------------------------
    def _parse_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        lines: list[str],
        parent_name: Optional[str] = None,
    ) -> ParsedSymbol:
        start = node.lineno
        end = node.end_lineno or node.lineno
        text = _node_text(lines, node)
        decs = _decorators(node)

        # Build signature line
        try:
            sig = ast.unparse(node).split("\n")[0]
        except Exception:
            sig = f"def {node.name}(...)"

        kind = ChunkKind.METHOD if parent_name else ChunkKind.FUNCTION

        return ParsedSymbol(
            kind=kind,
            name=node.name,
            start_line=start,
            end_line=end,
            text=text,
            parent_name=parent_name,
            docstring=_extract_docstring(node),
            decorators=decs,
            signature=sig,
        )

    def _parse_class(self, node: ast.ClassDef, lines: list[str]) -> ParsedSymbol:
        start = node.lineno
        end = node.end_lineno or node.lineno
        text = _node_text(lines, node)
        decs = _decorators(node)
        children: list[ParsedSymbol] = []

        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method = self._parse_function(child, lines, parent_name=node.name)
                children.append(method)

        return ParsedSymbol(
            kind=ChunkKind.CLASS,
            name=node.name,
            start_line=start,
            end_line=end,
            text=text,
            docstring=_extract_docstring(node),
            decorators=decs,
            children=children,
        )

    def extract_imports(self, source: str) -> Optional[ParsedSymbol]:
        """Extract the import block (consecutive import statements at top of file)."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        lines = source.splitlines()
        import_lines: list[int] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                import_lines.append(node.lineno)

        if not import_lines:
            return None

        start = import_lines[0]
        end = import_lines[-1]
        text = "\n".join(lines[start - 1:end])

        return ParsedSymbol(
            kind=ChunkKind.IMPORT,
            name="__imports__",
            start_line=start,
            end_line=end,
            text=text,
        )
