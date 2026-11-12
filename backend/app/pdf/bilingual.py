"""Locate a paper's PaperFlow translation and map note evidence onto it.

PaperFlow writes NAME-dual.pdf (original and translated pages interleaved) and
NAME-mono.pdf (translated only) beside the source PDF. The original pages inside
a dual file are byte-identical copies of the source, so evidence rectangles
transfer 1:1 onto them.

Translated pages differ: pdf2zh re-typesets them, and one source paragraph
becomes several independent text objects (one per rendered line, plus one per
font switch and per inline formula). So a translated page needs either the
PaperFlow sidecar (NAME-map.json, exact) or alignment clustering (approximate)
to recover the whole paragraph.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from .ingest import locate_text

# Filename suffixes PaperFlow appends to the source name.
SUFFIXES = ("-dual", "-mono", "-side_by_side")
SIDECAR_SUFFIX = "-map.json"

# Page sizes may differ by this much (points) and still count as identical.
SIZE_TOL = 1.0

# How much of the evidence box a sidecar paragraph must cover to count as the
# same one. Evidence is often a phrase, so it is measured against the evidence
# box rather than as IoU against the whole paragraph: a phrase inside a
# paragraph scores ~1.0 here but only ~0.1 as IoU, and would never match.
COVER_MIN = 0.35

# PaperFlow records one rectangle per drawn text object, and a formula character
# is an object of its own, so a paragraph can arrive as dozens of slivers.
# Rectangles are merged back into lines when they overlap vertically by more
# than this share of the shorter one. Neighbouring lines only overlap by a point
# or two, so they stay apart.
LINE_OVERLAP = 0.5

# How much of the final score a candidate sentence gets for sitting where the
# geometry says the quote should be. Anchors outweigh it, so a sentence carrying
# the quote's numbers beats the one the height points at.
PROX_WEIGHT = 0.5

# Two sentences this close in height count as equally well placed, and between
# them the one as far through the column as the quote is through its own wins.
# Both columns run in the same order, so where the two have drifted apart in
# height the order still agrees — but only ever as a tie-break, because it is
# itself thrown off by a translation running to a different number of sentences.
PROX_SLACK = 0.2

# A quote whose anchors weigh less than this says nothing: one weak Latin word,
# say. Position then decides alone, rather than being overridden by noise.
ANCHOR_MIN_WEIGHT = 0.8


def kind(path: str | Path) -> str:
    """Classify a PDF by filename: dual / mono / side_by_side / original."""
    stem = Path(path).stem.lower()
    for suffix in SUFFIXES:
        if stem.endswith(suffix):
            return suffix.lstrip("-")
    return "original"


# A translated page is mostly CJK and the original page facing it is not. That
# difference is the only signal left for a bilingual file once Gloss has renamed
# the import to original.pdf, which is what happens to every paper the reader
# brings in directly.
CJK_SHARE_MIN = 0.3  # share of CJK characters that reads as a translation
CJK_SHARE_GAP = 0.2  # lead a translation needs over the writing beside it
# A translated column shares its page with formulae, code and English terms, so
# its CJK share runs lower than a whole translated page's. What still marks the
# pair is that the *other* column carries next to no CJK at all.
CJK_SHARE_MIN_SIDE = 0.2
CJK_SHARE_LOW = 0.1
DETECT_PAGES = 20  # pages sampled from the front of the file
HALF_CHARS_MIN = 40  # both columns of a spread have to hold writing


def _halves_cjk_share(page: fitz.Page) -> tuple[float, float, int, int]:
    """(cjk share, cjk share, chars, chars) of the left and the right half.

    A side_by_side page holds the original and its translation beside each other,
    so one half reads as a translation and the other does not — which is the one
    thing that tells such a page from a plain one. How much text each half holds
    comes back too: a page whose text simply sits on the left (a translation laid
    out in one column, say) otherwise looks exactly like a spread.
    """
    middle = (page.rect.x0 + page.rect.x1) / 2
    left: list[str] = []
    right: list[str] = []
    try:
        words = page.get_text("words")
    except Exception:
        return 0.0, 0.0, 0, 0
    # Word by word, not block by block: a block can straddle both columns, and
    # then one half would be credited with the other half's writing.
    for word in words:
        if len(word) < 5:
            continue
        text = word[4] or ""
        (left if (word[0] + word[2]) / 2 < middle else right).append(text)
    joined_left = "".join(left)
    joined_right = "".join(right)
    return (
        _cjk_share(joined_left),
        _cjk_share(joined_right),
        len("".join(joined_left.split())),
        len("".join(joined_right.split())),
    )


def side_by_side_shift(page: fitz.Page) -> float | None:
    """How far a box moves to reach the translated column, or None.

    Positive when the translation sits to the right of the original (PaperFlow's
    layout), negative the other way round. One-sided like the rest of the
    detection: a page whose halves read alike, or whose other half is empty, is
    not a spread.
    """
    left, right, left_chars, right_chars = _halves_cjk_share(page)
    if min(left_chars, right_chars) < HALF_CHARS_MIN:
        return None
    high, low = max(left, right), min(left, right)
    if high < CJK_SHARE_MIN_SIDE or low > CJK_SHARE_LOW:
        return None
    if high - low < CJK_SHARE_GAP:
        return None
    half = page.rect.width / 2
    return half if left < right else -half


def _cjk_share(text: str) -> float:
    """Share of the non-space characters that are CJK."""
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return 0.0
    hits = 0
    for char in letters:
        code = ord(char)
        # unified ideographs, CJK punctuation, full-width forms
        if 0x4E00 <= code <= 0x9FFF or 0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF:
            hits += 1
    return hits / len(letters)


def detect_kind(path: str | Path, max_pages: int = DETECT_PAGES) -> str:
    """Tell from the contents whether a PDF interleaves originals and translations.

    Used where the filename says nothing — Gloss renames every import to
    ``original.pdf``, so a bilingual file brought in directly cannot be told from
    a plain one by name. Two shapes are looked for: a page holding the original
    and its translation side by side (``side_by_side``), and a file alternating
    original pages with translated ones (``dual``).

    Deliberately one-sided: only a marked difference counts, so a normal paper
    (or a translated-only one, whose pages are all alike) is never mirrored by
    mistake. Failing to spot one costs a missing mirror; spotting one by accident
    would put every highlight on the wrong page.
    """
    try:
        doc = fitz.open(str(path))
    except Exception:
        return "original"
    try:
        if doc.page_count < 2:
            return "original"
        even: list[float] = []
        odd: list[float] = []
        sampled = 0
        columns = 0  # pages holding an original beside a translation
        for index in range(min(doc.page_count, max_pages)):
            try:
                page = doc.load_page(index)
                text = page.get_text()
            except Exception:
                continue
            (even if index % 2 == 0 else odd).append(_cjk_share(text))
            sampled += 1
            if side_by_side_shift(page) is not None:
                columns += 1
        if sampled and columns * 2 >= sampled:
            return "side_by_side"
        if even and odd and doc.page_count % 2 == 0:
            odd_share = sum(odd) / len(odd)
            if (
                odd_share >= CJK_SHARE_MIN
                and odd_share - sum(even) / len(even) >= CJK_SHARE_GAP
            ):
                return "dual"
        return "original"
    finally:
        doc.close()


def _base(path: str | Path) -> Path:
    """Strip any PaperFlow suffix, yielding the source PDF's path."""
    p = Path(path)
    stem = p.stem
    for suffix in SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return p.with_name(stem + p.suffix)


