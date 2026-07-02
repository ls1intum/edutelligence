from iris.domain.struggle.struggle_signal_dto import StruggleSignal


def test_struggle_signal_parses_camelcase_wire_payload():
    payload = {
        "alert": {
            "tSessionS": 540,
            "primaryBoundary": "FM",
            "boundaryTypes": ["FM", "STATE"],
            "severity": 0.72,
            "path": "armed",
            "inWarmup": False,
            "inGrace": False,
        },
        "trajectory": [{"t": 520, "s": 0.5, "v": 0.6}, {"t": 530, "s": 0.6, "v": 0.7}],
        "dominantComponents": [{"name": "feedbackViewing", "value": 0.8}],
        "sessionSeconds": 540,
    }
    sig = StruggleSignal.model_validate(payload)
    assert sig.alert.primary_boundary == "FM"
    assert sig.alert.severity == 0.72
    assert sig.trajectory[1].v == 0.7
    assert sig.dominant_components[0].name == "feedbackViewing"
