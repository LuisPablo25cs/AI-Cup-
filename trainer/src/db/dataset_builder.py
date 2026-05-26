import shutil
import hashlib
from uuid import uuid4
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Tuple, Protocol
import random

from .s3_client import S3Client
from .db_client import TrainingSample

@dataclass(frozen=True)
class Dataset:
    root_dir: Path
    yaml_path: Path
    class_names: Dict[int, str]
    num_train: int
    num_val: int
    fingerprint: str

    def cleanup(self) -> None:
        """Deletes the entire local dataset directory to conserve workspace disk space."""
        if self.root_dir.exists():
            shutil.rmtree(self.root_dir)


class SplitStrategy(Protocol):
    def split(self, samples: List[TrainingSample], train_ratio: float) -> Tuple[List[TrainingSample], List[TrainingSample]]:
        """Splits training samples into train and validation sets."""
        ...


class RandomSplit:
    """Naive randomized split."""
    def split(self, samples: List[TrainingSample], train_ratio: float) -> Tuple[List[TrainingSample], List[TrainingSample]]:
        shuffled = list(samples)
        random.shuffle(shuffled)
        split_idx = int(len(shuffled) * train_ratio)
        return shuffled[:split_idx], shuffled[split_idx:]


class StratifiedSplit:
    """
    Prevents data leakage. Groups samples by render_set_id, ensuring
    all variants (sin_bolsa, con_bolsa_clear, etc.) from the same camera/background setup
    always end up together inside either train or val.
    """
    def split(self, samples: List[TrainingSample], train_ratio: float) -> Tuple[List[TrainingSample], List[TrainingSample]]:
        groups: Dict[str, List[TrainingSample]] = {}
        for sample in samples:
            groups.setdefault(sample.render_set_id, []).append(sample)
        
        group_keys = list(groups.keys())
        random.shuffle(group_keys)

        train_groups_count = int(len(group_keys) * train_ratio)
        # Guarantee validation set has at least one group if ratio allows it
        if train_groups_count == len(group_keys) and train_ratio < 1.0 and len(group_keys) > 1:
            train_groups_count = len(group_keys) - 1

        train_keys = group_keys[:train_groups_count]
        val_keys = group_keys[train_groups_count:]

        train_samples = []
        for k in train_keys:
            train_samples.extend(groups[k])
            
        val_samples = []
        for k in val_keys:
            val_samples.extend(groups[k])

        return train_samples, val_samples


@dataclass
class PieceSpec:
    piece_id: str
    class_index: int
    class_name: str
    samples: List[TrainingSample]


class DatasetBuilder:
    def __init__(self, s3_client: S3Client, base_dir: Path):
        self._s3 = s3_client
        self._base_dir = base_dir
        self._pieces: List[PieceSpec] = []
        self._split_strategy: SplitStrategy = StratifiedSplit()
        self._train_ratio: float = 0.80

    def add_piece(self, piece_id: str, class_index: int, class_name: str, samples: List[TrainingSample]) -> "DatasetBuilder":
        self._pieces.append(PieceSpec(piece_id, class_index, class_name, samples))
        return self

    def with_split_strategy(self, strategy: SplitStrategy) -> "DatasetBuilder":
        self._split_strategy = strategy
        return self

    def with_train_ratio(self, ratio: float) -> "DatasetBuilder":
        if not (0.0 <= ratio <= 1.0):
            raise ValueError("Train ratio must be between 0.0 and 1.0")
        self._train_ratio = ratio
        return self

    def _remap_label_class(self, src_label_path: Path, dest_label_path: Path, new_class_index: int) -> None:
        """Reads a label from S3 (which defaults to index 0) and maps it to the target multi-class index."""
        if not src_label_path.exists():
            return
        
        with open(src_label_path, "r") as rf:
            lines = rf.readlines()

        remapped_lines = []
        for line in lines:
            parts = line.strip().split()
            if not parts:
                continue
            # YOLO format: class_index x1 y1 x2 y2 ...
            parts[0] = str(new_class_index)
            remapped_lines.append(" ".join(parts) + "\n")

        dest_label_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_label_path, "w") as wf:
            wf.writelines(remapped_lines)

    def build(self) -> Dataset:
        if not self._pieces:
            raise ValueError("Cannot build dataset without pieces. Call .add_piece() first.")

        dataset_uuid = str(uuid4())
        dataset_dir = self._base_dir / f"dataset_{dataset_uuid}"
        
        # Setup final folders
        img_train_dir = dataset_dir / "images" / "train"
        img_val_dir = dataset_dir / "images" / "val"
        lbl_train_dir = dataset_dir / "labels" / "train"
        lbl_val_dir = dataset_dir / "labels" / "val"

        for d in [img_train_dir, img_val_dir, lbl_train_dir, lbl_val_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Temporary folder for labels download before remapping
        temp_dir = dataset_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        class_names: Dict[int, str] = {}
        num_train = 0
        num_val = 0
        fingerprint_inputs = []

        for piece in self._pieces:
            class_names[piece.class_index] = piece.class_name
            
            # Apply the split strategy
            train_samples, val_samples = self._split_strategy.split(piece.samples, self._train_ratio)
            
            # Record dataset fingerprint components deterministically
            for sample in sorted(piece.samples, key=lambda s: s.image_key):
                fingerprint_inputs.append(f"{piece.class_index}:{sample.image_key}:{sample.label_key}")

            # Assemble splits
            for split_name, samples_list, dest_img_dir, dest_lbl_dir in [
                ("train", train_samples, img_train_dir, lbl_train_dir),
                ("val", val_samples, img_val_dir, lbl_val_dir)
            ]:
                for sample in samples_list:
                    # Rename images and labels uniquely on disk to avoid conflicts across piece sets
                    local_img_name = f"{piece.class_name}_{sample.render_set_id}_{sample.variante}.jpg"
                    local_lbl_name = f"{piece.class_name}_{sample.render_set_id}_{sample.variante}.txt"
                    
                    local_img_path = dest_img_dir / local_img_name
                    dest_lbl_path = dest_lbl_dir / local_lbl_name
                    
                    # 1. Download image
                    self._s3.download_file(sample.image_key, local_img_path)
                    
                    # 2. Download label to temp, then remap to destination
                    temp_lbl_hash = hashlib.md5(sample.label_key.encode()).hexdigest()
                    temp_lbl_path = temp_dir / f"{temp_lbl_hash}.txt"
                    
                    if not temp_lbl_path.exists():
                        self._s3.download_file(sample.label_key, temp_lbl_path)
                    
                    self._remap_label_class(temp_lbl_path, dest_lbl_path, piece.class_index)
                    
                    if split_name == "train":
                        num_train += 1
                    else:
                        num_val += 1

        # Compute stable dataset hash
        fingerprint_raw = ",".join(fingerprint_inputs).encode("utf-8")
        fingerprint = hashlib.sha256(fingerprint_raw).hexdigest()

        # Clean temp folder
        shutil.rmtree(temp_dir, ignore_errors=True)

        # Write dataset.yaml for YOLO
        yaml_content = f"""
path: {dataset_dir.absolute().as_posix()}
train: images/train
val: images/val

names:
"""
        for idx in sorted(class_names.keys()):
            yaml_content += f"  {idx}: {class_names[idx]}\n"

        yaml_path = dataset_dir / "dataset.yaml"
        with open(yaml_path, "w") as f:
            f.write(yaml_content.strip())

        return Dataset(
            root_dir=dataset_dir,
            yaml_path=yaml_path,
            class_names=class_names,
            num_train=num_train,
            num_val=num_val,
            fingerprint=fingerprint
        )