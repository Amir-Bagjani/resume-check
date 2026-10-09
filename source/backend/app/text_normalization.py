"""Layout-aware PDF text normalization.

PDF extraction reproduces the visual line layout, not the prose. Four artefact
families break naive matching, all seen in real resumes:

- Hyphenated line breaks: ``pro-\\nfessional`` -> ``professional``.
- Words split across lines that had no hyphen at all: ``4 years of\\n \\nyears``.
- Letters/words spaced by the PDF renderer: ``3+ y ears`` -> ``3+ years``.
- Arabic presentation forms and zero-width marks from Persian PDFs:
  ``خﻼصه`` -> ``خلاصه``, ``اپلیکیشن‌های`` -> ``اپلیکیشن‌های``.

Everything here is derived, non-destructive text: the original extraction stays
available on ``ResumeFacts.raw_text`` for keyword matching and for display.
"""
from __future__ import annotations

import re
import unicodedata

# Arabic presentation forms (U+FB50–U+FDFF, U+FE70–U+FEFF) fold back to the base
# letters with NFKC: "خﻼصه" -> "خلاصه", "ﺗﺠﺮﺑﻪ" -> "تجربه".
#
# Note: NFC is NOT enough here. U+FEFC (ﻼ) has no NFC decomposition, so a resume
# whose headings are rendered in presentation forms never matches "خلاصه" until the
# compatibility form is applied. NFKC handles it in one step.

# Zero-width and bidi control marks that PDFs inject between Persian words.
_ZERO_WIDTH_RE = re.compile(r"[-‏‪-‮⁦-⁩﻿]")

# Arabic-Indic and Persian digits folded to ASCII for numeric parsing.
_DIGIT_MAP = {
    **{ord("٠") + i: str(i) for i in range(10)},  # Arabic-Indic ٠-٩
    **{ord("۰") + i: str(i) for i in range(10)},  # Extended Arabic-Indic ۰-۹
}

# Arabic letter variants that NFKC leaves alone but Persian text needs normalized.
_LETTER_FOLD = str.maketrans({
    "ي": "ی",  # Arabic yeh -> Farsi yeh
    "ى": "ی",  # alef maksura -> Farsi yeh
    "ك": "ک",  # Arabic kaf -> keheh
    "ک": "ک",  # keheh
    "ة": "ه",  # teh marbuta -> heh
    "أ": "ا",  # alef with hamza above
    "إ": "ا",  # alef with hamza below
    "آ": "ا",  # alef with madda
    "ؤ": "و",  # waw with hamza
    "ئ": "ی",  # yeh with hamza
    "ۀ": "ه",  # heh with yeh above
    "ﻻ": "لا",  # lam-alef ligature
    "ﻵ": "لا",
    "ﻷ": "لا",
    "ﻹ": "لا",
})


def normalize_unicode(text: str) -> str:
    """Fold Arabic presentation forms, digits and letter variants to plain text.

    ``خﻼصه`` -> ``خلاصه``، ``۷`` -> ``7``، ``تجربه`` keeps its ZWNJ so word order
    and spacing stay intact for phrase matching.

    The compatibility pass runs over Arabic/Persian letters only: applying NFKC to
    the whole document would also rewrite ASCII typography (U+2010 HYPHEN becomes a
    plain "-", ligatures such as "fi" become "fi"), quietly corrupting filenames and
    file extensions such as "CV-front-end.pdf".
    """
    if not text:
        return ""
    out = "".join(
        _fold_arabic_char(ch) if _is_arabic_char(ch) else ch for ch in text
    )
    return out


def _is_arabic_char(ch: str) -> bool:
    return (
        "\u0600" <= ch <= "\u06ff"
        or "\ufb50" <= ch <= "\ufdff"
        or "\ufe70" <= ch <= "\ufeff"
        or "\u200c" <= ch <= "\u200f"
        or "\u202a" <= ch <= "\u202e"
        or "\u2066" <= ch <= "\u2069"
        or ch == "\ufeff"
    )


def _fold_arabic_char(ch: str) -> str:
    folded = unicodedata.normalize("NFKC", ch)
    folded = _ZERO_WIDTH_RE.sub("", folded)
    folded = folded.translate(_DIGIT_MAP)
    return folded.translate(_LETTER_FOLD)