def _sibling(path: str | Path, suffix: str, ext: str = ".pdf") -> Path | None:
    base = _base(path)
    candidate = base.with_name(base.stem + suffix + ext)
    return candidate if candidate.is_file() else None


def dual_path_for(path: str | Path) -> Path | None:
    """The -dual.pdf next to path, if it exists."""
    return _sibling(path, "-dual")


def mono_path_for(path: str | Path) -> Path | None:
    """The -mono.pdf next to path, if it exists."""
    return _sibling(path, "-mono")


def sidecar_path_for(path: str | Path) -> Path | None:
    """The -map.json paragraph map next to path, if it exists.

    PaperFlow names the sidecar after the file it was handed, which for a PDF
    downloaded from a URL is a temporary name rather than the source's. So when
    the expected name is absent, accept a lone sidecar in the same folder: an
    attachment folder holds one paper, so more than one map means the folder is
    shared and guessing would be unsafe.
    """
    named = _sibling(path, "-map", ".json")
    if named is not None:
        return named
    try:
        found = list(Path(path).parent.glob("*-map.json"))
    except OSError:
        return None
    return found[0] if len(found) == 1 else None


def translated_page(kind_: str, page: int) -> int | None:
    """Which page of a translated PDF holds the translation of page."""
    if kind_ == "dual":
        return page * 2 + 1
    if kind_ == "mono":
        return page
    # side_by_side halves and interleaves pages horizontally: unsupported.
    return None


def load_sidecar(path: str | Path) -> dict | None:
    """Read the paragraph map PaperFlow exported, or None if unusable.

    A sidecar using a different convention (e.g. bottom-left coordinates) is
    rejected rather than silently misplacing every highlight.
    """
    sidecar = sidecar_path_for(path)
    if sidecar is None:
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("coord") != "fitz":
        return None
    return data


def _sidecar_pages(sidecar: dict | None) -> dict[int, list]:
    """Sidecar paragraphs keyed by source page."""
    pages: dict[int, list] = {}
    if not sidecar:
        return pages
    for entry in sidecar.get("pages") or []:
        try:
            pages[int(entry["page"])] = entry.get("paragraphs") or []
        except (TypeError, ValueError, KeyError):
            continue
    return pages


def sidecar_paragraphs(path: str | Path) -> dict[int, list]:
    """The sidecar's paragraph table, or {} when the paper has no sidecar."""
    return _sidecar_pages(load_sidecar(path))


