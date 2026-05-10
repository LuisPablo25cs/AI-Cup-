from src.schemas.inspect import Detection, InspectionResult


def evaluate(
    detections: list[Detection],
    expected: dict[str, int],
) -> InspectionResult:
    """Pure evaluator: compares detected counts against kit expectations.

    No I/O. No side effects. Returns an InspectionResult dataclass that the
    router uses to build the HTTP response.

    Pass/fail logic:
    - missing[c] = expected[c] - counts.get(c, 0)  for each c where > 0 (REQ-08)
    - extra[c]   = counts[c]  - expected.get(c, 0) for each c where > 0 (REQ-09, REQ-10)
    - result is "pass" iff missing == {} and extra == {}              (REQ-07)
    """
    # Aggregate counts from filtered detections (confidence already applied by router)
    counts: dict[str, int] = {}
    for det in detections:
        counts[det.class_label] = counts.get(det.class_label, 0) + 1

    # Classes present in expected but missing or short in counts
    missing: dict[str, int] = {}
    for cls, qty in expected.items():
        deficit = qty - counts.get(cls, 0)
        if deficit > 0:
            missing[cls] = deficit

    # Classes with more than expected (covers both unknown classes and over-count)
    extra: dict[str, int] = {}
    for cls, qty in counts.items():
        surplus = qty - expected.get(cls, 0)
        if surplus > 0:
            extra[cls] = surplus

    result = "pass" if not missing and not extra else "fail"

    return InspectionResult(
        result=result,
        counts=counts,
        missing=missing,
        extra=extra,
    )
