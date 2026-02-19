"""Ingestion layer: discover and read source files from disk / git."""
from .crawler import FileCrawler
from .language_detector import LanguageDetector
from .git_indexer import GitIndexer
from .watcher import FileWatcher

__all__ = ["FileCrawler", "LanguageDetector", "GitIndexer", "FileWatcher"]