# "high-\nperformance" -> "high-performance" (keep the real hyphen).
_HYPHEN_BREAK_RE = re.compile(r"(\w)[-‐‑‒–—]\s*\n\s*(\w)")

# "4 years of\n \nyears" -> collapse blank/short runs between two word characters.
_BLANK_RUN_RE = re.compile(r"[ \t]*\n[ \t]*(?=\n)")

# Any run of horizontal whitespace inside a line becomes a single space.
# Hyphens are excluded: "front-end" is a real word, not a separator to erase.
_INLINE_SPACE_RE = re.compile(r"[^\S\n]+")

# Line break between two word characters: a plain space, not a sentence boundary.
_LINE_BREAK_RE = re.compile(r"[ \t]*\n[ \t]*")

# Detection and repair for PDFs that space out every letter of a word:
# "D e v e l o p e r", or Persian "ا ط م ا ع ا ت".
#
# Repairs are gated on :func:`is_exploded_letter_document` so that a clean CV, which
# never contains several long isolated-letter runs, is left completely alone.
#
# Arabic letters are listed explicitly (U+0621..U+064A) rather than as a range,
# because the surrounding range would also swallow Latin letters.
_SPACED_LETTER = r"[A-Za-zء-ي]"

# A document needs this repair only when it contains at least two long runs; ordinary
# prose reaches at most three in a row ("U S A").
_EXPLODED_RUN_RE = re.compile(
    rf"(?<![A-Za-z]){_SPACED_LETTER}(?:[ \t]+{_SPACED_LETTER}){{4,}}(?![A-Za-z])"
)

# One exploded word. Stops before an upper-case letter because that always begins
# the next word ("F r o n t e n d S u m m a ry").
_EXPLODED_WORD_RE = re.compile(
    rf"(?<![A-Za-z]){_SPACED_LETTER}"
    rf"(?:[ \t]+(?![A-Z]){_SPACED_LETTER})*"
    rf"(?=[ \t.,;:!?()\[\]]|$)"
)

# The last two glyphs of an exploded word often keep their own spacing ("S u m m a
# ry"), so they are absorbed into the word being repaired.
_SPACED_TAIL_RE = re.compile(r"[ \t]+[A-Za-zء-ي]{2}(?=[ \t.,;:!?()\[\]]|$)")


def is_exploded_letter_document(text: str) -> bool:
    """True when the PDF renderer spaced letters apart across the whole document."""
    return len(_EXPLODED_RUN_RE.findall(text)) >= 2

# "y ears" -> "years": a single letter knocked loose from its own word by the
# renderer.
#
# Restricted to fragments that spell a real word when joined. "y ears" becomes
# "years" and is kept; "e rwith" would become "erwith" and is left alone. That
# vocabulary check is what keeps the repair from closing up genuine word boundaries
# such as "a good developer" -> "agooddeveloper".
_SPLIT_LETTER_RE = re.compile(
    r"(?<![A-Za-z])([a-z]) ([a-z]{2,})(?=[ \t]|$)"
)

# Fragments produced by this repair that spell a real English word. Small on
# purpose: it only needs to cover the words a renderer actually splits apart.
_SPLIT_LETTER_WORDS = {
    "years", "year", "yeast", "yes", "yet", "you", "your", "young",
    "team", "tech", "test", "text", "time", "type", "tool",
    "react", "redux", "state", "stack", "scale", "start", "style",
    "and", "for", "not", "are", "was", "has", "can", "all", "its",
}


# English sentence terminators.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+")

# Persian sentence terminators (؟ ! ۔) and full stop followed by space.
_FA_SENTENCE_END_RE = re.compile(r"(?<=[؟!۔؛])\s+")

# Lines that are a lone hyphen / bullet / rule, common in headers.
_NOISE_LINE_RE = re.compile(r"^[\s\-=_*•·–—.|/#\\]+$")


def dehyphenate(text: str) -> str:
    """Repair words broken across PDF line endings.

    A line break after a hyphen is genuinely ambiguous: "Front-\\nEnd" is a real
    compound, while "pro-\\nfessional" is one word split by the renderer. The hyphen
    is kept, and :func:`dehyphenate_for_matching` additionally tries the joined form
    so matching can succeed either way without guessing which one was meant.
    """
    return _HYPHEN_BREAK_RE.sub(r"\1-\2", text)


