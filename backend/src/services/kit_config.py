from pathlib import Path

from pydantic import BaseModel, RootModel


class KitConfig(BaseModel):
    model_path: str
    model_version: str
    confidence_threshold: float
    expected: dict[str, int]


KitsConfig = RootModel[dict[str, KitConfig]]


def load_kit_config(path: Path) -> KitsConfig:
    """Load and validate kit configuration from a JSON file.

    Raises:
        ValueError: If the file is missing, unreadable, or fails schema validation.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"models_config.json not found at {path}")
    except OSError as exc:
        raise ValueError(f"Cannot read models_config.json at {path}: {exc}") from exc

    try:
        return KitsConfig.model_validate_json(raw)
    except Exception as exc:
        raise ValueError(f"Invalid models_config.json schema: {exc}") from exc
