"""
parsers
=======
Language-specific AST parsers that extract structural metadata from source files.

Each parser implements the BaseParser interface and returns a list of
ParsedSymbol objects representing functions, classes, methods, etc.

Parser selection:
    The parser registry maps Language enum values to parser classes.
    If no parser exists for a language, GenericParser (line-based) is used.
"""

from .base import BaseParser, ParsedSymbol
from .python_parser import PythonParser
from .javascript_parser import JavaScriptParser
from .go_parser import GoParser
from .rust_parser import RustParser
from .generic_parser import GenericParser
from .registry import get_parser

__all__ = [
    "BaseParser", "ParsedSymbol",
    "PythonParser", "JavaScriptParser", "GoParser", "RustParser",
    "GenericParser", "get_parser",
]
