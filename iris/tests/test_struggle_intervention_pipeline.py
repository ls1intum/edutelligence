from iris.pipeline.struggle_intervention_pipeline import parse_gate_result


def test_parse_gate_result_active():
    raw = '{"action":"active","message":"Check the empty list.","confidence":0.81,"rationale":"FM"}'
    g = parse_gate_result(raw)
    assert g.action == "active"
    assert g.message == "Check the empty list."
    assert g.confidence == 0.81


def test_parse_gate_result_silent_when_unparseable_defaults_safe():
    g = parse_gate_result("the model rambled without json")
    assert g.action == "silent"
    assert g.message is None
    assert g.confidence == 0.0


def test_parse_gate_result_ambient():
    g = parse_gate_result(
        '{"action":"ambient","message":"re-read the spec","confidence":0.5}'
    )
    assert g.action == "ambient"
    assert g.message == "re-read the spec"
    assert g.confidence == 0.5


def test_parse_gate_result_invalid_action_defaults_silent():
    g = parse_gate_result('{"action":"shout","message":"x","confidence":0.9}')
    assert g.action == "silent"
    assert g.message is None
    assert g.confidence == 0.0


def test_parse_gate_result_coerces_string_confidence():
    g = parse_gate_result('{"action":"ambient","message":"hint","confidence":"0.9"}')
    assert g.confidence == 0.9


def test_parse_gate_result_non_silent_without_message_defaults_silent():
    g = parse_gate_result('{"action":"active","message":null,"confidence":0.8}')
    assert g.action == "silent"
    assert g.message is None
    assert g.confidence == 0.0


def test_parse_gate_result_rejects_non_finite_confidence():
    # json.loads accepts NaN/Infinity; the finite guard maps them to 0.0 so they
    # never reach the wire (a NaN/Infinity would break the JSON callback POST).
    nan = parse_gate_result('{"action":"ambient","message":"x","confidence":NaN}')
    inf = parse_gate_result('{"action":"ambient","message":"x","confidence":Infinity}')
    assert nan.confidence == 0.0
    assert inf.confidence == 0.0


def test_parse_gate_result_clamps_confidence_to_unit_range():
    high = parse_gate_result('{"action":"ambient","message":"x","confidence":5}')
    low = parse_gate_result('{"action":"ambient","message":"x","confidence":-2}')
    assert high.confidence == 1.0
    assert low.confidence == 0.0


def test_parse_gate_result_non_string_message_defaults_silent():
    g = parse_gate_result('{"action":"active","message":123,"confidence":0.8}')
    assert g.action == "silent"
    assert g.message is None


def test_parse_gate_result_drops_non_string_rationale():
    g = parse_gate_result(
        '{"action":"ambient","message":"x","confidence":0.5,"rationale":42}'
    )
    assert g.rationale is None
