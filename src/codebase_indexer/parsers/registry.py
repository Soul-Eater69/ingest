"""
parsers/registry.py
===================
Maps Language enum values to parser instances.

Using a registry (dict) instead of isinstance chains means adding a new
language requires only two changes:
  1. Write a new parser class
  2. Add one entry here

All parser instances are singletons (created once at import time) because
parsers are stateless.
"""

from __future__ import annotations

from ..models.chunk import Language
from .base import BaseParser
from .python_parser import PythonParser
from .javascript_parser import JavaScriptParser
from .go_parser import GoParser
from .rust_parser import RustParser
from .generic_parser import GenericParser

# TypeScript / TSX / JSX share the JavaScript parser
_js_parser = JavaScriptParser()
_js_parser.language = Language.JAVASCRIPT  # default

_REGISTRY: dict[Language, BaseParser] = {
    Language.PYTHON:     PythonParser(),
    Language.JAVASCRIPT: JavaScriptParser(),
    Language.TYPESCRIPT: JavaScriptParser(),
    Language.TSX:        JavaScriptParser(),
    Language.JSX:        JavaScriptParser(),
    Language.GO:         GoParser(),
    Language.RUST:       RustParser(),
}

_GENERIC = GenericParser()


def get_parser(language: Language) -> BaseParser:
    """
    Return the appropriate parser for the given language.

    Falls back to GenericParser if no specific parser is registered.
    """
    return _REGISTRY.get(language, _GENERIC)
