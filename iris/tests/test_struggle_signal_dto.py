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
        "sessionSeconds": 540,
    }
    sig = StruggleSignal.model_validate(payload)
    assert sig.alert.primary_boundary == "FM"
    assert sig.alert.severity == 0.72
    assert sig.trajectory[1].s == 0.6


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
        "sessionSeconds": 540,
    }
    sig = StruggleSignal.model_validate(payload)
    assert sig.alert.primary_boundary == "TPS"
    assert sig.alert.boundary_types == ["TPS"]
    assert sig.alert.path == "discrete"
    assert sig.alert.in_warmup is True


def test_struggle_signal_ignores_stray_dominant_components_key():
    """A payload still carrying the removed dominantComponents key must parse fine:
    the model has no extra="forbid", so pydantic's default ignore-unknown-fields
    behavior means old senders (or a client mid-rollout) do not get a 422."""
    payload = {
        "alert": {
            "tSessionS": 540,
            "primaryBoundary": "FM",
            "boundaryTypes": ["FM"],
            "severity": 0.72,
            "path": "armed",
            "inWarmup": False,
            "inGrace": False,
        },
        "trajectory": [{"t": 520, "s": 0.5}],
        "dominantComponents": [{"name": "typing", "value": 0.8}],
        "sessionSeconds": 540,
    }
    sig = StruggleSignal.model_validate(payload)
    assert sig.alert.primary_boundary == "FM"
    assert not hasattr(sig, "dominant_components")
