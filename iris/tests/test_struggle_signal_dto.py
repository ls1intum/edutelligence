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
        "trajectory": [{"t": 520, "s": 0.5}, {"t": 530, "s": 0.6}],
        "dominantComponents": [{"name": "feedbackViewing", "value": 0.8}],
        "sessionSeconds": 540,
    }
    sig = StruggleSignal.model_validate(payload)
    assert sig.alert.primary_boundary == "FM"
    assert sig.alert.severity == 0.72
    assert sig.trajectory[1].s == 0.6
    assert sig.dominant_components[0].name == "feedbackViewing"


def test_struggle_signal_parses_tps_discrete_payload():
    # The discrete test-stagnation path sends primaryBoundary=TPS with path=discrete
    # (build-anchored, bypasses B4 -> inGrace is always false on the wire).
    payload = {
        "alert": {
            "tSessionS": 540,
            "primaryBoundary": "TPS",
            "boundaryTypes": ["TPS"],
            "severity": 0.41,
            "path": "discrete",
            "inWarmup": True,
            "inGrace": False,
        },
        "trajectory": [{"t": 530, "s": 0.4}],
        "dominantComponents": [{"name": "typing", "value": 0.3}],
        "sessionSeconds": 540,
    }
    sig = StruggleSignal.model_validate(payload)
    assert sig.alert.primary_boundary == "TPS"
    assert sig.alert.boundary_types == ["TPS"]
    assert sig.alert.path == "discrete"
    assert sig.alert.in_warmup is True
