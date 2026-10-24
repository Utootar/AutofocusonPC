"""Pure decision logic: calibrated 1D projection, One-Euro filter, dwell/hysteresis state machine.

Monitor index 0 and 1 refer to the two calibration targets, in calibration order.
"""
import math

import numpy as np


class Calib:
    """Projects a (yaw, pitch) pose onto the axis between the two monitor centroids.

    score 0 = looking at monitor 0, score 1 = looking at monitor 1. No hardcoded angles:
    sign conventions, asymmetric layouts and lens distortion are absorbed by the centroids.
    """

    def __init__(self, c0, c1, sigma_s):
        self.c = [np.asarray(c0, float), np.asarray(c1, float)]
        self.sigma_s = float(sigma_s)

    @classmethod
    def fit(cls, samples0, samples1):
        a, b = np.asarray(samples0, float), np.asarray(samples1, float)
        d = b.mean(0) - a.mean(0)
        if d @ d < 1e-9:
            raise ValueError("calibration centroids coincide; the two poses are indistinguishable")
        cal = cls(a.mean(0), b.mean(0), 0.0)
        # pooled noise along the axis, measured around each centroid
        resid = np.concatenate([cal.scores(a), cal.scores(b) - 1.0])
        cal.sigma_s = float(resid.std())
        return cal

    def scores(self, p):
        d = self.c[1] - self.c[0]
        return (np.asarray(p, float) - self.c[0]) @ d / (d @ d)

    def score(self, p):
        return float(self.scores(p))

    @property
    def margin(self):
        return max(0.15, 3.0 * self.sigma_s)

    @property
    def feasible(self):
        # the hysteresis band must leave room on both sides of 0.5
        return self.margin < 0.35

    def update(self, k, p, alpha=0.05):
        """Passive recalibration: nudge centroid k toward pose p. Rejects outliers."""
        if abs(self.score(p) - k) > 0.5:
            return False
        self.c[k] = (1 - alpha) * self.c[k] + alpha * np.asarray(p, float)
        return True

    def to_dict(self):
        return {"c0": self.c[0].tolist(), "c1": self.c[1].tolist(), "sigma_s": self.sigma_s}

    @classmethod
    def from_dict(cls, d):
        return cls(d["c0"], d["c1"], d["sigma_s"])


def _aug(p):
    p = np.asarray(p, float)
    return np.concatenate([p, np.ones(p.shape[:-1] + (1,))], -1)


def fit_point_map(poses, points):
    """Least-squares affine map (yaw, pitch) -> screen (x, y) for one monitor. Returns a 3x2 matrix."""
    a, *_ = np.linalg.lstsq(_aug(poses), np.asarray(points, float), rcond=None)
    return a


def map_point(a, pose):
    """pose: (yaw, pitch) or an (n, 2) array. Returns (x, y) or an (n, 2) array."""
    return _aug(pose) @ np.asarray(a, float)


class OneEuro:
    """One-Euro filter (Casiez et al. 2012) driven by real timestamps, so frame drops are handled."""

    def __init__(self, min_cutoff=1.0, beta=0.5, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self):
        self.t = self.x = None
        self.dx = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, t, x):
        if self.t is None:
            self.t, self.x = t, x
            return x
        dt = t - self.t
        if dt <= 0:
            return self.x
        self.dx += self._alpha(self.d_cutoff, dt) * ((x - self.x) / dt - self.dx)
        self.x += self._alpha(self.min_cutoff + self.beta * abs(self.dx), dt) * (x - self.x)
        self.t = t
        return self.x


class StateMachine:
    """Hysteresis zone + dwell + refractory. Fires the monitor index to focus, or returns None."""

    def __init__(self, margin, dwell=0.4, refractory=1.0):
        self.margin, self.dwell, self.refractory = margin, dwell, refractory
        self.zone = None
        self.armed_at = None
        self.blocked_until = -math.inf

    def step(self, t, s, fg_monitor, guards_ok):
        """s: filtered score or None (no face). fg_monitor: monitor of the real OS foreground.
        guards_ok: callable, only evaluated once dwell is satisfied."""
        if s is None:
            self.zone = self.armed_at = None
            return None
        if s > 0.5 + self.margin:
            zone = 1
        elif s < 0.5 - self.margin:
            zone = 0
        else:
            zone = self.zone
        if zone != self.zone:
            self.zone, self.armed_at = zone, None
        if zone is None or zone == fg_monitor or t < self.blocked_until:
            self.armed_at = None
            return None
        if self.armed_at is None:
            self.armed_at = t
        if t - self.armed_at >= self.dwell and guards_ok():
            self.armed_at = None
            self.blocked_until = t + self.refractory
            return zone
        return None
