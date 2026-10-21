"""Narration structure shared by Boundary (idea boards) and Motion (idea climax)."""

from __future__ import annotations

import re

SENTENCE_END = frozenset(".!?؟…")
_CLOSERS = "\"'»)]}”’ "


def continues_sentence(narration: str | None) -> bool:
    """True when a beat's narration stops mid-sentence: the next picture is the same idea."""
    text = (narration or "").strip().rstrip(_CLOSERS)
    return bool(text) and any(char.isalpha() for char in text) and text[-1] not in SENTENCE_END


# Arabic (MSA and dialect) connectives that open a sentence continuing the same idea:
# "and / so / but / because / meaning / even / then / also / or".
_LEAD = r"^[\s‏‎⁦-⁩\"'«(]*"
_END = r"(?=[\s,،.!؟?‎‏⁦-⁩]|$)"
_CONTINUATION = re.compile(
    _LEAD + r"(?:(?:لأن|لان|لإن|عشان|علشان)(?:ه|ها|هم|و|ك|ي|نا)?|بس|يعني|حتى|ثم|لكن|بل|أو|او|كمان|بعدين|مع ذلك)"
    + _END
)
# A و / ف clitic is a connective only before the article or a known continuation word
# (والهاكر، وهون، فهيك ...); many nouns simply start with و or ف (وزارة، فلوس).
_CLITIC_WAW_FA = re.compile(
    _LEAD + r"[وف](?:ال(?=[ء-ي])|(?:هون|هنا|هيك|هكذا|هذا|هذه|هاد|هاي|هي|هو|هم|بعدين|كمان|بالتالي"
    r"|عشان|لأنه|لأن|لكن|بس|حتى|إذا|اذا|لو|لما|كان|صار)" + _END + ")"
)


def continues_idea(next_narration: str | None) -> bool:
    """True when the next sentence opens with a connective (و/ف prefix, بس, لأن, يعني...):
    it continues the idea the previous sentence started."""
    text = next_narration or ""
    return bool(_CONTINUATION.match(text) or _CLITIC_WAW_FA.match(text))


_HOOK_OPENERS = re.compile(
    _LEAD + r"(?:تخيل|تخيّل|تخيلوا|هل|ليش|ليه|لماذا|ليشو|كيف|شلون|شو|ماذا|ما الذي|متى|وين|أين|مين|منو|من هو|من هي|عمرك|بتعرف|تعرف|هلق تخيل)"
    + _END
)


def is_hook(sentence: str | None) -> bool:
    """A question, an exclamation or a "picture this" opener: the video's hook."""
    text = (sentence or "").strip().rstrip(_CLOSERS)
    return bool(text) and (text[-1] in "?؟!" or bool(_HOOK_OPENERS.match(text)))
