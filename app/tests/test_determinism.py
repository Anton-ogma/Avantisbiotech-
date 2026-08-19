"""Детерминизм и идемпотентность (§4 инварианты 1–2, §16)."""
from domain.analysis import SessionInput, TrialInput, analyze
from domain.hashing import canonical_json, file_hash, input_hash

BASE = {"PELVIC_TILT": 10.0, "KYPHOTIC_ANGLE_ICT_ITL": 45.0, "LATERAL_DEVIATION_RMS": 6.0}


def _session() -> SessionInput:
    return SessionInput("s1", "p1", "habitual_occlusion", True, [
        TrialInput("t1", "MAND_NEUTRAL_WITH_APPARATUS", "reference", 1, 0, True, BASE),
        TrialInput("t2", "MAND_CLENCH", "diagnostic", 1, 300, False,
            {**BASE, "LATERAL_DEVIATION_RMS": 9.5}),
        TrialInput("t3", "MAND_NEUTRAL_WITH_APPARATUS", "reference", 1, 900, True, BASE),
        TrialInput("t4", "MAND_NEUTRAL_WITH_APPARATUS", "reference", 1, 1500, True, BASE),
    ])


def test_same_input_same_hash_and_result(bundle):
    a, b = analyze(_session(), bundle), analyze(_session(), bundle)
    assert a.input_hash == b.input_hash
    assert canonical_json(a.to_dict()) == canonical_json(b.to_dict())


def test_changed_versions_change_hash(bundle):
    a = analyze(_session(), bundle)
    other = input_hash({"x": 1}, {**bundle.versions, "registry_version": "9.9"})
    assert a.input_hash != other


def test_float_representation_is_platform_stable():
    """Побайтовая воспроизводимость требует фиксированного формата чисел."""
    assert input_hash({"v": 0.1 + 0.2}, {}) == input_hash({"v": 0.3}, {})


def test_file_hash_is_idempotency_key():
    blob = b"Date;Kyphotic Angle ICT-ITL\r\n2026-01-01;45,1\r\n"
    assert file_hash(blob) == file_hash(blob)
    assert file_hash(blob) != file_hash(blob + b" ")


def test_analysis_without_neutral_fails_loudly(bundle):
    import pytest
    s = SessionInput("s", "p", "habitual_occlusion", False, [
        TrialInput("t", "MAND_CLENCH", "diagnostic", 1, 0, False, BASE),
    ])
    with pytest.raises(ValueError, match="нейтрал"):
        analyze(s, bundle)
