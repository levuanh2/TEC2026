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

The same closed vocabulary of subjects NO rule covers (`UNCOVERED_SUBJECT_PHRASES`) is also the
second pre-model layer (`uncovered_question_refusal`, called by the orchestrator before retrieval),
so the two layers can never disagree about what is out of scope.

Not a semantic oracle: it recognises subjects from a closed vocabulary. A paraphrase it does not
recognise makes it REJECT (fail closed), never admit. It cannot see a false premise stated in
covered words (e.g. "drained all season, is that AWD?") — that stays the prompt's and the model's
job, and the benchmark reports model policy failures separately.
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
#: A data-task rule answers a question about RECORDS: the domain word alone ("phân đạm",
#: "tưới nước") is a farming question, not a records question (R3 follow-up: "double the nitrogen,
#: show me how to apply it" must not be answered with "record your fertilizer amounts").
DATA_RULE_PREFIX = "data.completeness."
#: Subjects that name WHAT a question is about (as opposed to "data", which names records).
DOMAIN_SUBJECTS = frozenset({"water", "emission", "fertilizer", "cost", "yield"})

#: Subject vocabulary, written WITH accents. Matched word by word on the accent signature (so
#: "tưới" never matches "tuổi"); a question typed entirely without accents is matched folded.
SUBJECT_PHRASES: dict[str, tuple[str, ...]] = {
    "water": ("tưới", "nước tưới", "lượng nước", "mực nước", "ngập", "khô xen kẽ", "ướt khô", "rút nước",
              "phơi ruộng", "thủy lợi", "awd", "bơm nước", "tháo nước", "giữ nước", "cấp nước", "thoát nước"),
    "emission": ("phát thải", "khí nhà kính", "mê-tan", "mê tan", "metan", "methane", "carbon", "các-bon",
                 "cacbon", "co2", "co2e", "ch4", "giảm khí"),
    "fertilizer": ("phân bón", "bón phân", "bón", "phân đạm", "đạm", "urê", "ure", "npk", "kali", "lân"),
    "cost": ("chi phí", "giá thành", "vật tư", "tiền", "lợi nhuận", "vốn", "tốn kém"),
    "yield": ("năng suất", "sản lượng", "thu hoạch", "thu được", "bao nhiêu lúa"),
    "data": ("số liệu", "dữ liệu", "ghi", "ghi chép", "ghi lại", "ghi sổ", "nhật ký", "sổ theo dõi", "nhập",
             "bổ sung", "đầy đủ", "đã đủ", "đủ chưa", "còn thiếu", "thiếu", "chưa cân", "cân sản lượng", "cân lúa"),
}
#: Applying MORE of an input is a farming practice, not filling in records: these windows are
#: masked before the "data" subject is looked for ("bón bổ sung" is top-dressing).
NOT_DATA_PHRASES = ("bón bổ sung", "bón thêm", "tưới bổ sung", "tưới thêm", "bổ sung nước", "bổ sung phân",
                    "bơm thêm", "thiếu nước", "thiếu phân", "thiếu đạm")

