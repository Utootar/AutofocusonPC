"""Offline, deterministic replay of trace.csv through the decision logic, for tuning.

  python -m tools.replay data/trace.csv --dwell 0.5 --beta 0.3   (run from the project root)

shortcut: guards are assumed open and the foreground only changes on simulated switches
(user clicks in the trace are ignored); log guard state per tick if tuning needs them.
"""
import argparse
import csv
import json

from autofocus.decide import Calib, OneEuro, StateMachine


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--calib", default="data/calib.json")
    ap.add_argument("--dwell", type=float, default=0.4)
    ap.add_argument("--refractory", type=float, default=1.0)
    ap.add_argument("--margin", type=float, help="default: from calibration")
    ap.add_argument("--min-cutoff", type=float, default=1.0)
    ap.add_argument("--beta", type=float, default=0.5)
    a = ap.parse_args()

    with open(a.calib) as f:
        cal = Calib.from_dict(json.load(f))
    filt = OneEuro(a.min_cutoff, a.beta)
    sm = StateMachine(a.margin if a.margin is not None else cal.margin, a.dwell, a.refractory)
    fg, switches = None, []
    with open(a.trace, newline="") as f:
        for row in csv.reader(f):
            t, yaw, pitch, fg_logged = float(row[0]), row[1], row[2], row[5]
            if fg is None and fg_logged:
                fg = int(fg_logged)
            if yaw:
                s = filt(t, cal.score((float(yaw), float(pitch))))
            else:
                filt.reset()
                s = None
            m = sm.step(t, s, fg, lambda: True)
            if m is not None:
                switches.append((t, m))
                fg = m
    for t, m in switches:
        print(f"{t:10.3f}  -> monitor {m}")
    print(f"{len(switches)} switches")


if __name__ == "__main__":
    main()
