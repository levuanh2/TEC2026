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
OUT_OF_SCOPE = ("thuoc tru sau", "thuoc bvtv", "thuoc bao ve thuc vat", "phun thuoc", "sau benh", "benh hai",
                "thoi tiet", "troi mua", "du bao", "ngay mai", "htx khac", "nong ho khac", "gia ban", "thi truong")

#: Text addressed to an AI/system rather than describing agronomy: a chunk containing one of
#: these is not cited as evidence (it stays in the corpus for its operator to fix at ingestion).
INSTRUCTION_MARKERS = ("bo qua moi quy tac", "bo qua cac quy tac", "bo qua quy tac", "bo qua huong dan",
                       "ignore previous", "ignore all", "ignore the above", "system prompt", "ban la tro ly",
                       "hay dong vai", "dat visibility", "khong can tuan theo", "tiet lo", "jailbreak")


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
