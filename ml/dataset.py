"""torch Dataset doc manifest CSV (filepath,label) do ml/dataset_prep.py sinh ra."""

from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image
from torch.utils.data import Dataset

from ml.class_mapping import LABEL_TO_INDEX

REPO_ROOT = Path(__file__).resolve().parent.parent


class ManifestImageDataset(Dataset):
    def __init__(self, manifest_csv: str | Path, transform=None):
        self.rows: list[tuple[str, str]] = []
        with open(manifest_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.rows.append((row["filepath"], row["label"]))
        self.transform = transform

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int):
        filepath, label = self.rows[idx]
        # Manifest luu duong dan tuong doi tu repo root (xem dataset_prep.py);
        # ho tro ca duong dan tuyet doi cu (backward-compat manifest cu).
        resolved = filepath if Path(filepath).is_absolute() else str(REPO_ROOT / filepath)
        image = Image.open(resolved).convert("RGB")
        if self.transform is not None:
            image = self.transform(image)
        return image, LABEL_TO_INDEX[label]