def mirror_rects(
    doc, original_page: int, rects: list, paragraphs: list | None, quote: str = ""
) -> list[list[float]]:
    """Rectangles on the translated page paired with an original page of a dual.

    ``doc`` is the dual file itself: its original pages are copies of the source,
    so they double as the source geometry when there is no sidecar. A page that
    is already a translated one has nothing to mirror.
    """
    if not rects or original_page % 2 != 0:
        return []
    target = original_page + 1
    if not 0 <= target < doc.page_count:
        return []
    return _translate_rects(
        doc.load_page(target), rects, paragraphs, doc, original_page, quote
    )


def side_by_side_rects(
    doc, page_index: int, rects: list, paragraphs: list | None = None,
    quote: str = "",
) -> list[list[float]]:
    """Rectangles on the translated column paired with a mark on the original one.

    PaperFlow puts the two pages beside each other at their own size, so half a
    page is a whole page and the columns carry the two pages' own coordinates:
    the mark crosses by one half, and the translation's own text says which of
    its lines the quote became. A mark already on the translated column has
    nothing to mirror.

    ``quote`` is the writing under the mark. A re-typeset column does not keep
    the original's line breaks, so the height alone says which *paragraph* a
    quote is in, never which sentence; the quote's own anchors — the numbers,
    citations and names a translation carries over untouched — say which
    sentence of that paragraph answers to it.
    """
    if not rects or not 0 <= page_index < doc.page_count:
        return []
    page = doc.load_page(page_index)
    shift = side_by_side_shift(page)
    if not shift:
        return []
    zone = _union(rects)
    if zone is None:
        return []
    middle = (page.rect.x0 + page.rect.x1) / 2
    if ((zone.x0 + zone.x1) / 2 < middle) != (shift > 0):
        return []  # already on the translated column
    # The original column carries the source page's coordinates and the
    # translated one the translation's; landing turns those into page ones.
    source = fitz.Rect(zone) if shift > 0 else fitz.Rect(zone) + (shift, 0, shift, 0)
    landing = shift if shift > 0 else 0.0
    if paragraphs:
        hit = _match_paragraph(paragraphs, source)
        if hit:
            found = _clamp(_merge_lines(hit.get("trans") or []), page.rect)
            if found:
                return [
                    [round(float(r[0]) + landing, 2), r[1],
                     round(float(r[2]) + landing, 2), r[3]]
                    for r in found
                ]
    paired = _facing_rects(page, source, shift, quote)
    if paired:
        return paired
    # Nothing to match against: the same place on the translated column.
    return _clamp(
        [[round(float(source.x0 + landing), 2), round(float(source.y0), 2),
          round(float(source.x1 + landing), 2), round(float(source.y1), 2)]],
        page.rect,
    )


def _facing_rects(
    page: fitz.Page, source: fitz.Rect, shift: float, quote: str = ""
) -> list[list[float]]:
    """Rectangles covering the translation of a mark on the original column.

    The two columns of a side_by_side page are typeset on one vertical flow: the
    writing of a page starts at the same height in both and runs down in the
    same order, so the translation of a sentence is the writing beside it. Its
    lines do not sit at the same heights — a translation runs to a different
    number of them — so what crosses over is the height, and the sentence that
    answers to it is picked out of the translated column by the quote's anchors.
    """
    half = page.rect.width / 2
    if shift > 0:
        origin = (page.rect.x0, page.rect.x0 + half)
        target = (page.rect.x0 + half, page.rect.x1)
        back = 0.0
    else:
        origin = (page.rect.x0 + half, page.rect.x1)
        target = (page.rect.x0, page.rect.x0 + half)
        back = -shift  # the source box is in the column's own coordinates
    box = fitz.Rect(source) + (back, 0, back, 0)
    drop = _column_offset(page, origin, target)
    band = fitz.Rect(target[0], box.y0 + drop, target[1], box.y1 + drop)
    line_height = _line_height(page, *target) or 12.0
    picked = _pick_sentence(
        page, origin, target, band, box, quote or _text_of(page, box), line_height
    )
    if picked:
        return _clamp(picked, page.rect)
    # Nothing written beside the mark — a figure, say: the paragraph facing it.
    boxes = _paragraph_boxes(
        _cluster_blocks(_page_blocks(page, *target), line_height)
    )
    if not boxes:
        return []
    centre = (band.y0 + band.y1) / 2
    near = min(boxes, key=lambda r: abs((r.y0 + r.y1) / 2 - centre))
    return _clamp([[round(float(v), 2) for v in near]], page.rect)


def _pick_sentence(
    page: fitz.Page,
    origin: tuple[float, float],
    target: tuple[float, float],
    band: fitz.Rect,
    box: fitz.Rect,
    quote: str,
    line_height: float,
) -> list[list[float]]:
    """The sentence of a column that answers to a quote, one box per line.

    Height says which paragraph, and a paragraph runs to several sentences, so
    highlighting the whole of it marks sentences the note is not about. The
    quote's anchors pick the one it is about, and failing those, how far through
    the column it sits.
    """
    units = _sentence_units(page, target[0], target[1])
    if not units:
        return []
    centre = (band.y0 + band.y1) / 2
    window = max(4.0 * line_height, band.height + 2.0 * line_height, 80.0)
    return _pick_best(
        units, centre, window, _anchors(quote), _expected_order(page, origin, box, units)
    )


