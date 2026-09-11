"""Canonical label set cho M03 CV MVP.

Canonical labels PHAI khop enum DB `public.disease_label` trong
supabase/migrations/20260907000000_baseline.sql (dong 117-118):
    rice_blast, bacterial_leaf_blight, brown_spot, healthy, unknown

`unknown` KHONG phai class de train - day la ket qua khi confidence duoi
nguong (xem infer.py / FR-1b-04). Model chi phan loai 4 class ben duoi.
"""

from __future__ import annotations

# Thu tu co dinh -> dung lam thu tu index cho model output (index 0..3).
CANONICAL_LABELS = ["rice_blast", "bacterial_leaf_blight", "brown_spot", "healthy"]

LABEL_TO_INDEX = {label: i for i, label in enumerate(CANONICAL_LABELS)}
INDEX_TO_LABEL = {i: label for label, i in LABEL_TO_INDEX.items()}

# label tieng Viet - dung cho hien thi (khong dung trong model/DB).
LABEL_VI = {
    "rice_blast": "Đạo ôn",
    "bacterial_leaf_blight": "Bạc lá",
    "brown_spot": "Đốm nâu",
    "healthy": "Khỏe mạnh",
}

# Mapping ten thu muc goc trong dataset Mendeley (hx6f852hw4, "Original Images.zip")
# -> canonical label. Dataset co 8 class, chi 4 class duoi day khop PRD - 4 class
# con lai (Leaf Scald, Narrow Brown Leaf Spot, Rice Hispa, Sheath Blight) BI LOAI,
# khong dua vao train/eval. Xem ml/datasets/README.md de biet ten thu muc that
# (case/khoang trang co the khac - dataset_prep.py se chuan hoa ten truoc khi so sanh).
RAW_FOLDER_TO_CANONICAL = {
    "bacterial leaf blight": "bacterial_leaf_blight",
    "brown spot": "brown_spot",
    "leaf blast": "rice_blast",
    "healthy rice leaf": "healthy",
}


def normalize_folder_name(name: str) -> str:
    return " ".join(name.strip().lower().replace("_", " ").replace("-", " ").split())


def map_raw_folder_to_canonical(folder_name: str) -> str | None:
    """Tra ve canonical label hoac None neu folder khong thuoc 4 class can dung.

    Khong tu doan: chi map neu ten thu muc (sau normalize) khop chinh xac 1
    trong 4 key cua RAW_FOLDER_TO_CANONICAL.
    """
    return RAW_FOLDER_TO_CANONICAL.get(normalize_folder_name(folder_name))
