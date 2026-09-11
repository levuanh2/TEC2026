"""AgriCarbon CV - huan luyen baseline (M03 CV MVP).

Lop 1b. FR-1b-01: phan loai 4 nhan benh la lua.
Dac ta: docs/modules/03-computer-vision.md

Chay (tu thu muc goc repo):
    python -m ml.train
    python -m ml.train --epochs 20 --batch-size 32 --lr 1e-3 --image-size 224

Yeu cau: da chay `python -m ml.dataset_prep` truoc de co
ml/datasets/splits/{train,validation,test}.csv.

Khong hardcode absolute path - moi duong dan tinh tu vi tri file nay.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
import torchvision
from torch import nn
from torch.utils.data import DataLoader

from ml.class_mapping import CANONICAL_LABELS
from ml.dataset import ManifestImageDataset
from ml.model import build_model, build_transforms

ML_DIR = Path(__file__).resolve().parent
SPLITS_DIR = ML_DIR / "datasets" / "splits"
RUNS_DIR = ML_DIR / "runs"


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def run_epoch(model, loader, criterion, optimizer, device, train: bool) -> tuple[float, float]:
    model.train(mode=train)
    total_loss, correct, total = 0.0, 0, 0
    with torch.set_grad_enabled(train):
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            if train:
                optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            if train:
                loss.backward()
                optimizer.step()
            total_loss += loss.item() * images.size(0)
            correct += (outputs.argmax(dim=1) == labels).sum().item()
            total += images.size(0)
    return total_loss / total, correct / total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--run-name", type=str, default=None, help="mac dinh: mobilenetv2-baseline-<timestamp>")
    parser.add_argument("--unfreeze-backbone", action="store_true", help="fine-tune toan bo mang thay vi chi train classifier head")
    parser.add_argument("--backbone-lr", type=float, default=None, help="mac dinh: --lr / 10 (chi dung khi --unfreeze-backbone)")
    args = parser.parse_args()

    if not (SPLITS_DIR / "train.csv").exists():
        raise SystemExit("Chua co splits. Chay 'python -m ml.dataset_prep' truoc.")

    set_seed(args.seed)
    device = "cpu"

    run_name = args.run_name or f"mobilenetv2-baseline-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir = RUNS_DIR / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    train_ds = ManifestImageDataset(SPLITS_DIR / "train.csv", transform=build_transforms(args.image_size, train=True))
    val_ds = ManifestImageDataset(SPLITS_DIR / "validation.csv", transform=build_transforms(args.image_size, train=False))

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    model = build_model(pretrained=True, freeze_backbone=not args.unfreeze_backbone).to(device)
    criterion = nn.CrossEntropyLoss()
    if args.unfreeze_backbone:
        backbone_lr = args.backbone_lr if args.backbone_lr is not None else args.lr / 10
        optimizer = torch.optim.Adam([
            {"params": model.features.parameters(), "lr": backbone_lr},
            {"params": model.classifier.parameters(), "lr": args.lr},
        ])
    else:
        optimizer = torch.optim.Adam(model.classifier.parameters(), lr=args.lr)

    best_val_acc = -1.0
    history = []
    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = run_epoch(model, train_loader, criterion, optimizer, device, train=True)
        val_loss, val_acc = run_epoch(model, val_loader, criterion, optimizer, device, train=False)
        history.append({"epoch": epoch, "train_loss": train_loss, "train_acc": train_acc, "val_loss": val_loss, "val_acc": val_acc})
        print(f"epoch {epoch:02d}/{args.epochs} train_loss={train_loss:.4f} train_acc={train_acc:.4f} val_loss={val_loss:.4f} val_acc={val_acc:.4f}")

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            config = {
                "seed": args.seed,
                "framework": f"torch=={torch.__version__}",
                "torchvision": torchvision.__version__,
                "model": (
                    "mobilenet_v2 (ImageNet pretrained, fine-tuned end-to-end, linear head)"
                    if args.unfreeze_backbone
                    else "mobilenet_v2 (ImageNet pretrained, frozen backbone, linear head)"
                ),
                "image_size": args.image_size,
                "batch_size": args.batch_size,
                "learning_rate": args.lr,
                "backbone_learning_rate": (args.backbone_lr if args.backbone_lr is not None else args.lr / 10) if args.unfreeze_backbone else None,
                "unfreeze_backbone": args.unfreeze_backbone,
                "epochs_planned": args.epochs,
                "best_epoch": epoch,
                "train_count": len(train_ds),
                "validation_count": len(val_ds),
                "labels": CANONICAL_LABELS,
                "run_name": run_name,
            }
            torch.save({"model_state_dict": model.state_dict(), "config": config}, run_dir / "model.pt")

    (run_dir / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(f"\nDa luu checkpoint tot nhat (val_acc={best_val_acc:.4f}) vao {run_dir / 'model.pt'}")
    print(f"run_name: {run_name}")


if __name__ == "__main__":
    main()
