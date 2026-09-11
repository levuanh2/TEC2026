"""Kien truc model + transform dung chung cho train/evaluate/infer.

MobileNetV2 pretrain ImageNet, dong bang backbone, chi train classifier head.
Chon vi nhe, phu hop CPU-only va dataset nho (vai tram anh/class) - dung
transfer learning, khong can SOTA (yeu cau MVP).
"""

from __future__ import annotations

import torch
from torch import nn
from torchvision import transforms
from torchvision.models import MobileNet_V2_Weights, mobilenet_v2

from ml.class_mapping import CANONICAL_LABELS

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

NUM_CLASSES = len(CANONICAL_LABELS)


def build_model(pretrained: bool = True, freeze_backbone: bool = True) -> nn.Module:
    weights = MobileNet_V2_Weights.IMAGENET1K_V1 if pretrained else None
    model = mobilenet_v2(weights=weights)
    if freeze_backbone:
        for param in model.features.parameters():
            param.requires_grad = False
    in_features = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_features, NUM_CLASSES)
    return model


def build_transforms(image_size: int, train: bool) -> transforms.Compose:
    if train:
        return transforms.Compose([
            transforms.RandomResizedCrop(image_size, scale=(0.8, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.RandomRotation(15),
            transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ])
    return transforms.Compose([
        transforms.Resize(int(image_size * 1.14)),
        transforms.CenterCrop(image_size),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])


def load_checkpoint(checkpoint_path: str, device: str = "cpu") -> tuple[nn.Module, dict]:
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model = build_model(pretrained=False, freeze_backbone=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, checkpoint["config"]
