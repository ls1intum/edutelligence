from iris.domain.data.video_source_type import VideoSourceType


def test_values_match_wire_format():
    assert VideoSourceType.TUM_LIVE.value == "TUM_LIVE"
    assert VideoSourceType.YOUTUBE.value == "YOUTUBE"


def test_is_str_enum_for_json_round_trip():
    # StrEnum compatibility: value equals the enum member when compared as string
    assert VideoSourceType("YOUTUBE") == VideoSourceType.YOUTUBE
    assert VideoSourceType("TUM_LIVE") == VideoSourceType.TUM_LIVE
