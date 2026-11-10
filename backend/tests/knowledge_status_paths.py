"""Shared by the knowledge DB tests: how a fixture row legally reaches a status under RAG V1.5 M1
(migration 20261110090100). A row is inserted `review_required` and every later status is a
controlled, audited transition. Document versions pass expert_review before approval (D3);
sources approve directly. `db` is a psycopg connection or cursor of the operator / table owner.
"""

from __future__ import annotations

TRANSITION = {
    "source": "select private.knowledge_transition_source(%s, %s::public.knowledge_status,"
              " %s::public.knowledge_status, %s, %s)",
    "document": "select private.knowledge_transition_document(%s, %s::public.knowledge_status,"
                " %s::public.knowledge_status, %s, %s)",
}

_APPROVE_SOURCE = [("review_required", "approved")]
SOURCE_PATH = {
    "review_required": [],
    "rejected": [("review_required", "rejected")],
    "approved": _APPROVE_SOURCE,
    "archived": _APPROVE_SOURCE + [("approved", "archived")],
    "quarantined": _APPROVE_SOURCE + [("approved", "quarantined")],
}
_APPROVE_DOCUMENT = [("review_required", "expert_review"), ("expert_review", "approved")]
DOCUMENT_PATH = {
    "review_required": [],
    "rejected": [("review_required", "rejected")],
    "expert_review": [("review_required", "expert_review")],
    "approved": _APPROVE_DOCUMENT,
    "archived": _APPROVE_DOCUMENT + [("approved", "archived")],
    "quarantined": _APPROVE_DOCUMENT + [("approved", "quarantined")],
}


def transition(db, kind, key, frm, to, *, reason="fixture", approver=None):
    """One controlled transition; returns its event id. `approver` is required for an approval."""
    if to == "approved" and approver is None:
        raise ValueError("an approval names its approver")
    return db.execute(TRANSITION[kind], (key, frm, to, reason, approver if to == "approved" else None)).fetchone()[0]


def bring(db, kind, key, status, *, approver=None, reason="fixture"):
    """Move a freshly inserted (review_required) row to `status` along the legal path."""
    for frm, to in (SOURCE_PATH if kind == "source" else DOCUMENT_PATH)[status]:
        transition(db, kind, key, frm, to, reason=reason, approver=approver)