def _expected_order(
    page: fitz.Page,
    origin: tuple[float, float],
    box: fitz.Rect,
    units: list[tuple[str, list[fitz.Rect], fitz.Rect]],
) -> float | None:
    """As a sentence index here, how far through its column the quote sits.

    The two columns are one text in two languages, so a sentence keeps its place
    in the order even where the two have drifted apart in height. Counting
    sentences rather than points survives that drift; a ratio between the two
    counts survives a translation running to a different number of them.
    """
    source = _sentence_units(page, origin[0], origin[1])
    index = _sentence_index(source, box)
    if index is None or len(source) < 2 or len(units) < 2:
        return None
    return index / (len(source) - 1) * (len(units) - 1)


def _column_offset(
    page: fitz.Page, origin: tuple[float, float], target: tuple[float, float]
) -> float:
    """How far the translated column's writing sits below the original's.

    Measured once for the page, from where each column's writing starts: the
    two are typeset together, so whatever gap there is holds all the way down.
    """
    tops: list[float | None] = []
    for column in (origin, target):
        boxes = _paragraph_boxes(
            _cluster_blocks(_page_blocks(page, *column), _line_height(page, *column))
        )
        tops.append(boxes[0].y0 if boxes else None)
    if tops[0] is None or tops[1] is None:
        return 0.0
    return float(tops[1] - tops[0])


def _paragraph_boxes(clusters: list[list[fitz.Rect]]) -> list[fitz.Rect]:
    """One box per paragraph, top to bottom."""
    boxes: list[fitz.Rect] = []
    for cluster in clusters:
        box: fitz.Rect | None = None
        for rect in cluster:
            box = rect if box is None else box | rect
        if box is not None:
            boxes.append(box)
    boxes.sort(key=lambda r: (r.y0, r.x0))
    return boxes


def _column_line_boxes(
    page: fitz.Page, x0: float, x1: float
) -> list[tuple[str, fitz.Rect]]:
    """(text, box) per line of a horizontal slice of a page, top to bottom."""
    try:
        words = page.get_text("words")
    except Exception:
        return []
    lines: list[list] = []  # [box, [(x0, text), ...]]
    for word in words:
        if len(word) < 5:
            continue
        box = fitz.Rect(word[0], word[1], word[2], word[3])
        if not x0 <= (box.x0 + box.x1) / 2 < x1:
            continue
        for entry in lines:
            overlap = min(box.y1, entry[0].y1) - max(box.y0, entry[0].y0)
            if overlap > LINE_OVERLAP * min(box.height, entry[0].height):
                entry[0] = entry[0] | box
                entry[1].append((box.x0, word[4] or ""))
                break
        else:
            lines.append([box, [(box.x0, word[4] or "")]])
    out: list[tuple[str, fitz.Rect]] = []
    for box, parts in lines:
        parts.sort()
        out.append((" ".join(text for _, text in parts), box))
    out.sort(key=lambda item: (item[1].y0, item[1].x0))
    return out


def _column_lines(page: fitz.Page, x0: float, x1: float) -> list[fitz.Rect]:
    """Line boxes of a horizontal slice of a page, top to bottom."""
    return [box for _, box in _column_line_boxes(page, x0, x1)]


# A sentence ends on a terminator, not on a line break. pdf2zh wraps a
# translated paragraph at a fixed width, so its lines stop mid-sentence and a
# sentence runs over two or three of them — reading line by line would make the
# whole paragraph look like one sentence.
_TERMINATORS = "。！？；!?"
_CLOSERS = "”’\"')」）】》"
# A full stop ends a sentence, but an abbreviation ends on one too, and so does
# every dot of an email address. What tells them apart is what follows: a
# sentence continues after a space or at the end of the line, while
# "runlin22@buaa.edu.cn" carries on straight into the next letter. What comes
# before tells the rest: "et al." and "J." are abbreviations, a word of two
# letters or more is the end of a sentence.
_DOT_HEAD = re.compile(r"[A-Za-z0-9]{2,}$")
_DOT_STOP = frozenset({
    "al", "et", "eg", "ie", "cf", "vs", "no", "fig", "eq", "inc", "ltd", "co",
    "mr", "dr", "st", "jr", "sr", "prof", "approx", "etc", "ref", "vol", "pp",
})


def _dot_ends(head: str) -> bool:
    """True when a full stop at this point really closes a sentence."""
    token = re.split(r"[^A-Za-z0-9]", head)[-1].lower()
    return len(token) >= 2 and token not in _DOT_STOP


