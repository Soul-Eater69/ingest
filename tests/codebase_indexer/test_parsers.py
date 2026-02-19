"""
tests/codebase_indexer/test_parsers.py
========================================
Unit tests for all language parsers.

Each parser test follows the same pattern:
  1. Provide a minimal but realistic source snippet.
  2. Call parser.parse().
  3. Assert on the number and types of extracted symbols.
  4. Assert on symbol names, line numbers, and docstrings.
"""

from __future__ import annotations

import pytest

from codebase_indexer.models.chunk import ChunkKind
from codebase_indexer.parsers.go_parser import GoParser
from codebase_indexer.parsers.javascript_parser import JavaScriptParser
from codebase_indexer.parsers.python_parser import PythonParser
from codebase_indexer.parsers.rust_parser import RustParser
from codebase_indexer.parsers.generic_parser import GenericParser


# ---------------------------------------------------------------------------
# Python parser
# ---------------------------------------------------------------------------

PYTHON_SOURCE = '''\
"""Module docstring."""

import os
import sys

def add(a: int, b: int) -> int:
    """Return the sum of a and b."""
    return a + b


class Calculator:
    """A simple calculator."""

    def multiply(self, x: float, y: float) -> float:
        """Return x * y."""
        return x * y

    def divide(self, x: float, y: float) -> float:
        """Return x / y. Raises ZeroDivisionError if y is zero."""
        return x / y
'''


class TestPythonParser:
    def setup_method(self) -> None:
        self.parser = PythonParser()

    def test_extracts_function(self) -> None:
        symbols = self.parser.parse(PYTHON_SOURCE, "calc.py")
        funcs = [s for s in symbols if s.kind == ChunkKind.FUNCTION]
        assert any(s.name == "add" for s in funcs), "should extract 'add' function"

    def test_extracts_class(self) -> None:
        symbols = self.parser.parse(PYTHON_SOURCE, "calc.py")
        classes = [s for s in symbols if s.kind == ChunkKind.CLASS]
        assert any(s.name == "Calculator" for s in classes), "should extract 'Calculator' class"

    def test_extracts_methods(self) -> None:
        symbols = self.parser.parse(PYTHON_SOURCE, "calc.py")
        cls = next(s for s in symbols if s.name == "Calculator")
        method_names = {c.name for c in cls.children}
        assert "multiply" in method_names
        assert "divide"   in method_names

    def test_function_docstring(self) -> None:
        symbols = self.parser.parse(PYTHON_SOURCE, "calc.py")
        add_fn = next(s for s in symbols if s.name == "add")
        assert add_fn.docstring and "sum" in add_fn.docstring

    def test_extracts_imports(self) -> None:
        symbols = self.parser.parse(PYTHON_SOURCE, "calc.py")
        imports = [s for s in symbols if s.kind == ChunkKind.IMPORT]
        assert imports, "should extract import block"
        assert "import" in imports[0].text.lower()

    def test_line_numbers(self) -> None:
        symbols = self.parser.parse(PYTHON_SOURCE, "calc.py")
        add_fn = next(s for s in symbols if s.name == "add")
        assert add_fn.start_line > 0
        assert add_fn.end_line >= add_fn.start_line

    def test_invalid_syntax_returns_empty(self) -> None:
        result = self.parser.parse("def foo(: broken syntax !!!", "bad.py")
        assert result == []


# ---------------------------------------------------------------------------
# JavaScript parser
# ---------------------------------------------------------------------------

JS_SOURCE = """\
import React from 'react';
import { useState } from 'react';

/**
 * A counter component.
 */
function Counter() {
    const [count, setCount] = useState(0);
    return count;
}

class EventEmitter {
    emit(event) {
        console.log(event);
    }
}

const add = (a, b) => {
    return a + b;
};
"""


