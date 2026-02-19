"""
ingestion/language_detector.py
================================
Detect the programming language of a source file.

Detection strategy (in order of preference):
  1. File extension lookup (fast, covers 99% of cases)
  2. Shebang line parsing  (handles #!/usr/bin/env python scripts)
  3. Content heuristics    (fallback for ambiguous cases)

Why not use a library?
  python-magic requires libmagic (a C library), linguist requires Ruby.
  A hand-rolled extension map is smaller, faster, and dependency-free.
"""

from __future__ import annotations

from pathlib import Path

from ..models.chunk import Language


# ---------------------------------------------------------------------------
# Extension → Language map
# Covers the vast majority of codebases encountered in the wild.
# ---------------------------------------------------------------------------
_EXT_MAP: dict[str, Language] = {
    ".py":    Language.PYTHON,
    ".pyi":   Language.PYTHON,
    ".js":    Language.JAVASCRIPT,
    ".mjs":   Language.JAVASCRIPT,
    ".cjs":   Language.JAVASCRIPT,
    ".jsx":   Language.JSX,
    ".ts":    Language.TYPESCRIPT,
    ".tsx":   Language.TSX,
    ".go":    Language.GO,
    ".rs":    Language.RUST,
    ".java":  Language.JAVA,
    ".kt":    Language.KOTLIN,
    ".kts":   Language.KOTLIN,
    ".cs":    Language.CSHARP,
    ".cpp":   Language.CPP,
    ".cc":    Language.CPP,
    ".cxx":   Language.CPP,
    ".c":     Language.C,
    ".h":     Language.C,
    ".hpp":   Language.CPP,
    ".rb":    Language.RUBY,
    ".php":   Language.PHP,
    ".swift": Language.SWIFT,
    ".scala": Language.SCALA,
    ".sc":    Language.SCALA,
    ".sh":    Language.SHELL,
    ".bash":  Language.SHELL,
    ".zsh":   Language.SHELL,
    ".fish":  Language.SHELL,
    ".sql":   Language.SQL,
    ".html":  Language.HTML,
    ".htm":   Language.HTML,
    ".css":   Language.CSS,
    ".scss":  Language.CSS,
    ".sass":  Language.CSS,
    ".less":  Language.CSS,
    ".yaml":  Language.YAML,
    ".yml":   Language.YAML,
    ".json":  Language.JSON,
    ".toml":  Language.TOML,
    ".md":    Language.MARKDOWN,
    ".mdx":   Language.MARKDOWN,
    ".rst":   Language.MARKDOWN,
}

# Shebang interpreter → Language
_SHEBANG_MAP: dict[str, Language] = {
    "python":  Language.PYTHON,
    "python3": Language.PYTHON,
    "node":    Language.JAVASCRIPT,
    "ruby":    Language.RUBY,
    "ruby3":   Language.RUBY,
    "bash":    Language.SHELL,
    "sh":      Language.SHELL,
    "zsh":     Language.SHELL,
    "fish":    Language.SHELL,
}


class LanguageDetector:
    """
    Stateless utility class for language detection.

    Usage
    -----
        detector = LanguageDetector()
        lang = detector.detect(Path("src/utils.py"))
    """

    def detect(self, path: Path, content: str | None = None) -> Language:
        """
        Detect language from path and optionally the file's first line.

        Parameters
        ----------
        path:     Path to the file (used for extension lookup).
        content:  File content (used for shebang detection if extension fails).

        Returns
        -------
        Language enum value.  Falls back to Language.UNKNOWN.
        """
        # 1. Extension-based detection
        suffix = path.suffix.lower()
        if suffix in _EXT_MAP:
            return _EXT_MAP[suffix]

        # 2. Shebang detection (first line of file)
        if content:
            first_line = content.split("\n", 1)[0].strip()
            if first_line.startswith("#!"):
                # e.g. "#!/usr/bin/env python3"
                parts = first_line.split()
                interpreter = parts[-1].split("/")[-1].lower()
                if interpreter in _SHEBANG_MAP:
                    return _SHEBANG_MAP[interpreter]

        # 3. Special filenames without extensions
        name = path.name.lower()
        _FILENAME_MAP: dict[str, Language] = {
            "makefile":    Language.SHELL,
            "dockerfile":  Language.SHELL,
            "vagrantfile": Language.RUBY,
            "gemfile":     Language.RUBY,
            "rakefile":    Language.RUBY,
            "pipfile":     Language.TOML,
            "cargo.toml":  Language.TOML,
            "go.mod":      Language.GO,
            "go.sum":      Language.GO,
        }
        if name in _FILENAME_MAP:
            return _FILENAME_MAP[name]

        return Language.UNKNOWN
