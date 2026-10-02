"""A node's former profile files are handed to Logos once, then kept aside."""

from __future__ import annotations

from logos_worker_node.legacy_profile_import import mark_legacy_profiles_migrated, read_legacy_profiles


def test_nothing_to_hand_over(tmp_path):
    assert read_legacy_profiles(tmp_path) is None


def test_profiles_and_unsupported_list_are_read(tmp_path):
    (tmp_path / "model_profiles.yml").write_text("model_profiles:\n  org/a:\n    base_residency_mb: 5.0\n")
    logs = tmp_path / "calibration_logs"
    logs.mkdir()
    (logs / "calibration_unsupported_models.txt").write_text(
        "# header\n\norg/bad\tinvalid-repo-id\t2026-09-01T00:00:00Z\tdesc\norg/old\n"
    )
    assert read_legacy_profiles(tmp_path) == {
        "model_profiles": {"org/a": {"base_residency_mb": 5.0}},
        "unsupported_models": {"org/bad": "invalid-repo-id", "org/old": "unknown"},
    }


def test_an_unreadable_profile_file_still_hands_over_the_rest(tmp_path):
    (tmp_path / "model_profiles.yml").write_text("model_profiles:\n  org/a: {unterminated\n")
    assert read_legacy_profiles(tmp_path) == {"model_profiles": {}, "unsupported_models": {}}


def test_handed_over_files_are_renamed_not_deleted(tmp_path):
    (tmp_path / "model_profiles.yml").write_text("model_profiles: {}\n")
    mark_legacy_profiles_migrated(tmp_path)
    assert not (tmp_path / "model_profiles.yml").exists()
    assert (tmp_path / "model_profiles.yml.migrated").exists()
    assert read_legacy_profiles(tmp_path) is None