class TestJavaScriptParser:
    def setup_method(self) -> None:
        self.parser = JavaScriptParser()

    def test_extracts_function(self) -> None:
        symbols = self.parser.parse(JS_SOURCE, "app.js")
        funcs = [s for s in symbols if s.kind == ChunkKind.FUNCTION]
        assert any(s.name == "Counter" for s in funcs)

    def test_extracts_class(self) -> None:
        symbols = self.parser.parse(JS_SOURCE, "app.js")
        classes = [s for s in symbols if s.kind == ChunkKind.CLASS]
        assert any(s.name == "EventEmitter" for s in classes)

    def test_extracts_arrow_function(self) -> None:
        symbols = self.parser.parse(JS_SOURCE, "app.js")
        funcs = [s for s in symbols if s.kind == ChunkKind.FUNCTION]
        assert any(s.name == "add" for s in funcs)

    def test_jsdoc_captured(self) -> None:
        symbols = self.parser.parse(JS_SOURCE, "app.js")
        counter = next((s for s in symbols if s.name == "Counter"), None)
        assert counter is not None
        assert counter.docstring and "counter" in counter.docstring.lower()


# ---------------------------------------------------------------------------
# Go parser
# ---------------------------------------------------------------------------

GO_SOURCE = """\
package main

import (
    "fmt"
    "errors"
)

// Add returns the sum of two integers.
func Add(a, b int) int {
    return a + b
}

// Calculator provides arithmetic operations.
type Calculator struct {
    Name string
}

// Multiply returns a * b.
func (c *Calculator) Multiply(a, b float64) float64 {
    return a * b
}
"""


class TestGoParser:
    def setup_method(self) -> None:
        self.parser = GoParser()

    def test_extracts_function(self) -> None:
        symbols = self.parser.parse(GO_SOURCE, "main.go")
        assert any(s.name == "Add" and s.kind == ChunkKind.FUNCTION for s in symbols)

    def test_extracts_struct(self) -> None:
        symbols = self.parser.parse(GO_SOURCE, "main.go")
        assert any(s.name == "Calculator" and s.kind == ChunkKind.CLASS for s in symbols)

    def test_extracts_method(self) -> None:
        symbols = self.parser.parse(GO_SOURCE, "main.go")
        assert any(s.name == "Multiply" and s.kind == ChunkKind.METHOD for s in symbols)

    def test_doc_comment_captured(self) -> None:
        symbols = self.parser.parse(GO_SOURCE, "main.go")
        add_fn = next(s for s in symbols if s.name == "Add")
        assert add_fn.docstring and "sum" in add_fn.docstring.lower()

    def test_imports_extracted(self) -> None:
        symbols = self.parser.parse(GO_SOURCE, "main.go")
        assert any(s.kind == ChunkKind.IMPORT for s in symbols)


# ---------------------------------------------------------------------------
# Rust parser
# ---------------------------------------------------------------------------

RUST_SOURCE = """\
/// A simple adder function.
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

/// Calculator struct.
pub struct Calculator {
    name: String,
}

/// A calculation trait.
pub trait Compute {
    fn compute(&self) -> f64;
}
"""


class TestRustParser:
    def setup_method(self) -> None:
        self.parser = RustParser()

    def test_extracts_function(self) -> None:
        symbols = self.parser.parse(RUST_SOURCE, "lib.rs")
        assert any(s.name == "add" and s.kind == ChunkKind.FUNCTION for s in symbols)

    def test_extracts_struct(self) -> None:
        symbols = self.parser.parse(RUST_SOURCE, "lib.rs")
        assert any(s.name == "Calculator" and s.kind == ChunkKind.CLASS for s in symbols)

    def test_extracts_trait(self) -> None:
        symbols = self.parser.parse(RUST_SOURCE, "lib.rs")
        assert any(s.name == "Compute" and s.kind == ChunkKind.BLOCK for s in symbols)

    def test_doc_comment_captured(self) -> None:
        symbols = self.parser.parse(RUST_SOURCE, "lib.rs")
        add_fn = next(s for s in symbols if s.name == "add")
        assert add_fn.docstring and "adder" in add_fn.docstring.lower()


# ---------------------------------------------------------------------------
# Generic parser
# ---------------------------------------------------------------------------

class TestGenericParser:
    def setup_method(self) -> None:
        self.parser = GenericParser()

    def test_wraps_entire_file(self) -> None:
        content = "key: value\nother: data\n"
        symbols = self.parser.parse(content, "config.yaml")
        assert len(symbols) == 1
        assert symbols[0].kind == ChunkKind.MODULE
        assert symbols[0].text == content

    def test_empty_file_returns_empty(self) -> None:
        assert self.parser.parse("   \n\n", "empty.txt") == []