#: Subjects NO stored rule covers. A question that names one is about something else, even when it
#: also mentions emissions or water ("đốt rơm có giảm phát thải không", "vụ đã đạt tín chỉ carbon
#: chưa"): it is refused before the model and may carry NO recommendation. Bare "sâu" is absent on
#: purpose (also "deep": nước sâu).
UNCOVERED_SUBJECT_PHRASES: dict[str, tuple[str, ...]] = {
    "pest_disease": ("côn trùng", "sâu bệnh", "sâu cuốn lá", "sâu đục thân", "sâu non", "sâu keo", "sâu hại",
                     "sâu phao", "bọ trĩ", "bọ xít", "bọ rùa", "nhện", "rệp", "bướm", "châu chấu", "rầy", "chuột",
                     "ốc bươu", "oc buou", "ốc", "con ốc", "ốc ăn", "ốc phá", "dịch hại", "bệnh", "nấm",
                     "nhiễm nấm", "bị nấm", "đốm", "lem lép", "đạo ôn", "khô vằn",
                     "bạc lá", "vàng lùn", "lùn xoắn", "vi khuẩn", "vi rút", "virus", "chữa", "chữa trị",
                     "điều trị", "triệu chứng", "thuốc", "thuoc nao", "loai thuoc", "mua thuoc", "hoạt chất",
                     "kháng sinh", "phun", "xịt", "diệt", "trừ sâu", "vôi"),
    "straw": ("rơm", "rơm rạ", "đốt rơm"),
    "weed": ("cỏ dại", "lúa cỏ", "lúa ma"),
    # Salinity changes what irrigation advice is safe (AWD can draw salt in): no stored rule covers it.
    # Seed variety, sowing density and acid soil are NOT here: "giống lúa này có hợp AWD không" is an
    # AWD question (agy review 2026-11-08); a pure seed question names no covered subject anyway.
    "other_agronomy": ("nhiễm mặn", "độ mặn", "xâm nhập mặn"),
    # Bare "bán" is not here: "bán lúa xong cần ghi số liệu gì" is a records question.
    "credit_market": ("tín chỉ", "đạt chuẩn", "mrv", "thị trường", "giá bán", "bán tín chỉ", "hồ sơ tín chỉ",
                      "hồ sơ chứng nhận"),
    # The assistant attests nothing: no certificate, confirmation, guarantee or judgement that a
    # practice the farmer describes is correct; and a lender's or appraiser's request is not a
    # farming question. Accent-free "co dung" (có dùng) / "dung ky thuat" (dùng kỹ thuật) are
    # legitimate requests, so the correctness phrases match only WITH accents (see AMBIGUOUS_FOLDS).
    # "Làm sao tưới đúng kỹ thuật" is a how-to question; only a request to JUDGE the farmer's own
    # practice ("như vậy có đúng kỹ thuật không") is attestation. "đủ điều kiện" is absent: "ruộng có
    # đủ điều kiện áp dụng AWD không" is a legitimate suitability question.
    "attestation": ("xác nhận", "xác thực", "chứng nhận", "chứng thực", "công nhận", "nghiệm thu",
                    "đủ tiêu chuẩn", "đạt tiêu chuẩn", "cam kết", "bảo lãnh", "giải ngân", "ngân hàng",
                    "thẩm định", "bảo hiểm", "khoản vay", "vay vốn", "có đúng kỹ thuật", "đúng kỹ thuật không",
                    "đúng kỹ thuật chưa", "như vậy có đúng", "làm vậy có đúng", "vậy có đúng không",
                    "sai kỹ thuật"),
    "coercion": ("bằng không", "không cần hệ thống", "tự tính", "bịa", "không giới hạn", "bỏ giới hạn", "admin",
                 "override", "quản trị viên", "nhà phát triển", "developer", "quên hết", "kê đơn"),
}
#: Folded spellings shared by unrelated common words ("ban" = bạn/bán, "thuoc" = thuộc/thuốc,
#: "chua" = chưa/chữa, "nam" = năm/nấm, "dung" = dùng/đúng …). In an accent-free question a
#: phrase made only of such words is NOT matched (it cannot be told apart); accented questions
#: are matched exactly, and accent-free questions still match the multi-word phrases.
AMBIGUOUS_FOLDS = frozenset({"ban", "oc", "thuoc", "chua", "nam", "lan", "dam", "tien", "von", "vay", "dung", "co",
                             "sai", "giong", "man", "bon", "phen"})
#: Phrases matched only in an accented question: their accent-free spelling is a legitimate request
#: ("co dung ky thuat awd" = "có dùng kỹ thuật AWD", do I use the AWD technique). A residual: an
#: accent-free request to judge a practice is not recognised (documented in RAG_V15_EVAL_PLAN.md).
ACCENTED_ONLY = frozenset({"có đúng kỹ thuật", "đúng kỹ thuật không", "đúng kỹ thuật chưa", "như vậy có đúng",
                           "làm vậy có đúng", "vậy có đúng không", "sai kỹ thuật", "liều lượng", "liều dùng"})
#: Multi-word phrases made only of ambiguous folds whose accent-free spelling has no common other
#: reading ("vay von" is not "vậy vốn" in practice): matched loose despite AMBIGUOUS_FOLDS.
LOOSE_OK = frozenset({"vay vốn"})

#: Words a "what should I do for this season" request is made of, WITH accents. A RECOMMEND/WHAT_IF
#: question made ONLY of these words names no other subject, so any stored rule may answer it
#: (the farmer chose the recommend intent). One word outside the list ("bị", "sâu", "côn trùng",
#: "xịt", …) and the question must name a subject the rule covers. Matched on the accent signature,
#: so "sâu" (pest) is not "sau" (after); a fully accent-free question is matched folded.
#: Courtesy ("xin chào", "cảm ơn", "giúp") carries no subject either.
GENERIC_WORDS = frozenset("""
tôi mình nhà chúng ta em anh chị bà con cô chú bác bạn
vụ này đó ruộng lúa mùa thửa đồng
nên cần phải có thể được hãy muốn
làm gì sao thế nào ra cải thiện ưu tiên việc điều cách gợi ý khuyến nghị đề xuất biện pháp phương án
trước tiếp theo bây giờ đầu hiện tại sắp tới tới
cho với của ở trên để tốt hơn ổn không chưa rồi vậy nhỉ ạ hả nha nhé đi
xin chào cảm ơn giúp hỏi ơi
""".split())
_GENERIC_SPELLINGS = None  # built lazily from GENERIC_WORDS