def _split_line(
    chars: list[tuple[str, fitz.Rect]]
) -> list[tuple[str, fitz.Rect, bool]]:
    """Cut one rendered line into (text, box, ends a sentence) pieces.

    A line holding two sentences comes back as two pieces, and a line holding
    half of one as a single piece that does not end it.
    """
    ends: list[int | None] = []
    index = 0
    while index < len(chars):
        char = chars[index][0]
        stop: int | None = None
        if char in _TERMINATORS:
            stop = index
        elif (
            char == "."
            and (index + 1 == len(chars) or chars[index + 1][0].isspace())
            and _dot_ends("".join(chars[k][0] for k in range(max(0, index - 8), index)))
        ):
            stop = index
        if stop is None:
            index += 1
            continue
        # A closing mark belongs to the sentence it closes, not to the next one.
        if stop + 1 < len(chars) and chars[stop + 1][0] in _CLOSERS:
            stop += 1
        ends.append(stop)
        index = stop + 1
    pieces: list[tuple[str, fitz.Rect, bool]] = []
    start = 0
    for stop in ends:
        pieces.append(_piece(chars, start, stop, True))
        start = stop + 1
    if start < len(chars):
        pieces.append(_piece(chars, start, len(chars) - 1, False))
    return pieces


def _piece(
    chars: list[tuple[str, fitz.Rect]], start: int, stop: int, closed: bool
) -> tuple[str, fitz.Rect, bool]:
    text = "".join(chars[i][0] for i in range(start, stop + 1))
    box = fitz.Rect(chars[start][1])
    for i in range(start + 1, stop + 1):
        box = box | chars[i][1]
    return text, box, closed


def _sentence_units(
    page: fitz.Page, x0: float, x1: float
) -> list[tuple[str, list[fitz.Rect], fitz.Rect]]:
    """(text, box per rendered line, box) per sentence of a slice of a page.

    Character by character, because that is the only place a translated sentence
    really ends: a re-typeset paragraph is wrapped at a fixed width, so its line
    breaks fall inside sentences. The sentence — not the line and not the
    paragraph — is what answers to a quote: it is what the translation of one
    sentence is.
    """
    try:
        raw = page.get_text("rawdict")
    except Exception:
        return []
    units: list[tuple[str, list[fitz.Rect], fitz.Rect]] = []
    texts: list[str] = []
    boxes: list[fitz.Rect] = []
    for block in raw.get("blocks") or []:
        if block.get("type") != 0:  # 0 = text, 1 = image
            continue
        for line in block.get("lines") or []:
            chars: list[tuple[str, fitz.Rect]] = []
            for span in line.get("spans") or []:
                for char in span.get("chars") or []:
                    glyph = char.get("c") or ""
                    bbox = char.get("bbox")
                    if not glyph or not bbox:
                        continue
                    box = fitz.Rect(bbox)
                    if box.is_empty:
                        continue
                    if not x0 <= (box.x0 + box.x1) / 2 < x1:
                        continue
                    chars.append((glyph, box))
            if not chars:
                continue
            for text, box, closed in _split_line(chars):
                if not text.strip():
                    continue
                texts.append(text)
                boxes.append(box)
                if closed:
                    units.append((" ".join(texts), boxes, _union_of(boxes)))
                    texts, boxes = [], []
    if boxes:
        units.append((" ".join(texts), boxes, _union_of(boxes)))
    return units


def _union_of(boxes: list[fitz.Rect]) -> fitz.Rect:
    box = fitz.Rect(boxes[0])
    for other in boxes[1:]:
        box = box | other
    return box


# What a translation carries over from the original verbatim. Chinese has no
# shared vocabulary with English, but numbers, citation markers, figure
# references, years and technical names survive translation untouched — so
# these are the only things a quote and its translation can be matched on
# without a translation model. Ordered strongest first; the weight a token gets
# is the highest of the ones it matches.
# ``\\b`` is unusable here: Python counts a Han character as a word character,
# so "183个" and "Test4Py实现" hold no word boundary at all and every anchor in
# a Chinese sentence would go unmatched. Only ASCII counts as a word.
_EDGE_BEFORE = r"(?<![A-Za-z0-9])"
_EDGE_AFTER = r"(?![A-Za-z0-9])"

_ANCHOR_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\[\s*\d+(?:\s*[,–-]\s*\d+)*\s*\]"), 1.0),  # [3], [1-4]
    (
        re.compile(
            r"(?<![A-Za-z])(?:Fig(?:ure)?\.?|Table|Tab\.?|Eq(?:uation)?\.?|Algorithm"
            r"|Section|Sec\.?|Appendix|Lemma|Theorem|Step|Line)\s*\d+(?:\.\d+)*",
            re.I,
        ),
        1.0,
    ),
    (re.compile(r"(?<![0-9.])\d+(?:\.\d+)?\s*%"), 1.0),
    (re.compile(r"(?<![0-9])(?:19|20)\d{2}(?![0-9])"), 1.0),
    (re.compile(r"(?<![0-9.])\d+\.\d+(?![0-9])"), 0.9),
    (re.compile(r"(?<![0-9.])\d{2,}(?![0-9])"), 0.8),
    # GPT-4, ResNet50: at least one letter, or a run of digits would match too.
    (
        re.compile(
            _EDGE_BEFORE + r"(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]*\d[A-Za-z0-9]*" + _EDGE_AFTER
        ),
        0.7,
    ),
    (re.compile(_EDGE_BEFORE + r"[A-Z][A-Z0-9]{2,}" + _EDGE_AFTER), 0.8),  # LLM, API
    (re.compile(_EDGE_BEFORE + r"[A-Za-z][a-z]{2,}[A-Z][A-Za-z]*" + _EDGE_AFTER), 0.7),
    (re.compile(r"(?<![A-Za-z])[A-Za-z]{5,}(?![A-Za-z])"), 0.3),  # any Latin word
)


