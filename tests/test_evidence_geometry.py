"""An evidence mark has to cover the sentence it quotes.

The rest of the suite checks that the right number of annotations reach the
right *pages*. Trustworthy evidence needs more than that: the rectangle has to
sit on the very words the note quotes. These tests read the text back out from
under every written annotation and compare it with the quote, so a mark that
covers half a sentence — or a different sentence — fails here instead of
looking perfectly fine in Acrobat.
"""
from __future__ import annotations

import difflib

import fitz
from pdf_helpers import annot_facts, served_pdf

# Long enough to wrap over several rendered lines, which is how a sentence in a
# real paper arrives and where a geometry bug hides.
QUOTE = (
    "We propose the Transformer, a new network architecture based solely on "
    "attention mechanisms, dispensing with recurrence and convolutions entirely."
)
SHORT_QUOTE = "We propose the Transformer."
OTHER_QUOTE = (
    "Recurrent models have long dominated sequence modeling and transduction "
    "tasks such as language modeling and machine translation."
)

# Two notes about one sentence that differ only in how it ends. Their first
# eighty characters are identical — longer than any honest dedup head.
SHARED_HEAD = (
    "The model is trained on the WMT 2014 English-German dataset consisting "
    "of about 4.5 million sentence pairs"
)
Q1 = SHARED_HEAD + " with a shared source and target vocabulary."
Q2 = SHARED_HEAD + " and evaluated on the WMT 2014 test set with beam search."

WIDTH, HEIGHT = 612.0, 792.0
EVIDENCE_TITLE = "Gloss Evidence"

# --- a side_by_side spread, laid out the way pdf2zh leaves one ---------------
# Each translation carries the numbers of its own sentence, so the two can be
# told apart without reading Chinese.
EN_LINES = [
    "The model reaches 41.2 BLEU on WMT 2014 English-to-German.",
    "Training took 3.5 days on eight P100 GPUs.",
    "We also tested 2015 variants with 12 layers.",
]
# Already wrapped: the first translation takes two lines and pushes the two
# below it down, so a mark's height no longer sits beside its own translation.
ZH_LINES = [
    "该模型在 WMT 2014 英德翻译任务上达到了 41.2 BLEU，超过了此前所有已发表的",
    "结果，也超过了集成模型的成绩，而训练代价只是它们的一小部分。",
    "训练在 8 块 P100 GPU 上耗时 3.5 天。",
    "我们还测试了 2015 年的 12 层变体。",
]
ZH_Y = [100.0, 120.0, 150.0, 180.0]
ZH_SENTENCES = [ZH_LINES[0] + ZH_LINES[1], ZH_LINES[2], ZH_LINES[3]]


def _spread_bytes() -> bytes:
    """One page: the paper in the left column, its translation in the right."""
    doc = fitz.open()
    page = doc.new_page(width=WIDTH * 2, height=HEIGHT)
    for index, line in enumerate(EN_LINES):
        page.insert_text((72.0, 100.0 + 30.0 * index), line, fontsize=10)
    for y, line in zip(ZH_Y, ZH_LINES):
        page.insert_text((WIDTH + 72.0, y), line, fontsize=10, fontname="china-s")
    data = doc.tobytes()
    doc.close()
    return data


