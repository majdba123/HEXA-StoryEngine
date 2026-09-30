"""Alignment-only view of the canonical script.

The Final Package ``canonical_script`` is the single text authority and is never edited
here. The forced aligner (WhisperX 3.8.6) recognises word boundaries only at ASCII space
(``text.split(" ")`` / ``text[cdx + 1] == " "``), while HEXA's token authority is every
Unicode whitespace run (``\\S+``). Sending paragraph/newline/tab formatted script verbatim
therefore merges tokens on the aligner side and every later word shifts.

``prepare_alignment_text`` produces a transport representation for the aligner: the
canonical tokens joined by a single ASCII space, plus the mapping of every alignment token
back to its ORIGINAL character span. This is not a semantic model; downstream layers keep
consuming canonical text and canonical spans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Single tokenization authority for forced alignment: canonical tokens are maximal runs of
# non-whitespace, exactly as script spans are tokenized elsewhere in the engine.
WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True, slots=True)
class AlignmentToken:
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class PreparedAlignmentText:
    """Canonical script + ASCII-space alignment text + token → original span map."""

    script: str
    text: str
    tokens: tuple[AlignmentToken, ...]

    def __len__(self) -> int:
        return len(self.tokens)


def prepare_alignment_text(script: str) -> PreparedAlignmentText:
    """Build the alignment text view of ``script`` without changing ``script``.

    O(len(script)); every token is a verbatim slice of the canonical script, so
    ``script[token.char_start:token.char_end] == token.text`` always holds.
    """
    tokens = tuple(
        AlignmentToken(text=match.group(), char_start=match.start(), char_end=match.end())
        for match in WORD_RE.finditer(script)
    )
    return PreparedAlignmentText(
        script=script,
        text=" ".join(token.text for token in tokens),
        tokens=tokens,
    )