def _norm_anchor(token: str) -> str:
    """One spelling for a number however it is spaced: "10 %" and "10%"."""
    text = token.strip()
    if re.fullmatch(r"[0-9.,%–\-\s]+", text):
        return re.sub(r"\s+", "", text)
    return text.lower()


def _anchors(text: str) -> dict[str, float]:
    """The anchor tokens of a piece of text, each with its weight."""
    found: dict[str, float] = {}
    for pattern, weight in _ANCHOR_PATTERNS:
        for match in pattern.finditer(text):
            key = _norm_anchor(match.group(0))
            if key and weight > found.get(key, 0.0):
                found[key] = weight
    return found


def _anchor_weight(wanted: dict[str, float], text: str) -> float:
    """How much of a quote's anchors a candidate sentence carries.

    A single weak anchor is a coincidence, not a match: a technical name turns
    up all over a paper. What a sentence carries has to weigh enough on its own
    before it is allowed to count at all.
    """
    have = _anchors(text)
    return sum(w for key, w in wanted.items() if key in have)


def _pick_best(
    units: list[tuple[str, list[fitz.Rect], fitz.Rect]],
    centre: float,
    window: float,
    wanted: dict[str, float],
    order: float | None = None,
) -> list[list[float]]:
    """The sentence of ``units`` answering to a quote, as one box per line.

    Anchors decide first and outright: a sentence carrying the quote's numbers
    is the one the quote became, and no position outweighs that. Height decides
    between the sentences equally supported — or between all of them, when the
    quote's translation shares nothing to match on — and only where two sit
    equally well does how far through the column each is settle it.
    """
    if not units:
        return []
    scored: list[tuple[float, float, int, list[fitz.Rect]]] = []
    for index, (text, lines, box) in enumerate(units):
        distance = abs((box.y0 + box.y1) / 2 - centre)
        scored.append(
            (
                _anchor_weight(wanted, text),
                1.0 - min(1.0, distance / window),
                index,
                lines,
            )
        )
    carrying = [s for s in scored if s[0] >= ANCHOR_MIN_WEIGHT]
    pool = carrying or scored
    best_anchors = max(s[0] for s in pool)
    pool = [s for s in pool if s[0] >= best_anchors]
    best_prox = max(s[1] for s in pool)
    pool = [s for s in pool if s[1] >= best_prox - PROX_SLACK]
    if order is not None and len(pool) > 1:
        chosen = min(pool, key=lambda s: abs(s[2] - order))
    else:
        chosen = pool[0]
    return [[round(float(v), 2) for v in r] for r in chosen[3]]


def _sentence_index(
    units: list[tuple[str, list[fitz.Rect], fitz.Rect]], box: fitz.Rect
) -> int | None:
    """Which sentence of a column a quote starts in.

    Its start, not the most of it: a quote running over two sentences belongs to
    the one it opens, and the largest overlap would be the longer of the two.
    """
    top = fitz.Point((box.x0 + box.x1) / 2, box.y0 + min(2.0, box.height / 2))
    for index, (_, _, rect) in enumerate(units):
        if rect.contains(top):
            return index
    best: int | None = None
    best_score = 0.0
    area = box.get_area()
    for index, (_, _, rect) in enumerate(units):
        score = (rect & box).get_area() / area if area > 0 else 0.0
        if score > best_score:
            best_score, best = score, index
    return best


def _text_of(page: fitz.Page, rect: fitz.Rect) -> str:
    """The writing inside a box, for when the evidence carries no quote."""
    try:
        return page.get_text("text", clip=rect) or ""
    except Exception:
        return ""


def map_evidence(
    dual_path: str | Path, evidence: list[dict], source_path: str | Path | None = None
) -> list[dict]:
    """Map evidence onto the original pages of a dual PDF (page p -> 2p).

    Rectangles carry over as they are; when the page sizes disagree, the quote is
    re-located by text instead.
    """
    out: list[dict] = []
    if kind(dual_path) != "dual":
        return [dict(e) for e in evidence]
    try:
        doc = fitz.open(str(dual_path))
    except Exception:
        return [dict(e) for e in evidence]
    src = None
    if source_path:
        try:
            src = fitz.open(str(source_path))
        except Exception:
            src = None
    try:
        for item in evidence:
            mapped = dict(item)
            rects = item.get("rects") or []
            try:
                page = int(item.get("page"))
            except (TypeError, ValueError):
                mapped["page"] = None
                out.append(mapped)
                continue
            target = page * 2
            if not 0 <= target < doc.page_count:
                mapped.update(page=None, rects=[])
                out.append(mapped)
                continue
            mapped["page"] = target
            if rects and _sizes_match(src, doc, page, target):
                out.append(mapped)
                continue
            # Sizes differ or the source is unknown: fall back to the text.
            found = locate_text(str(dual_path), str(item.get("quote") or ""))
            if found:
                mapped["page"] = found["page"]
                mapped["rects"] = found["rects"]
            else:
                mapped["rects"] = rects
            out.append(mapped)
    finally:
        doc.close()
        if src is not None:
            src.close()
    return out


