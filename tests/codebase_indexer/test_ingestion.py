"""
tests/codebase_indexer/test_ingestion.py
==========================================
Tests for the ingestion layer: language detection, file crawling.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from codebase_indexer.ingestion.language_detector import LanguageDetector
from codebase_indexer.ingestion.crawler import FileCrawler
from codebase_indexer.models.chunk import Language


class TestLanguageDetector:
    def setup_method(self) -> None:
        self.detector = LanguageDetector()

    def test_python_extension(self) -> None:
        assert self.detector.detect(Path("foo.py")) == Language.PYTHON

    def test_javascript_extension(self) -> None:
        assert self.detector.detect(Path("app.js")) == Language.JAVASCRIPT

    def test_typescript_extension(self) -> None:
        assert self.detector.detect(Path("types.ts")) == Language.TYPESCRIPT

    def test_go_extension(self) -> None:
        assert self.detector.detect(Path("main.go")) == Language.GO

    def test_rust_extension(self) -> None:
        assert self.detector.detect(Path("lib.rs")) == Language.RUST

    def test_yaml_extension(self) -> None:
        assert self.detector.detect(Path("config.yaml")) == Language.YAML

    def test_unknown_extension(self) -> None:
        assert self.detector.detect(Path("file.xyz")) == Language.UNKNOWN

    def test_shebang_python(self) -> None:
        result = self.detector.detect(
            Path("script"),
            content="#!/usr/bin/env python3\nprint('hi')\n",
        )
        assert result == Language.PYTHON

    def test_shebang_bash(self) -> None:
        result = self.detector.detect(
            Path("run"),
            content="#!/bin/bash\necho hello\n",
        )
        assert result == Language.SHELL

    def test_dockerfile_by_name(self) -> None:
        result = self.detector.detect(Path("Dockerfile"))
        assert result == Language.SHELL


class TestFileCrawler:
    def test_crawl_yields_python_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create some files
            (root / "main.py").write_text("def foo(): pass\n")
            (root / "utils.py").write_text("def bar(): pass\n")
            (root / "config.yaml").write_text("key: value\n")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"binary")

            crawler = FileCrawler(root)
            results = asyncio.run(_collect(crawler))

            paths = {sf.rel_path for sf in results}
            assert "main.py"    in paths
            assert "utils.py"   in paths
            assert "config.yaml" in paths

            # __pycache__ should be ignored
            assert not any("__pycache__" in p for p in paths)

    def test_change_detection_skips_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "foo.py").write_text("x = 1\n")

            # First crawl
            crawler1 = FileCrawler(root)
            results1 = asyncio.run(_collect(crawler1))
            assert len(results1) == 1

            # Capture hash from first crawl
            known = {results1[0].rel_path: results1[0].content_hash}

            # Second crawl with known hashes – should skip unchanged file
            crawler2 = FileCrawler(root, known_hashes=known)
            results2 = asyncio.run(_collect(crawler2))
            assert len(results2) == 0  # nothing changed → nothing yielded

    def test_force_flag_reindexes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "foo.py").write_text("x = 1\n")

            # Crawl with known hashes but force=True
            crawler = FileCrawler(
                root,
                known_hashes={"foo.py": "somehash"},
                force=True,
            )
            results = asyncio.run(_collect(crawler))
            assert len(results) == 1


async def _collect(crawler: FileCrawler) -> list:
    items = []
    async for sf in crawler.crawl():
        items.append(sf)
    return items
