"""Nạp bộ tham số phương pháp luận từ YAML.

Ràng buộc SRS RB-01: hệ số là DỮ LIỆU, không phải code. Module này là con đường duy nhất
để engine lấy tham số — không có hằng số phát thải nào viết thẳng trong logic tính.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import MissingEmissionFactorError

STATUS_VERIFIED = "VERIFIED"

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "emission_factors.yaml"


@dataclass(frozen=True)
class Parameter:
    """Một tham số đã nạp, kèm nguồn và trạng thái xác minh."""

    path: str
    value: float
    unit: str | None
    source: str | None
    status: str
    uncertainty_range: str | None = None

    @property
    def is_verified(self) -> bool:
        return self.status == STATUS_VERIFIED


@dataclass(frozen=True)
class Methodology:
    name: str
    version: str | None
    tier: int | None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "tier": self.tier}


@dataclass(frozen=True)
class ParameterSet:
    """Bộ tham số của một phiên bản config."""

    version: str
    review_date: str | None
    methodology: Methodology
    _root: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path | None = None) -> ParameterSet:
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(config_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        meta = raw.get("methodology") or {}
        return cls(
            version=str(raw.get("version", "unknown")),
            review_date=raw.get("review_date"),
            methodology=Methodology(
                name=meta.get("name", "unknown"),
                version=meta.get("version"),
                tier=meta.get("tier"),
            ),
            _root=raw,
        )

    def get(self, *path: str) -> Parameter:
        """Lấy tham số theo đường dẫn, ví dụ `get("factors", "ch4_rice", "efc")`.

        Raise MissingEmissionFactorError khi thiếu key hoặc `value` là null —
        KHÔNG bao giờ trả giá trị mặc định (SRS NFR-03).
        """
        dotted = ".".join(path)
        node: Any = self._root
        for key in path:
            if not isinstance(node, dict) or key not in node:
                raise MissingEmissionFactorError(
                    f"{dotted} không có trong bộ tham số '{self.version}'."
                )
            node = node[key]

        if not isinstance(node, dict):
            raise MissingEmissionFactorError(f"{dotted} không phải một mục tham số hợp lệ.")

        value = node.get("value")
        if value is None:
            raise MissingEmissionFactorError(
                f"{dotted} chưa được xác minh/cấu hình "
                f"(status={node.get('status', 'PENDING_VERIFICATION')}, "
                f"source={node.get('source', 'chưa có')}). "
                f"Xem docs/CARBON_METHOD_SOURCES.md."
            )

        return Parameter(
            path=dotted,
            value=float(value),
            unit=node.get("unit"),
            source=node.get("source"),
            status=node.get("status", "PENDING_VERIFICATION"),
            uncertainty_range=node.get("uncertainty_range"),
        )

    # -- lối tắt cho các nhóm hay dùng -------------------------------------

    def factor(self, *path: str) -> Parameter:
        return self.get("factors", *path)

    def gwp(self, gas: str) -> Parameter:
        """GWP để quy đổi sang CO2e. Hiện PENDING_VERIFICATION (OI-05)."""
        return self.get("gwp", gas)