def _sizes_match(src, doc, src_page: int, dst_page: int) -> bool:
    """True when both pages are the same size, so rectangles carry over."""
    if src is None or not 0 <= src_page < src.page_count:
        # Without the source we cannot compare; dual originals are copies, so
        # reusing the rectangles is the reasonable bet.
        return True
    a = src.load_page(src_page).rect
    b = doc.load_page(dst_page).rect
    return abs(a.width - b.width) <= SIZE_TOL and abs(a.height - b.height) <= SIZE_TOL


def _union(rects: list) -> fitz.Rect | None:
    """The bounding box of every evidence rectangle."""
    box: fitz.Rect | None = None
    for r in rects:
        if len(r) != 4:
            continue
        try:
            part = fitz.Rect(*[float(v) for v in r])
        except (TypeError, ValueError):
            continue
        box = part if box is None else box | part
    return box


def _project(box: fitz.Rect, src, src_page: int, page: fitz.Page) -> fitz.Rect | None:
    """Move a source rectangle onto a translated page, padding for reflow."""
    if src is not None and 0 <= src_page < src.page_count:
        a = src.load_page(src_page).rect
        b = page.rect
        if abs(a.width - b.width) > SIZE_TOL or abs(a.height - b.height) > SIZE_TOL:
            if a.width <= 0 or a.height <= 0:
                return None
            sx, sy = b.width / a.width, b.height / a.height
            box = fitz.Rect(box.x0 * sx, box.y0 * sy, box.x1 * sx, box.y1 * sy)
    # Translated text can sit outside the source box (pdf2zh only compresses
    # line height, and does not wrap a paragraph that had no line break).
    pad = max(6.0, box.height * 0.15)
    return fitz.Rect(box.x0 - pad, box.y0 - pad, box.x1 + pad, box.y1 + pad)


def _match_paragraph(paragraphs: list[dict], zone: fitz.Rect) -> dict | None:
    """The sidecar paragraph covering most of zone."""
    best: dict | None = None
    best_score = 0.0
    area = zone.get_area()
    if area <= 0:
        return None
    for para in paragraphs:
        orig = para.get("orig")
        if not orig or len(orig) != 4:
            continue
        try:
            box = fitz.Rect(*[float(v) for v in orig])
        except (TypeError, ValueError):
            continue
        score = (box & zone).get_area() / area
        if score > best_score:
            best_score, best = score, para
    return best if best_score >= COVER_MIN else None


def _merge_lines(rects: list) -> list[list[float]]:
    """Collapse the rectangles of one paragraph back into its lines."""
    boxes: list[fitz.Rect] = []
    for r in rects:
        if len(r) != 4:
            continue
        try:
            box = fitz.Rect(*[float(v) for v in r])
        except (TypeError, ValueError):
            continue
        if not box.is_empty and box.width > 0 and box.height > 0:
            boxes.append(box)
    boxes.sort(key=lambda b: (b.y0, b.x0))

    lines: list[fitz.Rect] = []
    for box in boxes:
        for i, line in enumerate(lines):
            overlap = min(box.y1, line.y1) - max(box.y0, line.y0)
            if overlap > LINE_OVERLAP * min(box.height, line.height):
                lines[i] = line | box
                break
        else:
            lines.append(box)
    lines.sort(key=lambda b: (b.y0, b.x0))
    return [[round(float(v), 2) for v in r] for r in lines]


def _clamp(rects: list[list[float]], bounds: fitz.Rect) -> list[list[float]]:
    """Keep highlights on the page.

    PaperFlow lets a line it could not wrap run past the right edge, and those
    rectangles are reported as they are; a highlight beyond the page would be
    drawn off it.
    """
    out: list[list[float]] = []
    for r in rects:
        if len(r) != 4:
            continue
        box = fitz.Rect(*[float(v) for v in r]) & bounds
        if box.is_empty:
            continue
        out.append([round(float(v), 2) for v in box])
    return out


def _page_blocks(
    page: fitz.Page, x0: float | None = None, x1: float | None = None
) -> list[fitz.Rect]:
    """Text block boxes of a page, optionally only those of a horizontal slice.

    A block belongs to the slice its centre falls in, so a column of a
    side_by_side page can be read as the page it really is.
    """
    blocks: list[fitz.Rect] = []
    try:
        raw = page.get_text("blocks")
    except Exception:
        return []
    lo = page.rect.x0 if x0 is None else x0
    hi = page.rect.x1 if x1 is None else x1
    for block in raw:
        if len(block) < 7 or block[6] != 0:  # 0 = text, 1 = image
            continue
        try:
            rect = fitz.Rect(block[0], block[1], block[2], block[3])
        except Exception:
            continue
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            continue
        if not lo <= (rect.x0 + rect.x1) / 2 < hi:
            continue
        blocks.append(rect)
    return blocks


