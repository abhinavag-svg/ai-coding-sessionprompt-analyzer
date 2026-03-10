from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Tuple


AFFIRMATION_PHRASES: Tuple[str, ...] = (
    "thanks",
    "thank you",
    "looks good",
    "lgtm",
    "great",
    "perfect",
    "nice",
    "works now",
    "resolved",
    "done",
    "ship it",
)

EXTENSION_PHRASES: Tuple[str, ...] = (
    "also",
    "additionally",
    "one more thing",
    "while you're at it",
    "can you also",
    "can you add",
    "could you add",
    "please add",
    "next",
    "follow up",
    "separately",
    "another thing",
)

EXPLICIT_CORRECTION_PHRASES: Tuple[str, ...] = (
    "wrong",
    "incorrect",
    "still failing",
    "fails",
    "failing",
    "redo",
    "try again",
    "you missed",
    "doesn't work",
    "does not work",
    "didn't work",
    "broken",
    "broken again",
    "same issue",
    "same error",
    "not quite",
    "nope",
    "wrong approach",
    "that's not right",
    "not what i asked",
    "use the correct",
)


_WS_TOKENS_RE = re.compile(r"\S+")


def approx_text_tokens(text: str) -> int:
    return len(_WS_TOKENS_RE.findall(text or ""))


def first_n_approx_tokens(text: str, n: int) -> str:
    if n <= 0:
        return ""
    tokens = _WS_TOKENS_RE.findall(text or "")
    return " ".join(tokens[:n])


def count_phrase_hits(text_lower: str, phrases: Iterable[str]) -> int:
    t = text_lower or ""
    return sum(1 for p in phrases if p and p in t)


def any_phrase_hit(text_lower: str, phrases: Iterable[str]) -> bool:
    t = text_lower or ""
    return any(bool(p and p in t) for p in phrases)


@dataclass(frozen=True)
class LexicalSignals:
    affirmation: bool
    extension: bool
    explicit_correction: bool
    explicit_correction_hits: int

