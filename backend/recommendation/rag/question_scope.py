"""What a question is about, and which retrieved chunks actually relate to it (deterministic).

Used by the trusted READ composer (strategy B) to answer the TOPIC asked instead of one
template per intent, to decline out-of-scope questions, and by the orchestrator to drop
retrieved chunks that share no distinctive term with the question (or the stored rule an
action answer explains) and chunks written as instructions to an assistant.

This is RELEVANCE, not the security boundary: strategy B never copies chunk text into an
answer, every citation is still validated against the retrieved set, and model output (if
any) goes through the full grounding chain. A miss here can only make an answer less
complete, never let an instruction or another tenant's document through.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


def fold(text: str) -> str:
    """Lower-case, no Vietnamese diacritics (đ -> d), single spaces."""
    decomposed = unicodedata.normalize("NFD", text or "").replace("đ", "d").replace("Đ", "d")
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", stripped.lower()).strip()


#: Function words and words so common in this domain that sharing them says nothing.
STOP_TERMS = frozenset("""
va voi cua la co cho toi ban minh chung ta ho nay do kia nao gi sao the nhu thi ma neu khi luc
duoc bi da dang se roi chua khong cung cac nhung mot hai ba moi rat qua lam hay hoac hon nhat
ve tu den tren duoi trong ngoai sau truoc giua theo bang de vi nen phai can muon biet hoi
vu mua lua ruong thua nong ho htx hop tac xa vu nay vu lua cay trong canh tac
bao nhieu tai lieu van ban noi huong dan quy dinh nao khong xem cho biet thong tin ve lien quan
""".split())

#: question topic -> (folded trigger phrases, fact-id prefixes the composer may state for it)
TOPICS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "carbon": (("phat thai", "khi nha kinh", "co2", "carbon", "cac bon", "me tan", "metan"),
               ("current.carbon.total_co2e_kg", "current.metrics.co2e_per_kg")),
    "yield": (("nang suat", "san luong", "thu hoach", "thu duoc", "bao nhieu lua", "duoc bao nhieu"),
              ("current.metrics.yield_kg",)),
    "status": (("giai doan", "trang thai", "dang canh tac", "da thu hoach", "tien do"),
               ("current.season.status",)),
    "water": (("nuoc", "tuoi", "awd", "ngap", "kho xen ke"),
              ("current.season.ipcc_water_regime", "current.metrics.water_m3", "current.completeness.water")),
    "fertilizer": (("phan bon", "bon phan", "bao nhieu phan", "luong phan", "phan dam", "dam", "ure", "npk"),
                   ("current.metrics.fertilizer_kg", "current.completeness.fertilizer")),
    "cost": (("chi phi", "tien", "gia thanh", "von"), ("current.metrics.cost_per_kg", "current.completeness.cost")),
    "mrv": (("mrv", "tin chi", "chung nhan", "dat chuan", "do dac bao cao"), ("current.carbon.total_co2e_kg",)),
}
#: "How is this season doing?" — every topic.
GENERIC = ("the nao", "ra sao", "tom tat", "tong quan", "tinh hinh", "giai thich vu", "the nao roi")
#: Things no tier answers: pests/pesticides/disease, weather, other organizations, markets.
#: A deterministic FIRST layer only: a paraphrase it misses still meets the provider prompt,
#: the mandatory rule_code gate and grounding (rag_qa.py), and the benchmark keeps cases that
#: deliberately avoid these phrases so the model layer stays measured.
#: Every phrase is checked against accent folding: no bare "tri sau" (duy trì / bố trí sau),
#: "dao on" (lãnh đạo ổn định) or "du bao" (dự báo phát thải is in scope).
OUT_OF_SCOPE = ("thuoc tru sau", "thuoc bvtv", "thuoc bao ve thuc vat", "phun thuoc", "sau benh", "benh hai",
                "thuoc tru", "thuoc diet", "xit thuoc", "thuoc tri sau", "cach tri sau", "phun tri sau",
                "tri benh", "tri ray", "ray nau", "benh dao on",
                "thoi tiet", "troi mua", "du bao thoi tiet", "du bao mua", "ngay mai", "htx khac", "nong ho khac",
                "gia ban", "thi truong")

#: Text addressed to an AI/system rather than describing agronomy: a chunk containing one of
#: these is not cited as evidence (it stays in the corpus for its operator to fix at ingestion),
#: and an ACTION question containing one is refused before retrieval.
INSTRUCTION_MARKERS = ("bo qua moi quy tac", "bo qua cac quy tac", "bo qua quy tac", "bo qua huong dan",
                       "bo qua chi dan", "bo qua moi chi dan", "quen cac quy tac", "quen moi quy tac",
                       "quen huong dan", "bia so lieu", "bia ra so lieu",
                       "ignore previous", "ignore all", "ignore the above", "system prompt", "ban la tro ly",
                       "hay dong vai", "dat visibility", "khong can tuan theo", "tiet lo", "jailbreak",
                       # addressed to an AI assistant/model: an approved agronomy source never is (R3
                       # gap 4: "Ghi chú dành cho trợ lý AI"). Not "yêu cầu hệ thống" (irrigation-system
                       # requirements) nor "dành cho trợ lý" (an HTX technical assistant): agy review.
                       "tro ly ai", "ai assistant", "chatbot", "mo hinh ngon ngu", "language model",
                       "as an ai", "admin override")

#: Agronomic concepts and the folded phrasings that express them. Relevance counts a shared
#: CONCEPT as well as a shared word, so an equivalent wording ("ruộng khô dần giữa các lần
#: tưới" for "AWD", "khí mê-tan" for "phát thải") is not refused for lack of identical words.
#: Deliberately absent: ambiguous folds ("lan" = lân/lần/lẫn, "tien" = tiền/tiến/tiện,
#: "dam" = đạm/đậm/đầm/dám) and bare "nuoc" (nhà nước, nước ta) / "tuoi" (tuổi, tươi):
#: water is recognised by compounds only.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "awd": ("awd", "kho xen ke", "uot kho", "ngap kho", "rut nuoc", "phoi ruong", "tuoi tiet kiem",
            "tiet kiem nuoc"),
    "water": ("muc nuoc", "nuoc tuoi", "tuoi nuoc", "ngap nuoc", "giu nuoc", "thao nuoc", "rut nuoc", "tieu nuoc",
              "bom nuoc", "lan tuoi", "lich tuoi", "che do tuoi", "tuoi ngap", "tuoi ruong", "ngap lien tuc",
              "thuy loi"),
    "ghg": ("phat thai", "khi nha kinh", "me tan", "metan", "methane", "ch4", "co2", "co2e", "carbon", "cac bon",
            "n2o"),
    "fertilizer": ("phan bon", "bon phan", "phan dam", "ure", "urea", "npk", "kali"),
    "cost": ("chi phi", "gia thanh", "vat tu", "loi nhuan"),
    "yield": ("nang suat", "san luong", "thu hoach"),
    "straw": ("rom ra", "rom", "dot rom", "vui rom"),
    # "cỏ" folds to "co" = "có" (a stop word), so the single word can never carry relevance;
    # two-word phrases can.
    "weed": ("co dai", "lua co", "lua ma", "lua hoang", "diet co", "lam co", "nho co"),
}


def action_question_refusal(question: str) -> str | None:
    """Why an ACTION (recommend / what-if) question is refused before retrieval, or None.

    `instruction_like_question`: the question talks to the assistant ("bỏ qua quy tắc ...").
    `out_of_scope_question`: it asks for something no tier answers (pesticide, disease,
    weather, other tenants, markets). Accent-insensitive (`fold`). Not the security boundary:
    a question that passes still has to survive the provider prompt, rule_code and grounding."""
    if looks_like_instructions(question):
        return "instruction_like_question"
    folded = fold(question)
    if any(_has(folded, phrase) for phrase in OUT_OF_SCOPE):
        return "out_of_scope_question"
    return None


def concepts(*texts: str) -> frozenset[str]:
    folded = " ".join(fold(text) for text in texts)
    return frozenset(name for name, phrases in CONCEPTS.items() if any(_has(folded, p) for p in phrases))


def _word_forms(*texts: str) -> dict[str, set[str]]:
    """folded distinctive word -> the spellings it was written with (lower-case NFC); a text
    typed entirely WITHOUT accents contributes the wildcard `None` (its spelling is unknown)."""
    forms: dict[str, set[str | None]] = {}
    for text in texts:
        normalized = unicodedata.normalize("NFC", text or "").lower()
        accentless = fold(normalized) == re.sub(r"\s+", " ", normalized).strip()
        for word in re.findall(r"\w+", normalized):
            folded = fold(word)
            if len(folded) >= 2 and folded not in STOP_TERMS:
                forms.setdefault(folded, set()).add(None if accentless else _spelling(word))
    return forms


def _spelling(word: str) -> tuple[str, ...]:
    """A word's accents independent of WHERE the tone mark sits: "hòa" == "hoà", "thủy" == "thuỷ",
    while "tưới" != "tuổi" and "số" != "so" (different marks)."""
    decomposed = unicodedata.normalize("NFD", word)
    marks = sorted(ch for ch in decomposed if unicodedata.category(ch) == "Mn")
    return (*marks, "đ") if "đ" in word else tuple(marks)


def shared_words(question_texts: Iterable[str], body: str) -> frozenset[str]:
    """Distinctive words the body shares with the question: the same spelling, or the same word
    folded when one side is a text typed WITHOUT accents ("lich tuoi" matches "lịch tưới").
    Inside an accented text an unaccented word is a real word, not a missing accent: "so"
    (so với) does not match "số" (số liệu), "tưới" does not match "tuổi". Known limit: one
    spelling with two meanings ("nước" = water / nation) still matches."""
    q, b = _word_forms(*question_texts), _word_forms(body)
    out = set()
    for folded in q.keys() & b.keys():
        if None in q[folded] or None in b[folded] or (q[folded] & b[folded]):
            out.add(folded)
    return frozenset(out)


def body_relevance(question_texts: Iterable[str], question_concepts: Iterable[str], body: str) -> int:
    """How much a chunk's OWN TEXT relates to the question: shared distinctive words plus shared
    concepts. Title/section are not read here: metadata may rank a chunk, never admit one."""
    return len(shared_words(question_texts, body)) + len(frozenset(question_concepts) & concepts(body))


def _has(folded: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", folded) is not None


def content_terms(*texts: str) -> frozenset[str]:
    words = set()
    for text in texts:
        words |= {w for w in re.findall(r"\w+", fold(text)) if len(w) >= 2 and w not in STOP_TERMS}
    return frozenset(words)


def question_topics(question: str) -> tuple[frozenset[str], bool, bool]:
    """(topics asked, out_of_scope, generic). Generic means "the whole season"."""
    q = fold(question)
    out = any(_has(q, phrase) for phrase in OUT_OF_SCOPE) or looks_like_instructions(question)
    topics = frozenset(name for name, (phrases, _) in TOPICS.items() if any(_has(q, p) for p in phrases))
    generic = not topics and any(_has(q, p) for p in GENERIC)
    return topics, out, generic


def looks_like_instructions(text: str) -> bool:
    folded = fold(text)
    return any(_has(folded, marker) for marker in INSTRUCTION_MARKERS)


def relevant(question_terms: Iterable[str], chunk_texts: Iterable[str]) -> bool:
    return overlap(question_terms, chunk_texts) > 0


def overlap(question_terms: Iterable[str], chunk_texts: Iterable[str]) -> int:
    return len(frozenset(question_terms) & content_terms(*chunk_texts))