def _cluster_blocks(
    blocks: list[fitz.Rect], line_height: float | None = None
) -> list[list[fitz.Rect]]:
    """Group text blocks into paragraphs.

    pdf2zh keeps a paragraph's lines left-aligned and evenly spaced, so
    neighbouring blocks sharing a left edge across a small vertical gap belong
    to the same paragraph.

    ``line_height`` is what the gap is rated against, and it is the height of a
    line, not of the blocks: a paragraph can arrive as one tall block, and
    rating the gap against that lets it swallow whatever sits below it however
    far away, and lets a later block jump over the ones in between and join it.
    Without it, the shorter of the two blocks is the least bad measure.
    """
    blocks = sorted(blocks, key=lambda r: (round(r.y0, 1), r.x0))
    clusters: list[list[fitz.Rect]] = []
    for rect in blocks:
        for cluster in clusters:
            last = cluster[-1]
            if abs(rect.x0 - last.x0) > max(2.0, 0.02 * last.width):
                continue
            gap = rect.y0 - last.y1
            if gap > 0.6 * (line_height or min(last.height, rect.height)):
                continue
            cluster.append(rect)
            break
        else:
            clusters.append([rect])
    return clusters


def _line_height(page: fitz.Page, x0: float, x1: float) -> float | None:
    """The height a line of writing in a column usually has."""
    heights = sorted(line.height for line in _column_lines(page, x0, x1))
    if not heights:
        return None
    return heights[len(heights) // 2]


def _clusters(page: fitz.Page) -> list[list[fitz.Rect]]:
    """Group a translated page's text blocks into paragraphs."""
    return _cluster_blocks(_page_blocks(page))


def map_evidence_to_translated(
    path: str | Path,
    evidence: list[dict],
    *,
    sidecar: dict | None = None,
    source_path: str | Path | None = None,
    kind_: str | None = None,
) -> list[dict]:
    """Map evidence onto the translated pages of a dual or mono PDF.

    Prefers the PaperFlow sidecar and falls back to alignment clustering. A
    paragraph comes back as one rectangle per rendered line, because that is what
    a re-typeset paragraph actually is.

    ``kind_`` overrides what the filename says, for a file whose name is not
    PaperFlow's — Gloss's own copy of an imported bilingual file, say.
    """
    kind_ = kind_ or kind(path)
    if sidecar is None:
        sidecar = load_sidecar(path)
    pages = _sidecar_pages(sidecar)
    try:
        doc = fitz.open(str(path))
    except Exception:
        return [dict(e, page=None, rects=[]) for e in evidence]
    src = None
    if source_path:
        try:
            src = fitz.open(str(source_path))
        except Exception:
            src = None
    try:
        out: list[dict] = []
        for item in evidence:
            mapped = dict(item)
            try:
                page = int(item.get("page"))
            except (TypeError, ValueError):
                mapped["page"] = None
                out.append(mapped)
                continue
            if kind_ == "side_by_side":
                # The translation is the column beside the original, on the very
                # same page.
                mapped["page"] = page
                mapped["rects"] = side_by_side_rects(
                    doc, page, item.get("rects") or [], pages.get(page),
                    str(item.get("quote") or ""),
                )
                out.append(mapped)
                continue
            target = translated_page(kind_, page)
            if target is None or not 0 <= target < doc.page_count:
                mapped.update(page=None, rects=[])
                out.append(mapped)
                continue
            mapped["page"] = target
            mapped["rects"] = _translate_rects(
                doc.load_page(target),
                item.get("rects") or [],
                pages.get(page),
                src,
                page,
                str(item.get("quote") or ""),
            )
            out.append(mapped)
    finally:
        doc.close()
        if src is not None:
            src.close()
    return out


def _translate_rects(
    page: fitz.Page,
    rects: list,
    paragraphs: list[dict] | None,
    src,
    src_page: int,
    quote: str = "",
) -> list[list[float]]:
    """Rectangles covering one evidence quote on a translated page."""
    if not rects:
        return []
    zone = _union(rects)
    if zone is None:
        return []
    if paragraphs:
        hit = _match_paragraph(paragraphs, zone)
        if hit:
            found = _clamp(_merge_lines(hit.get("trans") or []), page.rect)
            if found:
                return found
    # No usable sidecar: project the source box, then keep the sentence of the
    # paragraph it lands on that the quote is about.
    projected = _project(zone, src, src_page, page)
    if projected is None:
        return []
    for cluster in _clusters(page):
        if any(not (r & projected).is_empty for r in cluster):
            zone_box: fitz.Rect | None = None
            for rect in cluster:
                zone_box = rect if zone_box is None else zone_box | rect
            if zone_box is None:
                break
            units = [
                unit
                for unit in _sentence_units(page, page.rect.x0, page.rect.x1)
                if not (unit[2] & zone_box).is_empty
            ]
            picked = _pick_best(
                units,
                (projected.y0 + projected.y1) / 2,
                max(projected.height, 4.0 * (_line_height(page, page.rect.x0, page.rect.x1) or 12.0)),
                _anchors(quote),
            )
            if picked:
                return _clamp(picked, page.rect)
            return _clamp(
                [[round(float(v), 2) for v in r] for r in cluster], page.rect
            )
    return _clamp([[round(float(v), 2) for v in projected]], page.rect)