def dehyphenate_for_matching(text: str) -> str:
    """Also produce the un-hyphenated form so "pro-\\nfessional" can match.

    Returns the original text with broken words joined, leaving genuine compounds
    such as "Front-End" untouched because joining them yields a different string.
    """
    return _HYPHEN_BREAK_RE.sub(r"\1\2", text)


def collapse_split_letters(text: str) -> str:
    """Rejoin a letter the renderer split off its own word: ``y ears`` -> ``years``.

    Only applied when the joined fragment spells a known word, so real word
    boundaries are preserved.
    """

    def join(match: re.Match) -> str:
        joined = match.group(1) + match.group(2)
        # Join only when the result spells a real word; otherwise this was a
        # genuine word boundary and the space must stay ("a good" -> "a good").
        return joined if joined in _SPLIT_LETTER_WORDS else match.group(0)

    return _SPLIT_LETTER_RE.sub(join, text)


def collapse_spaced_out_words(text: str) -> str:
    """Repair PDFs whose renderer exploded words into isolated letters.

    Applied only when :func:`is_exploded_letter_document` confirms it, so clean
    prose and ordinary abbreviations ("U S A") are never touched. Inside such a
    document every word is separated, so joining is reconstruction rather than a
    guess, and the space that separates two words is restored.

    A letter run stops before an upper-case letter ("F r o n t e n d S u m m a
    ry" is two words) and swallows any two-letter tail left unspaced ("ry"), which
    is how the renderer split the final glyphs of longer words.
    """
    if not is_exploded_letter_document(text):
        return text

    out: list[str] = []
    pos = 0
    for match in _EXPLODED_WORD_RE.finditer(text):
        out.append(text[pos:match.start()])
        out.append(re.sub(r"[ \t]+", "", match.group(0)))
        tail = _SPACED_TAIL_RE.match(text, match.end())
        if tail:
            out.append(tail.group(0))
            pos = tail.end()
        else:
            pos = match.end()
        out.append(" ")
    out.append(text[pos:])
    return "".join(out)


def normalize_layout(text: str) -> str:
    """Produce analysis-ready text while keeping the prose readable.

    Newlines become spaces (they carry no meaning in a CV), hyphenated breaks are
    repaired, split letters are rejoined and Arabic presentation forms are folded.
    """
    if not text:
        return ""
    return _normalize_fragment(text)


def normalize_layout_preserving_lines(text: str) -> str:
    """Same repairs, but line structure survives so section headings stay findable.

    Section detection needs one heading per line, so newlines are kept here and
    only the in-line artefacts are repaired.
    """
    if not text:
        return ""
    t = normalize_unicode(text.replace("\r\n", "\n").replace("\r", "\n"))
    t = dehyphenate_for_matching(t)
    t = "\n".join(line for line in t.split("\n") if not _NOISE_LINE_RE.match(line))
    t = collapse_spaced_out_words(t)
    t = "\n".join(_INLINE_SPACE_RE.sub(" ", line).strip() for line in t.split("\n"))
    return t.strip()


def _normalize_fragment(text: str) -> str:
    t = normalize_unicode(text.replace("\r\n", "\n").replace("\r", "\n"))
    t = dehyphenate_for_matching(t)
    t = _BLANK_RUN_RE.sub(" ", t)
    t = "\n".join(line for line in t.split("\n") if not _NOISE_LINE_RE.match(line))
    t = _LINE_BREAK_RE.sub(" ", t)
    t = collapse_spaced_out_words(t)
    t = _INLINE_SPACE_RE.sub(" ", t)
    t = collapse_split_letters(t)
    return t.strip()


def sentences(text: str) -> list[str]:
    """Split already-normalized text into sentences.

    Used for phrase matching: it keeps a whole clause such as
    "8+ years in software development, including 6+ years building React apps"
    in one piece so the general and the technology-specific claim stay comparable.
    """
    parts = _FA_SENTENCE_END_RE.split(text)
    out: list[str] = []
    for part in parts:
        out.extend(_SENTENCE_END_RE.split(part))
    return [p.strip() for p in out if p and p.strip()]