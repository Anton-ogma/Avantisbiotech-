"""Валидаторы протокола: каждое нарушение §8.1 блокирует переход (§16)."""
import pytest
from domain.protocol import (
    PlannedProbe, ProtocolError, TrialFact, assert_transition, can_transition,
    randomize_within_groups, reconcile_with_plan, validate_plan, validate_trial,
)

FULL_PLAN = [
    PlannedProbe("MAND_NEUTRAL_WITH_APPARATUS", "reference", 0),
    PlannedProbe("MAND_CLENCH", "diagnostic", 1),
    PlannedProbe("CTRL_SHAM_MANDIBULAR", "control", 2),
    PlannedProbe("MAND_NEUTRAL_WITH_APPARATUS", "reference", 3),
    PlannedProbe("PODAL_WEDGE_L", "podal", 4),
    PlannedProbe("MAND_SPLINT_THERAPEUTIC", "therapeutic", 5),
    PlannedProbe("MAND_NEUTRAL_WITH_APPARATUS", "reference", 6),
]

OK = dict(study_mode=True, lld_measured=True, randomization_scheme="none", randomization_seed=None)


def test_valid_plan_passes(bundle):
    assert validate_plan(FULL_PLAN, bundle, **OK) == []


def test_therapeutic_before_diagnostic_blocked(bundle):
    plan = [
        PlannedProbe("MAND_NEUTRAL_WITH_APPARATUS", "reference", 0),
        PlannedProbe("MAND_SPLINT_THERAPEUTIC", "therapeutic", 1),
        PlannedProbe("MAND_CLENCH", "diagnostic", 2),
        PlannedProbe("CTRL_SHAM_MANDIBULAR", "control", 3),
        PlannedProbe("MAND_NEUTRAL_WITH_APPARATUS", "reference", 4),
        PlannedProbe("MAND_NEUTRAL_WITH_APPARATUS", "reference", 5),
    ]
    assert any(v.code == "group_order" for v in validate_plan(plan, bundle, **OK))


def test_sham_required_in_study_mode(bundle):
    """Р-15: без sham изменение объясняется временем, вниманием и ожиданием эффекта."""
    plan = [p for p in FULL_PLAN if p.probe_code != "CTRL_SHAM_MANDIBULAR"]
    assert any(v.code == "sham_missing" for v in validate_plan(plan, bundle, **OK))


def test_sham_not_required_outside_study_mode(bundle):
    plan = [p for p in FULL_PLAN if p.probe_code != "CTRL_SHAM_MANDIBULAR"]
    opts = {**OK, "study_mode": False}
    assert not any(v.code == "sham_missing" for v in validate_plan(plan, bundle, **opts))


def test_three_neutrals_required(bundle):
    plan = [p for p in FULL_PLAN if p.probe_code != "MAND_NEUTRAL_WITH_APPARATUS"][:3]
    assert any(v.code == "neutral_count" for v in validate_plan(plan, bundle, **OK))


def test_seed_required_when_randomizing(bundle):
    opts = {**OK, "randomization_scheme": "random_within_group", "randomization_seed": None}
    assert any(v.code == "seed_missing" for v in validate_plan(FULL_PLAN, bundle, **opts))


def test_lld_required_before_probes(bundle):
    opts = {**OK, "lld_measured": False}
    assert any(v.code == "lld_missing" for v in validate_plan(FULL_PLAN, bundle, **opts))


def test_randomization_is_reproducible_from_seed(bundle):
    """Р-16: без воспроизводимости эффект порядка нельзя проверить."""
    a = randomize_within_groups(FULL_PLAN, bundle, seed=42)
    b = randomize_within_groups(FULL_PLAN, bundle, seed=42)
    assert [p.probe_code for p in a] == [p.probe_code for p in b]


def test_randomization_keeps_neutrals_fixed(bundle):
    result = randomize_within_groups(FULL_PLAN, bundle, seed=7)
    neutrals = [p.position for p in result if p.probe_code == "MAND_NEUTRAL_WITH_APPARATUS"]
    assert neutrals == [0, 3, 6]


def test_settle_and_washout_block_trial(bundle):
    v = validate_trial(TrialFact("MAND_SPLINT_THERAPEUTIC", 1, 1, 10, 1.0, None, None), bundle)
    assert {x.code for x in v} >= {"settle", "washout"}


def test_excursion_required(bundle):
    v = validate_trial(TrialFact("MAND_PROTRUSION", 1, 1, 999, 99.0, None, None), bundle)
    assert any(x.code == "excursion" for x in v)


def test_state_machine_is_one_way_except_confirming_repeat():
    """Р-28: цикл probes_running ⇄ imported — иначе подтверждающий повтор невыразим."""
    assert can_transition("imported", "probes_running")
    assert can_transition("prepared", "plan_approved")
    assert not can_transition("analyzed", "imported")
    assert not can_transition("prepared", "analyzed")
    with pytest.raises(ProtocolError):
        assert_transition("analyzed", "prepared")


def test_deviations_are_data_not_errors(bundle):
    facts = [TrialFact("MAND_CLENCH", 1, 1, 999, 99.0, None, 80.0)]
    devs = reconcile_with_plan(FULL_PLAN, facts)
    assert any(d.kind == "missing" for d in devs)
