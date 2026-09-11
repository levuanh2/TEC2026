"""Chuan bi dataset cho M03 CV MVP: giai nen, loc 4 class, dedup, chia split.

Chay:
    python -m ml.dataset_prep

Doc file zip trong ml/datasets/raw/ (khong commit vao git - xem .gitignore),
giai nen, chi giu anh thuoc 4 class canonical (xem class_mapping.py), phat
hien anh trung lap/gan-trung-lap (de tranh data leakage giua cac split), roi
ghi ra manifest CSV (duong dan + label) cho train/validation/test. Manifest
CSV duoc commit (nho, chi la text) - anh that van nam trong raw/ (gitignore).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import zipfile
from collections import defaultdict
from pathlib import Path

from PIL import Image

from ml.class_mapping import CANONICAL_LABELS, map_raw_folder_to_canonical

ML_DIR = Path(__file__).resolve().parent
REPO_ROOT = ML_DIR.parent
RAW_DIR = ML_DIR / "datasets" / "raw"
EXTRACT_DIR = RAW_DIR / "extracted"
SPLITS_DIR = ML_DIR / "datasets" / "splits"

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def find_zip() -> Path:
    zips = sorted(RAW_DIR.glob("*.zip"))
    if not zips:
        raise SystemExit(
            f"Khong tim thay file .zip nao trong {RAW_DIR}. "
            "Tai 'Original Images.zip' tu https://data.mendeley.com/datasets/hx6f852hw4/2 truoc."
        )
    return zips[0]


def extract_if_needed(zip_path: Path) -> Path:
    marker = EXTRACT_DIR / ".extracted_ok"
    if marker.exists():
        return EXTRACT_DIR
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(EXTRACT_DIR)
    marker.write_text("ok", encoding="utf-8")
    return EXTRACT_DIR


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def average_hash(path: Path, hash_size: int = 8) -> int:
    """aHash don gian (chi dung PIL, khong them dependency) de bat near-duplicate."""
    with Image.open(path) as img:
        img = img.convert("L").resize((hash_size, hash_size), Image.LANCZOS)
        pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p >= avg else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def collect_images(extracted_root: Path) -> dict[str, list[Path]]:
    """Duyet toan bo cay thu muc, gom anh theo canonical label (bo qua 4 class thua)."""
    by_label: dict[str, list[Path]] = defaultdict(list)
    for path in extracted_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        label = map_raw_folder_to_canonical(path.parent.name)
        if label is None:
            continue
        by_label[label].append(path)
    return by_label


def dedup(by_label: dict[str, list[Path]], near_dup_threshold: int = 5) -> tuple[dict[str, list[Path]], dict]:
    """Loai anh trung het (sha256) va gom anh gan-trung (aHash) thanh group.

    Tra ve (by_label_deduped, stats). Anh gan-trung se duoc gan cung 1 group_id
    (dung khi chia split de ca group nam tron trong 1 split, tranh leakage).
    """
    stats = {"exact_duplicates_removed": 0}
    deduped: dict[str, list[Path]] = defaultdict(list)
    for label, paths in by_label.items():
        seen_hash: dict[str, Path] = {}
        unique_paths = []
        for p in paths:
            h = sha256_of(p)
            if h in seen_hash:
                stats["exact_duplicates_removed"] += 1
                continue
            seen_hash[h] = p
            unique_paths.append(p)
        deduped[label] = unique_paths
    return deduped, stats


def assign_near_dup_groups(paths: list[Path], threshold: int = 5) -> dict[Path, int]:
    """aHash O(n^2) tren tap da dedup exact - du nho (vai tram anh/class)."""
    hashes = {p: average_hash(p) for p in paths}
    group_of: dict[Path, int] = {}
    next_group = 0
    items = list(paths)
    for i, p in enumerate(items):
        if p in group_of:
            continue
        group_of[p] = next_group
        for q in items[i + 1:]:
            if q in group_of:
                continue
            if hamming(hashes[p], hashes[q]) <= threshold:
                group_of[q] = next_group
        next_group += 1
    return group_of


def stratified_group_split(
    paths: list[Path],
    group_of: dict[Path, int],
    ratios: tuple[float, float, float],
    rng: random.Random,
) -> dict[str, list[Path]]:
    groups: dict[int, list[Path]] = defaultdict(list)
    for p in paths:
        groups[group_of[p]].append(p)
    group_ids = list(groups.keys())
    rng.shuffle(group_ids)

    total = len(paths)
    train_target = round(total * ratios[0])
    val_target = round(total * ratios[1])

    split: dict[str, list[Path]] = {"train": [], "validation": [], "test": []}
    counts = {"train": 0, "validation": 0, "test": 0}
    for gid in group_ids:
        members = groups[gid]
        if counts["train"] < train_target:
            bucket = "train"
        elif counts["validation"] < val_target:
            bucket = "validation"
        else:
            bucket = "test"
        split[bucket].extend(members)
        counts[bucket] += len(members)
    return split


def write_manifest(rows: list[tuple[Path, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["filepath", "label"])
        for path, label in rows:
            # Duong dan tuong doi tu repo root - khong hardcode absolute path,
            # manifest van dung duoc tren may khac (miem la extract cung vi tri).
            writer.writerow([path.resolve().relative_to(REPO_ROOT).as_posix(), label])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--near-dup-threshold", type=int, default=5, help="aHash Hamming distance <= nguong -> coi la gan-trung-lap")
    args = parser.parse_args()

    test_ratio = 1.0 - args.train_ratio - args.val_ratio
    if test_ratio <= 0:
        raise SystemExit("train-ratio + val-ratio phai < 1.0")

    zip_path = find_zip()
    print(f"[1/5] Dung file zip: {zip_path.name}")
    extracted_root = extract_if_needed(zip_path)
    print(f"[2/5] Da giai nen vao: {extracted_root}")

    by_label = collect_images(extracted_root)
    missing = [c for c in CANONICAL_LABELS if c not in by_label or not by_label[c]]
    if missing:
        raise SystemExit(
            f"Khong tim thay anh cho class: {missing}. "
            "Kiem tra ten thu muc that trong zip va cap nhat RAW_FOLDER_TO_CANONICAL "
            "trong ml/class_mapping.py (KHONG tu doan mapping)."
        )
    print("[3/5] So anh theo class (truoc dedup):")
    for label in CANONICAL_LABELS:
        print(f"      {label}: {len(by_label[label])}")

    by_label, dedup_stats = dedup(by_label)
    print(f"[4/5] Dedup exact (sha256): loai {dedup_stats['exact_duplicates_removed']} anh trung het")

    rng = random.Random(args.seed)
    summary = {"seed": args.seed, "ratios": {"train": args.train_ratio, "validation": args.val_ratio, "test": test_ratio}, "classes": {}}
    manifest_rows: dict[str, list[tuple[Path, str]]] = {"train": [], "validation": [], "test": []}
    total_near_dup_groups = 0

    for label in CANONICAL_LABELS:
        paths = by_label[label]
        group_of = assign_near_dup_groups(paths, threshold=args.near_dup_threshold)
        n_groups = len(set(group_of.values()))
        total_near_dup_groups += n_groups
        split = stratified_group_split(paths, group_of, (args.train_ratio, args.val_ratio, test_ratio), rng)
        summary["classes"][label] = {
            "total_after_dedup": len(paths),
            "near_dup_groups": n_groups,
            "train": len(split["train"]),
            "validation": len(split["validation"]),
            "test": len(split["test"]),
        }
        for bucket in ("train", "validation", "test"):
            manifest_rows[bucket].extend((p, label) for p in split[bucket])

    for bucket in ("train", "validation", "test"):
        write_manifest(manifest_rows[bucket], SPLITS_DIR / f"{bucket}.csv")

    summary["dedup"] = dedup_stats
    summary["near_duplicate_groups_total"] = total_near_dup_groups
    (SPLITS_DIR / "split_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("[5/5] Da ghi manifest vao", SPLITS_DIR)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