def _paper(client, texts: list[str]) -> str:
    """A paper holding ``texts`` one under another, each wrapping as it must."""
    doc = fitz.open()
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    for index, text in enumerate(texts):
        top = 72.0 + index * 160.0
        page.insert_textbox(
            fitz.Rect(72.0, top, 540.0, top + 150.0), text, fontsize=11
        )
    data = doc.tobytes()
    doc.close()
    resp = client.post(
        "/api/papers/upload",
        files={"file": ("paper.pdf", data, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _write(client, paper_id: str, evidence: list[dict], **overrides):
    body = {"evidence": evidence, "target": "auto", "side": "original"}
    body.update(overrides)
    resp = client.post(f"/api/papers/{paper_id}/evidence/pdf", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _under(data: bytes, fact: dict) -> str:
    """The writing an annotation actually covers, read back out of the file."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        page = doc.load_page(fact["page"])
        return page.get_text("text", clip=fitz.Rect(*fact["rect"])) or ""
    finally:
        doc.close()


def _facts(data: bytes) -> list[dict]:
    return [f for f in annot_facts(data) if f["title"] == EVIDENCE_TITLE]


def _similar(a: str, b: str) -> float:
    """How much of one string the other is, ignoring spacing and case."""
    return difflib.SequenceMatcher(
        None, " ".join(a.split()).lower(), " ".join(b.split()).lower()
    ).ratio()


def test_a_quote_wrapping_over_lines_is_marked_whole(client):
    """A sentence on three rendered lines is highlighted on all three.

    Searching a fixed-length head of the quote finds its first line and stops,
    which leaves the reader looking at half a sentence and taking it for the
    whole claim the note was about.
    """
    pid = _paper(client, [QUOTE])
    try:
        out = _write(client, pid, [
            {"id": "E1", "quote": QUOTE, "why": "核心主张", "page": 0, "rects": []},
        ])
        assert out["written"] == 1, out

        data = served_pdf(client, pid)
        facts = _facts(data)
        assert len(facts) == 1, facts
        covered = _under(data, facts[0])
        assert _similar(covered, QUOTE) > 0.95, (covered, QUOTE)
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_one_line_quote_is_marked_whole(client):
    pid = _paper(client, [SHORT_QUOTE])
    try:
        out = _write(client, pid, [
            {"id": "E1", "quote": SHORT_QUOTE, "why": "主张", "page": 0, "rects": []},
        ])
        assert out["written"] == 1, out

        data = served_pdf(client, pid)
        facts = _facts(data)
        assert len(facts) == 1, facts
        assert _similar(_under(data, facts[0]), SHORT_QUOTE) > 0.95
    finally:
        client.delete(f"/api/papers/{pid}")


def test_each_quote_is_marked_on_its_own_sentence(client):
    """Two notes, two sentences: neither mark may drift onto the other.

    This is what makes an evidence chain worth following — the reader jumping
    from a claim lands on the sentence that claim came from.
    """
    pid = _paper(client, [QUOTE, OTHER_QUOTE])
    try:
        out = _write(client, pid, [
            {"id": "E1", "quote": QUOTE, "why": "主张", "page": 0, "rects": []},
            {"id": "E2", "quote": OTHER_QUOTE, "why": "背景", "page": 0, "rects": []},
        ])
        assert out["written"] == 2, out

        data = served_pdf(client, pid)
        facts = sorted(_facts(data), key=lambda f: f["rect"][1])
        assert len(facts) == 2, facts
        covered = [_under(data, f) for f in facts]
        assert _similar(covered[0], QUOTE) > 0.95, (covered[0], QUOTE)
        assert _similar(covered[1], OTHER_QUOTE) > 0.95, (covered[1], OTHER_QUOTE)
    finally:
        client.delete(f"/api/papers/{pid}")


def test_two_quotes_sharing_a_long_head_are_both_marked(client):
    """Two notes are not duplicates because their first eighty characters are.

    Comparing a truncated head drops the second note silently: the reader asked
    for two pieces of evidence and the paper quietly gets one, which is worse
    than a duplicate — nobody can see that anything went missing.
    """
    pid = _paper(client, [Q1, Q2])
    try:
        out = _write(client, pid, [
            {"id": "E1", "quote": Q1, "why": "训练数据", "page": 0,
             "rects": [[72.0, 120.0, 400.0, 140.0]]},
            {"id": "E2", "quote": Q2, "why": "评测方式", "page": 0,
             "rects": [[72.0, 150.0, 400.0, 170.0]]},
        ])
        assert out["written"] == 2, out
        assert len(_facts(served_pdf(client, pid))) == 2
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_mirror_lands_on_the_matching_translated_sentence(client):
    """The translation beside a mark is the sentence the mark quotes.

    Height alone cannot do this: the first translation wraps onto a second line
    and pushes the rest down, so the sentence sitting level with a mark is not
    the one it answers to. The numbers a translation carries over — 3.5, P100 —
    are what has to decide, and this fails if they are ignored.
    """
    resp = client.post(
        "/api/papers/upload",
        files={"file": ("paper-side_by_side.pdf", _spread_bytes(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    pid = resp.json()["id"]
    try:
        out = _write(client, pid, [
            {"id": "E1", "quote": EN_LINES[1], "why": "训练成本", "page": 0,
             "rects": [[72.0, 120.0, 400.0, 140.0]]},
            {"id": "E2", "quote": EN_LINES[2], "why": "消融实验", "page": 0,
             "rects": [[72.0, 150.0, 400.0, 170.0]]},
        ], side="both")
        assert out["written"] == 4, out

        data = served_pdf(client, pid)
        facts = _facts(data)
        right = sorted(
            (f for f in facts if f["rect"][0] >= WIDTH), key=lambda f: f["rect"][1]
        )
        assert len(right) == 2, (facts,)
        covered = [_under(data, f) for f in right]
        assert ZH_SENTENCES[1][:10] in covered[0], (covered[0], ZH_SENTENCES[1])
        assert ZH_SENTENCES[2][:10] in covered[1], (covered[1], ZH_SENTENCES[2])
    finally:
        client.delete(f"/api/papers/{pid}")


def test_a_mark_lands_on_the_quote_not_on_the_page_above_it(client):
    """The quote is the second passage on the page: the mark has to follow it."""
    pid = _paper(client, [OTHER_QUOTE, QUOTE])
    try:
        out = _write(client, pid, [
            {"id": "E1", "quote": QUOTE, "why": "主张", "page": 0, "rects": []},
        ])
        assert out["written"] == 1, out

        data = served_pdf(client, pid)
        facts = _facts(data)
        covered = _under(data, facts[0])
        assert _similar(covered, QUOTE) > 0.95, (covered, QUOTE)
        assert OTHER_QUOTE.split()[0] not in covered or _similar(covered, OTHER_QUOTE) < 0.5
    finally:
        client.delete(f"/api/papers/{pid}")
