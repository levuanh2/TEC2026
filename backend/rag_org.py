"""PROTOTYPE — organization-level (HTX) Q&A, READ only. Not wired to any route.

Authorization contract (separate from the season endpoint's, which is unchanged):
1. Identity is the caller's JWT only (`reader.me()`: GoTrue user + RLS on the caller's own
   membership rows, ACTIVE memberships only — ended ones are dropped server-side).
2. The request's organization_id is a SELECTOR, never evidence of access: the caller must hold
   an active membership in exactly that organization with an organization READ role
   (`cooperative_manager`). Anything else — non-member, former member, farmer role,
   another HTX, pending password change — is `not_found` (404), indistinguishable.
3. Every number comes from an existing caller-scoped aggregate read
   (`organization_summary`, `organization_plots_and_seasons`, `metrics_for_seasons`), all
   under the caller's JWT and RLS. Nothing is read with the service role, nothing is
   re-aggregated here, a missing value stays "chưa có dữ liệu" (never 0).
4. No action intents (managers have no Core V1 WRITE on farms), no model text (strategy B
   templates), nothing persisted. Large organizations are paginated (`PAGE_SIZE`); a failing
   metrics read degrades to `partial` and names how many seasons are unknown.
Knowledge retrieval at organization scope needs an org-scoped RPC (a new migration with its
own approval) and is deliberately absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from recommendation.rag.errors import RagAccessDenied

ORG_READ_ROLES = frozenset({"cooperative_manager"})
PAGE_SIZE = 50
MAX_PAGE = 200  # 10 000 seasons; beyond that a filter is required
INTENTS = ("org_summary", "org_data_gaps")
MISSING = "chưa có dữ liệu"
_GAP_LABELS = (("water", "lượng nước tưới"), ("fertilizer", "phân bón"), ("cost", "chi phí"))


@dataclass(frozen=True)
class OrgScope:
    actor_id: str
    organization_id: str
    role: str


class CallerOrgScopeResolver:
    def __init__(self, reader: Any) -> None:
        self._reader = reader

    def resolve(self, organization_id: str) -> OrgScope:
        me = self._reader.me()
        if me.get("must_change_password"):
            raise RagAccessDenied("password change pending")
        for m in me.get("organization_memberships") or ():
            if str(m.get("organization_id")) == str(organization_id) and m.get("role") in ORG_READ_ROLES:
                return OrgScope(str(me["user_id"]), str(organization_id), str(m["role"]))
        raise RagAccessDenied("no active organization read role for this organization")


def _num(value: Any, unit: str) -> str:
    if value is None:
        return MISSING
    text = f"{float(value):,.2f}".rstrip("0").rstrip(".").replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} {unit}".strip()


class OrgQuestionService:
    """Deterministic organization answers; `reader` is the caller-bound read repository."""

    def answer(self, *, reader: Any, organization_id: str, intent: str, page: int = 0) -> dict[str, Any]:
        if intent not in INTENTS:
            raise RagAccessDenied("unknown organization intent")
        if not (0 <= page <= MAX_PAGE):
            raise RagAccessDenied("page out of range")
        scope = CallerOrgScopeResolver(reader).resolve(organization_id)
        body = self._summary(reader, scope) if intent == "org_summary" else self._gaps(reader, scope, page)
        body.update(intent=intent, organization_id=scope.organization_id,
                    provenance={"answer_source": "system_composed", "llm_calls": 0, "persisted": False})
        return body

    def _summary(self, reader: Any, scope: OrgScope) -> dict[str, Any]:
        s = reader.organization_summary(scope.organization_id)
        if str(s.get("organization_id")) != scope.organization_id:
            raise RagAccessDenied("summary of another organization")
        facts = {k: s.get(k) for k in ("farm_count", "plot_count", "crop_season_count", "total_area_ha",
                                       "total_yield_kg", "total_co2e_kg", "co2e_per_kg")}
        sentences = [
            f"HTX có {facts['farm_count']} nông hộ, {facts['plot_count']} thửa và {facts['crop_season_count']} vụ "
            f"mà bạn được xem.",
            f"Tổng diện tích: {_num(facts['total_area_ha'], 'ha')}.",
            f"Tổng sản lượng đã ghi nhận: {_num(facts['total_yield_kg'], 'kg')}.",
            f"Tổng phát thải đã tính: {_num(facts['total_co2e_kg'], 'kg CO2e')}; trên sản lượng: "
            f"{_num(facts['co2e_per_kg'], 'kg CO2e/kg')}.",
        ]
        limitations = ["Tổng chỉ được cộng khi mọi vụ đều có số liệu; thiếu một vụ thì ghi là chưa có dữ liệu.",
                       "Số liệu phát thải là ước tính theo hệ số mặc định IPCC Tier 1, chưa đạt yêu cầu MRV."]
        return {"status": "generated", "answer": " ".join(sentences), "facts": facts, "limitations": limitations,
                "partial": False}

    def _gaps(self, reader: Any, scope: OrgScope, page: int) -> dict[str, Any]:
        seasons = sorted((s for farm in reader.organization_plots_and_seasons(scope.organization_id)
                          for s in farm.get("crop_seasons") or ()), key=lambda s: str(s["id"]))
        total = len(seasons)
        window = seasons[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        ids = [str(s["id"]) for s in window]
        partial, metrics = False, {}
        try:
            metrics = reader.metrics_for_seasons(ids) if ids else {}
        except Exception:  # noqa: BLE001 - a failing aggregate read degrades, never invents
            partial = True
        gaps: dict[str, list[str]] = {key: [] for key, _ in _GAP_LABELS}
        gaps["yield"], unknown = [], []
        for s in window:
            m = metrics.get(str(s["id"]))
            code = str(s.get("season_code") or s["id"])
            if m is None:
                unknown.append(code)
                continue
            completeness = m.get("data_completeness") or {}
            for key, _ in _GAP_LABELS:
                if completeness.get(key) is not True:
                    gaps[key].append(code)
            if m.get("yield_kg") is None:
                gaps["yield"].append(code)
        sentences = [f"Trang {page + 1}: {len(window)} trên tổng {total} vụ của HTX."]
        for key, label in (*_GAP_LABELS, ("yield", "sản lượng thu hoạch")):
            if gaps[key]:
                sentences.append(f"{len(gaps[key])} vụ chưa đủ dữ liệu {label}: {', '.join(gaps[key][:10])}"
                                 + (" …" if len(gaps[key]) > 10 else "") + ".")
        if unknown:
            sentences.append(f"Chưa đọc được số liệu của {len(unknown)} vụ; vui lòng thử lại sau." if partial
                             else f"{len(unknown)} vụ chưa có số liệu.")
        return {"status": "partial" if partial else "generated", "answer": " ".join(sentences),
                "facts": {"gaps": gaps, "unknown": unknown}, "partial": partial, "limitations": [],
                "page": {"page": page, "size": PAGE_SIZE, "total": total,
                         "has_more": (page + 1) * PAGE_SIZE < total}}

