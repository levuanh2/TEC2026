"""Xuất OpenAPI schema hiện tại của backend ra docs/openapi.json.

Chạy: python backend/scripts/export_openapi.py
Không cần Supabase — chỉ import `app` (dependency_overrides không được set khi
thiếu .env, nhưng route vẫn khai báo đầy đủ trong OpenAPI vì đó là static schema
của FastAPI, không phụ thuộc runtime).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from main import app  # noqa: E402

if __name__ == "__main__":
    out_path = REPO_ROOT / "docs" / "openapi.json"
    out_path.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"OK: {out_path}")