#: The assistant itself declines (folded): an optional subject + negation + a verb of advising, or
#: out of scope. Vietnamese drops the subject freely ("Không thể tư vấn …", "Xin phép không hướng
#: dẫn …"), so the subject is optional — but then only for verbs that mean ADVISING (a hedge such as
#: "không thể đưa ra con số chính xác" is not a refusal).
_SELF_REFUSAL = re.compile(
    r"(?<!\w)(?:"
    r"(?:toi|tro ly|he thong|chung toi|em|chung em|minh)\s+(?:khong the|khong|chua the|xin phep khong|tu choi)\s+"
    r"(?:tu van|huong dan|ke|dua ra|khuyen|cung cap|tra loi|xac nhan|chan doan|chi dinh|goi y)"
    r"|(?:khong the|chua the|xin phep khong|xin loi,? (?:toi )?khong the|rat tiec,? (?:toi )?khong the|tu choi)\s+"
    r"(?:tu van|huong dan|khuyen|goi y|chi dinh|ke don|chan doan|tra loi|giai dap|xac nhan)"
    r"|ngoai pham vi|khong thuoc pham vi|khong duoc phep tu van|khong nam trong pham vi)(?!\w)"
)

#: Treatment advice in the model's own text — never acceptable in an ACTION answer unless the
#: sentence is the assistant declining (`_SELF_REFUSAL`): the rules explain irrigation and record
#: keeping, nothing else. Matched on the accent signature like the subjects ("dữ liệu lượng nước"
#: folds to "...lieu luong..." but is not "liều lượng").
TREATMENT_PHRASES: dict[str, tuple[str, ...]] = {
    "treatment": ("phun thuốc", "xịt thuốc", "thuốc trừ", "thuốc bảo vệ thực vật", "thuốc bvtv", "thuốc diệt",
                  "thuốc trị", "hoạt chất", "liều lượng", "liều dùng", "kê đơn", "nên phun", "hãy phun", "nên xịt",
                  "hãy xịt"),
}

#: Subjects a GENERATED answer's own prose may not discuss outside a refusal sentence: disease and
#: pest handling, and attestation ("đã đủ điều kiện để công nhận …"). The rules explain irrigation
#: and records only (agy review 2026-11-08: "điều trị đạo ôn bằng vôi bột" passed the phrase list).
PROSE_FORBIDDEN_SUBJECTS = ("pest_disease", "attestation")

POLICY_REASONS = ("refusal_with_recommendation", "recommendation_off_topic", "unknown_rule_subject",
                  "treatment_advice", "answer_text_off_topic", "recommendation_text_off_topic",
                  "uncovered_question_answered")


def _words(text: str) -> list[tuple[str, tuple[str, ...]]]:
    out = []
    for word in re.findall(r"\w+", unicodedata.normalize("NFC", text or "").lower()):
        marks = sorted(ch for ch in unicodedata.normalize("NFD", word) if unicodedata.category(ch) == "Mn")
        out.append((fold(word), (*marks, "đ") if "đ" in word else tuple(marks)))
    return out


def _accentless(text: str) -> bool:
    return all(not marks for _, marks in _words(text))


def _windows(words, phrase_words, loose):
    n = len(phrase_words)
    for i in range(len(words) - n + 1):
        if all(w[0] == t[0] and (loose or w[1] == t[1]) for w, t in zip(words[i:i + n], phrase_words)):
            yield i, n


def _phrase_targets(phrase: str, loose: bool):
    target = _words(phrase)
    if loose and (phrase in ACCENTED_ONLY
                  or (phrase not in LOOSE_OK and all(t[0] in AMBIGUOUS_FOLDS for t in target))):
        return None  # cannot be told apart from a common word without accents
    return target


def question_subjects(question: str, vocabulary: dict[str, tuple[str, ...]] | None = None) -> frozenset[str]:
    words = _words(question)
    loose = _accentless(question)
    vocabulary = SUBJECT_PHRASES if vocabulary is None else vocabulary
    found = set()
    for subject, phrases in vocabulary.items():
        scan = words
        if subject == "data":
            scan = list(words)
            for phrase in NOT_DATA_PHRASES:
                target = _phrase_targets(phrase, loose)
                for i, n in (list(_windows(scan, target, loose)) if target else ()):
                    scan[i:i + n] = [("\0", ())] * n
        for phrase in phrases:
            target = _phrase_targets(phrase, loose)
            if target and next(_windows(scan, target, loose), None) is not None:
                found.add(subject)
                break
    return frozenset(found)


