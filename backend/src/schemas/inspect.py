from dataclasses import dataclass, field

from pydantic import BaseModel


class Detection(BaseModel):
    class_label: str
    confidence: float
    bbox_xyxy_norm: list[float]


class InspectionResponse(BaseModel):
    kit_id: str
    result: str  # "pass" | "fail"
    detections: list[Detection]
    counts: dict[str, int]
    expected: dict[str, int]
    missing: dict[str, int]
    extra: dict[str, int]
    model_version: str
    inference_ms: int


@dataclass
class InspectionResult:
    """Internal dataclass returned by inspection.evaluate().

    Used to transfer evaluation data between the service layer and the router
    without exposing Pydantic models to pure business logic.
    """

    result: str  # "pass" | "fail"
    counts: dict[str, int] = field(default_factory=dict)
    missing: dict[str, int] = field(default_factory=dict)
    extra: dict[str, int] = field(default_factory=dict)
