import os
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any
from ultralytics import YOLO

from .config import config
from .dataset_builder import Dataset

@dataclass(frozen=True)
class TrainingResult:
    best_weights: Path
    metrics: Dict[str, float]
    epochs_completed: int


class ModelFactory:
    def __init__(self):
        self.base_model = config.BASE_MODEL

    def train(self, dataset: Dataset, model_id: str) -> TrainingResult:
        """
        Executes YOLOv8n-seg training with specialized augmentations for sim-to-real gap.
        """
        model = YOLO(self.base_model)
        
        # Setup specific output project/run directories
        run_name = f"train_{model_id}"
        project_dir = config.WORKSPACE_DIR / "runs"
        
        # Hyperparameters & Sim-To-Real Augmentations
        train_args = {
            "data": str(dataset.yaml_path),
            "epochs": config.TRAIN_EPOCHS,
            "patience": config.TRAIN_PATIENCE,
            "imgsz": config.TRAIN_IMGSZ,
            "batch": -1,                      # Auto-batch size matching hardware VRAM limit
            "device": config.DEVICE,
            "project": str(project_dir),
            "name": run_name,
            "exist_ok": True,
            
            # Regularization & Optimization
            "freeze": 10,                     # Backbone transfer learning freeze
            "erasing": 0.3,                   # Random erasing for occlusion handling
            "scale": 0.5,                     # Scaled variants
            
            # Sim-to-Real Color Gap Adjustments
            "hsv_h": 0.015,                   # Hue modulation
            "hsv_s": 0.7,                     # Saturation shifts
            "hsv_v": 0.4,                     # Brightness shifts (heightened for light/shadows)
            
            # Geometric Transformations
            "degrees": float(os.getenv("TRAIN_DEGREES", "180.0")),  # Complete rotation override
            "translate": 0.2,                 # Translational shifts
            "shear": 10.0,                    # Shearing skew
            "perspective": 0.001,             # Perspective warps
            
            # Segment-specific compositing
            "mosaic": 1.0,                    # Mosaic composite stitching
            "copy_paste": 0.1,                # Segment instance overlay pasting
            "mixup": 0.1,                     # Image blend ratios
            "plots": True,
            "verbose": True
        }

        # Train model
        results = model.train(**train_args)
        
        best_pt_path = project_dir / run_name / "weights" / "best.pt"
        if not best_pt_path.exists():
            raise FileNotFoundError(f"Training finalized but best weights file was not saved at {best_pt_path}")

        # Standardized MLOps metrics extraction
        raw_metrics = results.results_dict
        clean_metrics = {
            "box_map50": float(raw_metrics.get("metrics/mAP50(B)", 0.0)),
            "box_map50_95": float(raw_metrics.get("metrics/mAP50-95(B)", 0.0)),
            "seg_map50": float(raw_metrics.get("metrics/mAP50(M)", 0.0)),
            "seg_map50_95": float(raw_metrics.get("metrics/mAP50-95(M)", 0.0)),
            "fitness": float(raw_metrics.get("fitness", 0.0))
        }

        epochs_completed = getattr(results, "epoch", config.TRAIN_EPOCHS)

        return TrainingResult(
            best_weights=best_pt_path,
            metrics=clean_metrics,
            epochs_completed=epochs_completed
        )