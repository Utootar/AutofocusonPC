import numpy as np
import pytest

from autofocus.decide import Calib, OneEuro, StateMachine, fit_point_map, map_point

YES = lambda: True
NO = lambda: False


def test_score_is_zero_and_one_at_centroids_for_asymmetric_layout():
    # monitor 1 is up and to the left: both axes differ, unequal magnitudes
    cal = Calib((2.0, -8.0), (-30.0, 12.0), 0.02)
    assert cal.score((2.0, -8.0)) == pytest.approx(0.0)
    assert cal.score((-30.0, 12.0)) == pytest.approx(1.0)
    assert cal.score((-14.0, 2.0)) == pytest.approx(0.5)


def test_fit_measures_noise_and_rejects_identical_poses():
    rng = np.random.default_rng(0)
    a = rng.normal((0, 0), 0.5, (40, 2))
    b = rng.normal((-25, 3), 0.5, (40, 2))
    cal = Calib.fit(a, b)
    assert 0 < cal.sigma_s < 0.05 and cal.feasible
    with pytest.raises(ValueError):
        Calib.fit([(1, 1)] * 5, [(1, 1)] * 5)


def test_noisy_calibration_is_infeasible():
    assert not Calib((0, 0), (-10, 0), 0.15).feasible


def test_update_moves_centroid_but_rejects_outliers():
    cal = Calib((0, 0), (-20, 0), 0.02)
    assert cal.update(1, (-22, 0))
    assert cal.c[1][0] < -20
    assert not cal.update(0, (-18, 0))  # far from monitor 0: rejected
    assert cal.c[0][0] == 0


def test_point_map_recovers_affine_pose_to_screen():
    # monitor to the left: yaw drives x (mirrored), pitch drives y, plus a little cross-talk
    true = np.array([[-40.0, 3.0], [2.0, 35.0], [-1500.0, 600.0]])
    rng = np.random.default_rng(1)
    poses = rng.uniform((25, -10), (50, 15), (50, 2))
    a = fit_point_map(poses, map_point(true, poses))
    assert np.allclose(a, true)
    assert map_point(a, (37.0, 2.0)) == pytest.approx(map_point(true, (37.0, 2.0)))


def test_one_euro_smooths_jitter_and_resets():
    f = OneEuro()
    out = [f(i * 0.1, 0.5 + (0.05 if i % 2 else -0.05)) for i in range(30)]
    assert max(out[10:]) - min(out[10:]) < 0.05
    f.reset()
    assert f(10.0, 0.9) == 0.9


def run(sm, samples, fg=0, guards=YES):
    """samples: list of (t, s). Returns list of (t, fired monitor)."""
    fired = []
    for t, s in samples:
        m = sm.step(t, s, fg, guards)
        if m is not None:
            fired.append((t, m))
            fg = m
    return fired


def ticks(t0, t1, s, dt=0.1):
    return [(round(t0 + i * dt, 3), s) for i in range(int(round((t1 - t0) / dt)))]


def test_dwell_must_complete_before_firing():
    sm = StateMachine(0.15)
    assert run(sm, ticks(0, 0.35, 0.9)) == []
    sm = StateMachine(0.15)
    assert run(sm, ticks(0, 0.6, 0.9)) == [(0.4, 1)]


def test_hysteresis_band_does_not_flip_zone():
    sm = StateMachine(0.15)
    # enters zone 1, then wobbles inside the band: stays zone 1, never returns to 0
    fired = run(sm, ticks(0, 0.6, 0.9) + ticks(0.6, 3.0, 0.4))
    assert fired == [(0.4, 1)]


def test_face_loss_cancels_dwell():
    sm = StateMachine(0.15)
    samples = ticks(0, 0.3, 0.9) + [(0.3, None)] + ticks(0.4, 0.7, 0.9)
    assert run(sm, samples) == []


def test_refractory_blocks_immediate_switch_back():
    sm = StateMachine(0.15, refractory=1.0)
    fired = run(sm, ticks(0, 0.5, 0.9) + ticks(0.5, 3.0, 0.1))
    # back to 0 is armed only after the refractory ends at 1.4, then dwells 0.4
    assert fired == [(0.4, 1), (1.8, 0)]


def test_guards_hold_fire_until_they_clear_while_still_in_zone():
    sm = StateMachine(0.15)
    blocked = {"v": True}
    guards = lambda: not blocked["v"]
    assert run(sm, ticks(0, 1.0, 0.9), guards=guards) == []
    blocked["v"] = False
    assert sm.step(1.0, 0.9, 0, guards) == 1


def test_no_fire_when_foreground_already_on_looked_at_monitor():
    sm = StateMachine(0.15)
    assert run(sm, ticks(0, 2.0, 0.9), fg=1) == []
