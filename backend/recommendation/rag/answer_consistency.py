"""Trusted post-generation consistency gate for ACTION answers (Flash R3 finding, 2026-11-07).

R3: asked about insects eating rice leaves, deepseek-flash wrote "Tôi không thể tư vấn chọn thuốc…"
and then recommended AWD — a stored M05 rule with valid citations, so every earlier gate passed.
An existing rule_code is necessary, not sufficient: a recommendation must also answer the
subject the farmer asked about, and an answer must not both refuse and advise.

Runs AFTER schema, citation, fact and grounding validation, on the grounded `GeneratedAnswer`.
It never repairs: any violation discards the whole model answer (the orchestrator returns the
trusted `answer_policy_rejected` state). It is deterministic and fails closed: a rule without a
declared subject, or a question whose subject cannot be recognised, admits no recommendation
unless the question is a pure "what should I do for this season" request.

Not a semantic oracle: it recognises subjects from a closed vocabulary. A paraphrase it does not
recognise makes it REJECT (fail closed), never admit. It does not replace the prompt, the
rule_code gate or grounding; the benchmark reports model policy failures separately.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .models import GeneratedAnswer
from .question_scope import fold

#: What each stored M05 rule is about. Closed: an unknown rule_code admits nothing.
RULE_SUBJECTS: dict[str, frozenset[str]] = {
    "water.awd_from_continuous_flooding": frozenset({"water", "emission"}),
    "data.completeness.yield": frozenset({"yield", "data"}),
    "data.completeness.water": frozenset({"water", "data"}),
    "data.completeness.fertilizer": frozenset({"fertilizer", "data"}),
    "data.completeness.cost": frozenset({"cost", "data"}),
}

#: Subject vocabulary, written WITH accents. Matched word by word on the accent signature (so
#: "tưới" never matches "tuổi"); a question typed entirely without accents is matched folded.
SUBJECT_PHRASES: dict[str, tuple[str, ...]] = {
    "water": ("tưới", "nước tưới", "lượng nước", "mực nước", "ngập", "khô xen kẽ", "ướt khô", "rút nước",
              "phơi ruộng", "thủy lợi", "awd"),
    "emission": ("phát thải", "khí nhà kính", "mê-tan", "mê tan", "metan", "methane", "carbon", "các-bon",
                 "cacbon", "co2", "co2e", "ch4", "giảm khí"),
    "fertilizer": ("phân bón", "bón phân", "bón", "phân đạm", "đạm", "urê", "ure", "npk", "kali", "lân"),
    "cost": ("chi phí", "giá thành", "vật tư", "tiền", "lợi nhuận", "vốn", "tốn kém"),
    "yield": ("năng suất", "sản lượng", "thu hoạch", "thu được", "bao nhiêu lúa"),
    "data": ("số liệu", "dữ liệu", "ghi chép", "ghi lại", "ghi sổ", "nhật ký", "sổ theo dõi", "nhập", "bổ sung",
             "đầy đủ", "còn thiếu", "thiếu"),
}

#: Subjects NO stored rule covers. A question that names one is about something else, even when it
#: also mentions emissions or water ("đốt rơm có giảm phát thải không", "vụ đã đạt tín chỉ carbon
#: chưa"): it may carry NO recommendation. Bare "sâu" is absent on purpose (also "deep": nước sâu).
UNCOVERED_SUBJECT_PHRASES: dict[str, tuple[str, ...]] = {
    "pest_disease": ("côn trùng", "sâu bệnh", "sâu cuốn lá", "sâu đục thân", "rầy", "chuột", "ốc bươu", "ốc",
                     "bệnh", "nấm", "đốm", "lem lép", "thuốc", "phun", "xịt", "diệt", "trừ sâu", "vôi"),
    "straw": ("rơm", "rơm rạ", "đốt rơm"),
    "weed": ("cỏ dại", "lúa cỏ", "lúa ma"),
    "credit_market": ("tín chỉ", "chứng nhận", "đạt chuẩn", "mrv", "bán", "thị trường", "giá bán", "hồ sơ"),
    "coercion": ("bằng không", "không cần hệ thống", "tự tính", "bịa", "không giới hạn", "bỏ giới hạn", "admin",
                 "quên hết", "kê đơn"),
}

#: Words a "what should I do for this season" request is made of, WITH accents. A RECOMMEND/WHAT_IF
#: question made ONLY of these words names no other subject, so any stored rule may answer it
#: (the farmer chose the recommend intent). One word outside the list ("bị", "sâu", "côn trùng",
#: "xịt", …) and the question must name a subject the rule covers. Matched on the accent signature,
#: so "sâu" (pest) is not "sau" (after); a fully accent-free question is matched folded.
GENERIC_WORDS = frozenset("""
tôi mình nhà chúng ta em anh chị bà con cô chú bác bạn
vụ này đó ruộng lúa mùa thửa đồng
nên cần phải có thể được hãy muốn
làm gì sao thế nào ra cải thiện ưu tiên việc điều cách gợi ý khuyến nghị đề xuất
trước tiếp theo bây giờ đầu hiện tại sắp tới tới
cho với của ở trên để tốt hơn ổn không chưa rồi vậy nhỉ ạ hả nha nhé đi
""".split())
_GENERIC_SPELLINGS = None  # built lazily from GENERIC_WORDS

#: The assistant itself declines (folded): subject + negation + a verb of advising, or out of scope.
_SELF_REFUSAL = re.compile(
    r"(?<!\w)(?:(?:toi|tro ly|he thong|chung toi)\s+(?:khong the|khong|chua the|xin phep khong)\s+"
    r"(?:tu van|huong dan|ke|dua ra|khuyen|cung cap|tra loi|xac nhan|chan doan|chi dinh|goi y)"
    r"|ngoai pham vi|khong thuoc pham vi|khong duoc phep tu van|khong nam trong pham vi)(?!\w)"
)

POLICY_REASONS = ("refusal_with_recommendation", "recommendation_off_topic", "unknown_rule_subject")


def _words(text: str) -> list[tuple[str, tuple[str, ...]]]:
    out = []
    for word in re.findall(r"\w+", unicodedata.normalize("NFC", text or "").lower()):
        marks = sorted(ch for ch in unicodedata.normalize("NFD", word) if unicodedata.category(ch) == "Mn")
        out.append((fold(word), (*marks, "đ") if "đ" in word else tuple(marks)))
    return out


def _accentless(text: str) -> bool:
    return all(not marks for _, marks in _words(text))


def question_subjects(question: str, vocabulary: dict[str, tuple[str, ...]] | None = None) -> frozenset[str]:
    words = _words(question)
    loose = _accentless(question)
    found = set()
    for subject, phrases in (SUBJECT_PHRASES if vocabulary is None else vocabulary).items():
        for phrase in phrases:
            target = _words(phrase)
            n = len(target)
            for i in range(len(words) - n + 1):
                window = words[i:i + n]
                if all(w[0] == t[0] and (loose or w[1] == t[1]) for w, t in zip(window, target)):
                    found.add(subject)
                    break
            if subject in found:
                break
    return frozenset(found)


def is_generic_action_question(question: str) -> bool:
    """True when every word of the question is generic request filler (and there is at least one)."""
    global _GENERIC_SPELLINGS
    if _GENERIC_SPELLINGS is None:
        _GENERIC_SPELLINGS = frozenset(w for word in GENERIC_WORDS for w in _words(word))
    words = _words(question)
    if not words:
        return False
    if _accentless(question):
        folded_generic = {f for f, _ in _GENERIC_SPELLINGS}
        return all(f in folded_generic for f, _ in words)
    return all(w in _GENERIC_SPELLINGS for w in words)


def self_refusal(texts: Iterable[str | None]) -> bool:
    return any(_SELF_REFUSAL.search(fold(text or "")) for text in texts)


def answer_policy_violation(question: str, answer: GeneratedAnswer) -> str | None:
    """None when the answer is consistent; otherwise a sanitized reason code (POLICY_REASONS)."""
    if not answer.recommendations:
        return None
    if self_refusal((answer.answer, answer.rationale)):
        return "refusal_with_recommendation"
    if question_subjects(question, UNCOVERED_SUBJECT_PHRASES):
        return "recommendation_off_topic"  # the question is (also) about something no rule covers
    generic = is_generic_action_question(question)
    asked = question_subjects(question)
    for rec in answer.recommendations:
        if rec.rule_code is None:
            continue  # a missing rule_code is the structural rule gate's refusal (rag_qa), unchanged
        subjects = RULE_SUBJECTS.get(rec.rule_code)
        if subjects is None:
            return "unknown_rule_subject"
        if not generic and not (subjects & asked):
            return "recommendation_off_topic"
    return None


def assess_raw_answer(question: str, raw: object) -> dict[str, object]:
    """Evaluation helper (benchmark/diagnostics): judge a model's RAW structured output with the same
    rules, before any downstream gate. Never used to build a user response."""
    try:
        answer = GeneratedAnswer.model_validate(raw)
    except Exception:  # noqa: BLE001 - a schema-invalid output is a finding, not a crash
        return {"schema_valid": False, "status": None, "rules": [], "policy_violation": None, "declined": None}
    return {"schema_valid": True, "status": answer.status,
            "rules": [rec.rule_code for rec in answer.recommendations],
            "policy_violation": answer_policy_violation(question, answer),
            "declined": answer.status == "insufficient_evidence" and not answer.recommendations}
