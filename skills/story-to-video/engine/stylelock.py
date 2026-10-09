"""Style-lock helpers shared by stills.compose, brief.samples/lock and lint.

A project's look is a *preset* (image_style / flashback_style / motion_suffix / wan_negative). The lock layer adds
four optional fields on top, so a whole film uses one palette and one set of constraints, word for word:

  palette_en / palette_zh  list of colour names for this film, quoted verbatim in every still prompt
  hard_constraints         what the picture must look like, written POSITIVELY (see below)
  banned_terms             words that drag the model away from the look; lint flags them in shot prompts

Why positive: Z-Image-Turbo runs at guidance 0-1, so a negative prompt has no effect, and naming what to avoid tends
to make the model draw it (the "no scallions" lesson on a song MV). Negative wording belongs only in `wan_negative`,
where Wan runs at cfg 5 and does honour it.

Presets without these fields compose exactly as before (lock_text returns "").
"""
import re

# phrases that name something to avoid; heuristic, so lint reports them as warnings
NEG_EN = re.compile(r"\b(no|not|without|never|avoid|don't|do not|nothing|none|free of|absence of)\b", re.I)
NEG_ZH = re.compile(r"(不要|不得|别|没有|禁止|无需|切勿|避免|不含)")


def palette_en(style):
    p = style.get("palette_en")
    if not p:
        return ""
    return ", ".join(p) if isinstance(p, (list, tuple)) else str(p)


def lock_text(style):
    """The words appended after image_style in every still prompt. Empty when the style has no lock fields."""
    parts = []
    pal = palette_en(style)
    if pal:
        parts.append(f"Limited color palette of {pal}")
    if style.get("hard_constraints"):
        parts.append(style["hard_constraints"].strip().rstrip("."))
    return ". ".join(parts)


def style_text(style, flashback=False):
    """image_style (or flashback_style) plus the lock: the full style tail of a still prompt."""
    base = style["flashback_style"] if flashback else style["image_style"]
    lock = lock_text(style)
    return f"{base}. {lock}" if lock else base


def negations(text):
    """Return [(phrase_with_context)] for each negation word found in `text`."""
    out = []
    for rx in (NEG_EN, NEG_ZH):
        for m in rx.finditer(text):
            a, b = max(0, m.start() - 18), min(len(text), m.end() + 26)
            frag = text[a:b].replace("\n", " ")
            if a > 0 and " " in frag[:12]:                 # do not start / end mid-word (English text)
                frag = frag.split(" ", 1)[1]
            if b < len(text) and " " in frag[-12:]:
                frag = frag.rsplit(" ", 1)[0]
            out.append(frag.strip())
    return out


def banned_hits(text, banned):
    low = text.lower()
    return [b for b in (banned or []) if b.lower() in low]
