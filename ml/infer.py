"""AgriCarbon CV - inference tren 1 anh (M03 CV MVP).

Chay:
    python -m ml.infer path/to/image.jpg
    python -m ml.infer path/to/image.jpg --checkpoint ml/runs/<run_name>/model.pt --threshold 0.5

Neu khong truyen --checkpoint, dung run moi nhat trong ml/runs/.
Neu khong truyen --threshold, dung confidence_threshold trong
ml/runs/<run_name>/eval_metrics.json (sinh boi ml/evaluate.py).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from PIL import Image
from torch import nn

from ml.class_mapping import INDEX_TO_LABEL, LABEL_VI
from ml.model import build_transforms, load_checkpoint

ML_DIR = Path(__file__).resolve().parent
RUNS_DIR = ML_DIR / "runs"


def find_latest_run() -> Path:
    runs = sorted((p for p in RUNS_DIR.iterdir() if (p / "model.pt").exists()), key=lambda p: p.stat().st_mtime)
    if not runs:
        raise SystemExit(f"Khong tim thay checkpoint nao trong {RUNS_DIR}. Chay 'python -m ml.train' truoc.")
    return runs[-1]


def resolve_threshold(run_dir: Path, override: float | None) -> float:
    if override is not None:
        return override
    eval_path = run_dir / "eval_metrics.json"
    if eval_path.exists():
        return json.loads(eval_path.read_text(encoding="utf-8"))["confidence_threshold"]
    raise SystemExit(
        f"Khong co --threshold va khong tim thay {eval_path}. "
        "Chay 'python -m ml.evaluate --checkpoint <checkpoint>' truoc, hoac truyen --threshold thu cong."
    )


def resolve_temperature(run_dir: Path, override: float | None) -> float:
    """Temperature scaling dung de calibrate confidence (xem ml/evaluate.py).
    PHAI dung cung temperature da dung khi chon threshold, neu khong threshold
    se sai lech (khong con khop voi phan phoi confidence da calibrate).
    """
    if override is not None:
        return override
    eval_path = run_dir / "eval_metrics.json"
    if eval_path.exists():
        return json.loads(eval_path.read_text(encoding="utf-8")).get("temperature", 1.0)
    return 1.0


@torch.no_grad()
def predict_with_model(
    image: Image.Image, model: nn.Module, config: dict, threshold: float, temperature: float = 1.0,
    *, device: str = "cpu", run_name: str | None = None,
) -> dict:
    """Run inference with an already-loaded model (backend usage: load once
    at startup via `ml.model.load_checkpoint`, reuse across requests — never
    reload the checkpoint per call). `image` must already be a decoded PIL
    Image in RGB mode; this function only applies the canonical eval
    transform (`ml.model.build_transforms`), never a second preprocessing
    path.
    """
    transform = build_transforms(config["image_size"], train=False)
    tensor = transform(image).unsqueeze(0).to(device)

    logits = model(tensor)
    probs = torch.softmax(logits / temperature, dim=1)[0]
    confidence, pred_idx = probs.max(dim=0)
    confidence = float(confidence)
    is_uncertain = confidence < threshold

    label = None if is_uncertain else INDEX_TO_LABEL[int(pred_idx)]
    return {
        "label": label,
        "label_vi": LABEL_VI.get(label) if label else None,
        "confidence": round(confidence, 6),
        "uncertain": is_uncertain,
        "model_version": run_name or config.get("run_name", "unknown"),
    }


def predict(image_path: str, checkpoint_path: Path, threshold: float, temperature: float = 1.0) -> dict:
    """CLI/legacy entrypoint: load a checkpoint from disk, run one prediction.
    For repeated inference (backend), load once with `ml.model.load_checkpoint`
    and call `predict_with_model` directly instead of this function.
    """
    model, config = load_checkpoint(str(checkpoint_path), device="cpu")
    image = Image.open(image_path).convert("RGB")
    return predict_with_model(
        image, model, config, threshold, temperature,
        run_name=config.get("run_name", Path(checkpoint_path).parent.name),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=str)
    parser.add_argument("--checkpoint", type=str, default=None)
    parser.add_argument("--threshold", type=float, default=None)
    args = parser.parse_args()

    run_dir = Path(args.checkpoint).parent if args.checkpoint else find_latest_run()
    checkpoint_path = Path(args.checkpoint) if args.checkpoint else run_dir / "model.pt"
    threshold = resolve_threshold(run_dir, args.threshold)
    temperature = resolve_temperature(run_dir, None)

    result = predict(args.image, checkpoint_path, threshold, temperature)

    print(f"label: {result['label'] if result['label'] else 'unknown'}")
    print(f"confidence: {result['confidence']}")
    print(f"uncertain: {result['uncertain']}")
    print(f"model_version: {result['model_version']}")


if __name__ == "__main__":
    main()