def uncovered_subjects(question: str) -> frozenset[str]:
    """Subjects of `question` that NO stored rule covers (pest/disease, straw, weed, salinity/seed,
    credits/markets, attestation, coercion)."""
    return question_subjects(question, UNCOVERED_SUBJECT_PHRASES)


def uncovered_question_refusal(question: str) -> str | None:
    """Second pre-model layer for ACTION questions (after `question_scope.action_question_refusal`):
    a question naming a subject no stored rule covers cannot be answered by any recommendation, so
    no season data and no question reaches the provider. Coercion -> `instruction_like_question`,
    anything else -> `out_of_scope_question`."""
    subjects = uncovered_subjects(question)
    if not subjects:
        return None
    return "instruction_like_question" if "coercion" in subjects else "out_of_scope_question"


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


def _model_texts(answer: GeneratedAnswer) -> list[str]:
    texts = [answer.answer, answer.rationale or "", *answer.limitations]
    for rec in answer.recommendations:
        texts += [rec.title, *rec.actions]
    return texts


def _sentences(texts: Iterable[str]) -> list[str]:
    return [s for text in texts for s in re.split(r"(?<=[.!?;:])\s+|\n+", text or "") if s.strip()]


def treatment_advice(answer: GeneratedAnswer) -> bool:
    """A sentence of the model's text gives treatment advice and is not the assistant declining."""
    return any(question_subjects(s, TREATMENT_PHRASES) and not self_refusal((s,))
               for s in _sentences(_model_texts(answer)))


def prose_off_topic(answer: GeneratedAnswer) -> bool:
    """A GENERATED answer whose own prose (answer, rationale, limitations) discusses pest/disease or
    attests something, outside a refusal sentence. Fails closed: an answer that merely mentions a
    disease ("AWD không làm tăng bệnh") is also refused. A declined answer is not judged here (it
    may name the subject it declines)."""
    if answer.status != "generated":
        return False
    vocabulary = {k: UNCOVERED_SUBJECT_PHRASES[k] for k in PROSE_FORBIDDEN_SUBJECTS}
    texts = [answer.answer, answer.rationale or "", *answer.limitations]
    return any(question_subjects(s, vocabulary) and not self_refusal((s,)) for s in _sentences(texts))


def rule_answers_question(rule_code: str, asked: frozenset[str], generic: bool) -> bool | None:
    """True when a stored rule answers what was asked; None when the rule has no declared subject."""
    subjects = RULE_SUBJECTS.get(rule_code)
    if subjects is None:
        return None
    if generic:
        return True
    asked_domains = asked & DOMAIN_SUBJECTS
    if rule_code.startswith(DATA_RULE_PREFIX):
        # A records question, and if it names a domain, the rule's own domain.
        return "data" in asked and (not asked_domains or bool(subjects & asked_domains))
    return bool(subjects & asked_domains)


def answer_policy_violation(question: str, answer: GeneratedAnswer) -> str | None:
    """None when the answer is consistent; otherwise a sanitized reason code (POLICY_REASONS)."""
    if treatment_advice(answer):
        return "treatment_advice"
    if answer.recommendations and self_refusal((answer.answer, answer.rationale)):
        return "refusal_with_recommendation"  # the R3 shape: named first, it is the precise diagnosis
    if prose_off_topic(answer):
        return "answer_text_off_topic"
    declined_in_words = not answer.recommendations and self_refusal((answer.answer, answer.rationale))
    if answer.status == "generated" and not declined_in_words and uncovered_subjects(question):
        # The question is (also) about something no rule covers: no generated answer at all, with or
        # without a recommendation (normally refused before the model; this is the second line).
        return "recommendation_off_topic" if answer.recommendations else "uncovered_question_answered"
    if not answer.recommendations:
        return None
    if any(question_subjects(text, UNCOVERED_SUBJECT_PHRASES)
           for rec in answer.recommendations for text in (rec.title, *rec.actions)):
        return "recommendation_text_off_topic"  # the recommendation's own text leaves the rule's subject
    generic = is_generic_action_question(question)
    asked = question_subjects(question)
    for rec in answer.recommendations:
        if rec.rule_code is None:
            continue  # a missing rule_code is the structural rule gate's refusal (rag_qa), unchanged
        verdict = rule_answers_question(rec.rule_code, asked, generic)
        if verdict is None:
            return "unknown_rule_subject"
        if not verdict:
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
