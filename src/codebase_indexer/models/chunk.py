"""
models/chunk.py
===============
The CodeChunk is the atomic unit flowing through the entire pipeline.

A chunk is a slice of source code with:
  - The raw text (what gets embedded)
  - Rich metadata (file path, language, symbol name, line range, etc.)
  - An optional embedding vector (added after the embedding stage)

Why metadata matters for RAG:
  When a language model retrieves code, it needs context beyond the bare
  text.  Knowing that a chunk is "function parse_csv at line 42 of
  src/loaders/csv.py" lets the model cite sources accurately and lets
  the retrieval layer filter by file, language, or symbol type.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Language enum
# ---------------------------------------------------------------------------

class Language(str, Enum):
    """Detected programming / markup language of the source file."""
    PYTHON     = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    TSX        = "tsx"
    JSX        = "jsx"
    GO         = "go"
    RUST       = "rust"
    JAVA       = "java"
    KOTLIN     = "kotlin"
    CSHARP     = "csharp"
    CPP        = "cpp"
    C          = "c"
    RUBY       = "ruby"
    PHP        = "php"
    SWIFT      = "swift"
    SCALA      = "scala"
    SHELL      = "shell"
    SQL        = "sql"
    HTML       = "html"
    CSS        = "css"
    YAML       = "yaml"
    JSON       = "json"
    TOML       = "toml"
    MARKDOWN   = "markdown"
    UNKNOWN    = "unknown"


# ---------------------------------------------------------------------------
# ChunkKind enum
# ---------------------------------------------------------------------------

class ChunkKind(str, Enum):
    """
    Structural category of the chunk.

    FUNCTION  – a standalone function definition
    METHOD    – a method inside a class
    CLASS     – an entire class definition (or just its header if too large)
    MODULE    – top-level module / file (used when no symbols are detected)
    BLOCK     – a named code block (e.g., an interface, trait, struct)
    SLIDING   – a fixed-size window chunk (no semantic meaning)
    DOCSTRING – extracted docstring / comment block
    IMPORT    – import / require section
    """
    FUNCTION  = "function"
    METHOD    = "method"
    CLASS     = "class"
    MODULE    = "module"
    BLOCK     = "block"
    SLIDING   = "sliding"
    DOCSTRING = "docstring"
    IMPORT    = "import"


# ---------------------------------------------------------------------------
# CodeChunk
# ---------------------------------------------------------------------------

class CodeChunk(BaseModel):
    """
    A single indexable unit of source code.

    Fields
    ------
    chunk_id        Stable SHA-256 derived from (repo_root, rel_path, start_line).
                    Stable means re-indexing the same unchanged file produces
                    identical chunk IDs, enabling efficient upserts.

    repo_root       Absolute path to the repository root (for display / filtering).
    rel_path        Path of the source file relative to repo_root.
    language        Detected language.
    kind            Structural category (function, class, sliding window, …).

    symbol_name     Fully-qualified symbol name when kind is FUNCTION / METHOD /
                    CLASS / BLOCK.  None for SLIDING / MODULE chunks.
                    Example: "MyClass.my_method"

    start_line      1-based first line of the chunk in the original file.
    end_line        1-based last line (inclusive).

    text            The raw source text that will be embedded.

    context_before  A short snippet of code immediately before this chunk
                    (e.g., the class header when the chunk is a method).
                    Included in the embedding text to improve retrieval quality.

    context_after   A short snippet after this chunk (e.g., closing brace).

    docstring       Extracted docstring / leading comment block, if any.

    token_count     Approximate token count (len(text) // 4).

    embedding       Dense vector – populated by the embedding layer.
                    Not stored in this model to keep it JSON-serialisable;
                    the vector store manages the actual float arrays.

    git_commit      Git commit SHA at index time (optional).
    git_author      Git author of the last change (optional).

    extra           Arbitrary key-value metadata for future extensibility.
    """

    # --- identity ---
    chunk_id:     str = Field(default="")
    repo_root:    str
    rel_path:     str
    language:     Language
    kind:         ChunkKind

    # --- symbol info ---
    symbol_name:  Optional[str] = None

    # --- location ---
    start_line:   int
    end_line:     int

    # --- content ---
    text:           str
    context_before: str = ""
    context_after:  str = ""
    docstring:      Optional[str] = None

    # --- derived ---
    token_count:    int = 0

    # --- git metadata ---
    git_commit:   Optional[str] = None
    git_author:   Optional[str] = None

    # --- extension slot ---
    extra: dict = Field(default_factory=dict)

    # ------------------------------------------------------------------
    def model_post_init(self, __context: object) -> None:
        # Auto-compute chunk_id if not explicitly provided
        if not self.chunk_id:
            raw = f"{self.repo_root}|{self.rel_path}|{self.start_line}"
            self.chunk_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

        # Auto-compute approximate token count
        if self.token_count == 0:
            self.token_count = max(1, len(self.text) // 4)

    # ------------------------------------------------------------------
    @computed_field
    @property
    def full_text_for_embedding(self) -> str:
        """
        The string that actually gets fed to the embedding model.

        We prepend a structured header so the model sees file path,
        language, and symbol name as part of the input.  This dramatically
        improves retrieval precision for code.

        Format:
            # <rel_path> | <language> | <kind>: <symbol_name>
            <context_before>
            <text>
        """
        parts: list[str] = []
        symbol_str = self.symbol_name or ""
        parts.append(
            f"# {self.rel_path} | {self.language.value} | "
            f"{self.kind.value}: {symbol_str}"
        )
        if self.context_before:
            parts.append(self.context_before)
        parts.append(self.text)
        return "\n".join(parts)

    @computed_field
    @property
    def display_location(self) -> str:
        """Human-readable location string, e.g. src/foo.py:42-78"""
        return f"{self.rel_path}:{self.start_line}-{self.end_line}"
