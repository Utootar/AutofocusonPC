"""Head-pose monitor focus switcher.

  python main.py calibrate   look at the mouse pointer at 5 spots per monitor; writes calib.json
  python main.py             run; Ctrl+C to stop
"""
import collections
import csv
import json
import logging
import os
import sys
import time

import numpy as np

import vision
import win
from decide import Calib, OneEuro, StateMachine, fit_point_map, map_point

HERE = os.path.dirname(os.path.abspath(__file__))
CALIB = os.path.join(HERE, "calib.json")
TRACE = os.path.join(HERE, "trace.csv")
MODEL = os.path.join(HERE, "face_landmarker.task")
TRACE_MAX = 10 * 1024 * 1024
OPEN_RETRY_S = 30   # camera busy (e.g. a video call): back off
STALL_S = 3         # no frames this long (e.g. after resume): reopen
# fractions of each monitor's width/height to look at during calibration; center first, it fits Calib
GAZE_POINTS = ((0.5, 0.5), (0.1, 0.5), (0.9, 0.5), (0.5, 0.1), (0.5, 0.9))
STEADY_DEG = 2.5    # head counts as settled when yaw and pitch each move less than this over 0.3 s

log = logging.getLogger("main")


def steady(hist, t):
    """True once the head stopped turning, so the gaze point is not sampled mid-turn."""
    pts = [h[1:3] for h in hist if h[0] >= t - 0.3]
    return len(pts) >= 2 and np.ptp(pts, axis=0).max() < STEADY_DEG


def sample(cam, pose, seconds):
    out, end = [], time.monotonic() + seconds
    while time.monotonic() < end:
        f = cam.read()
        if f is not None:
            p = pose.estimate(*f)
            if p is not None:
                out.append(p)
    return out


def calibrate(cam, pose):
    lay = dict((d, tuple(r)) for d, r in win.layout())
    if len(lay) != 2:
        sys.exit(f"Need exactly 2 monitors, found {len(lay)}.")
    if not cam.open():
        sys.exit("Cannot open the camera.")
    input("Move the mouse onto the notebook screen, then press Enter... ")
    first = win.cursor_device()
    devices = [first] + [d for d in lay if d != first]
    centers, maps = [], []
    for name, dev in zip(("notebook", "external"), devices):
        l, t, r, b = lay[dev]
        poses, pts = [], []
        for fx, fy in GAZE_POINTS:
            x, y = int(l + fx * (r - l)), int(t + fy * (b - t))
            win.SetCursorPos(x, y)
            input(f"[{name}] Look at the mouse pointer the way you normally would, keep looking, press Enter... ")
            time.sleep(0.3)  # let the head settle after the key press
            print("Hold still for 1.5 s")
            s = sample(cam, pose, 1.5)
            if len(s) < 8:
                sys.exit(f"Only {len(s)} face samples. Check lighting and that the camera sees you.")
            if (fx, fy) == GAZE_POINTS[0]:
                centers.append([p[:2] for p in s])  # monitor choice uses head pose only
            poses += s
            pts += [(x, y)] * len(s)
        a = fit_point_map(poses, pts)
        err = np.sqrt(np.mean(np.sum((map_point(a, poses) - pts) ** 2, axis=1)))
        print(f"{name}: gaze fit error ~{err:.0f} px")
        maps.append(a.tolist())
    cam.close()
    cal = Calib.fit(*centers)
    with open(CALIB, "w") as f:
        json.dump({**cal.to_dict(), "devices": devices, "layout": win.layout(), "point_maps": maps}, f, indent=2)
    print(f"centroids {np.round(cal.c[0], 1)} vs {np.round(cal.c[1], 1)}, "
          f"noise {cal.sigma_s:.3f}, margin {cal.margin:.2f}")
    if not cal.feasible:
        print("WARNING: the two monitors are too close to tell apart by head pose. "
              "Turn your head (not just your eyes) toward each screen and calibrate again.")


def run(cam, pose):
    if not os.path.exists(CALIB):
        sys.exit("No calib.json. Run: python main.py calibrate")
    with open(CALIB) as f:
        cfg = json.load(f)
    cal = Calib.from_dict(cfg)  # passive updates stay in memory; calib.json is the stable baseline
    w = win.Win(cfg["devices"])
    # shortcut: maps are fixed at calibration (passive recalibration only moves Calib); recalibrate after moving the chair
    maps = cfg.get("point_maps")  # absent in an old calib.json: MRU window + last cursor position
    if maps and len(maps[0]) != 5:  # 3x2 head-only map: input no longer matches the 4-value pose
        log.warning("calib.json predates eye tracking; run calibrate again for gaze placement")
        maps = None
    filt, sm = OneEuro(), StateMachine(cal.margin)
    hist = collections.deque(maxlen=30)  # (t, yaw, pitch, eye_x, eye_y): recalibration, gaze, steadiness
    trace = open(TRACE, "a", newline="")
    out = csv.writer(trace)
    enabled, next_check, retry_at, last_frame = False, 0.0, 0.0, time.monotonic()
    log.info("running; Ctrl+C to stop")
    try:
        while True:
            now = time.monotonic()
            if now >= next_check:  # 1 Hz housekeeping
                next_check = now + 1
                was = enabled
                enabled = not win.is_locked() and win.layout() == cfg["layout"]
                if enabled != was:
                    log.info("enabled" if enabled else "disabled (locked or monitor layout changed)")
                if trace.tell() > TRACE_MAX:
                    trace.close()
                    os.replace(TRACE, TRACE + ".1")
                    trace = open(TRACE, "a", newline="")
                    out = csv.writer(trace)
            if not enabled:
                cam.close()
                time.sleep(1)
                continue
            if not cam.is_open:
                if now < retry_at:
                    time.sleep(1)
                    continue
                if not cam.open():
                    log.warning("camera unavailable, retrying in %d s", OPEN_RETRY_S)
                    retry_at = now + OPEN_RETRY_S
                    continue
                last_frame = now

            frame = cam.read()
            if frame is None:
                if time.monotonic() - last_frame > STALL_S:
                    log.warning("camera stalled, reopening")
                    cam.close()
                continue
            t, img = frame
            last_frame = t
            p = pose.estimate(t, img)
            if p is None:
                filt.reset()
                s = None
            else:
                hist.append((t, *p))
                s = filt(t, cal.score(p[:2]))

            w.track_cursor()
            fg = w.fg_monitor()
            target = sm.step(t, s, fg, lambda: steady(hist, t) and w.guards_ok())
            event = ""
            if target is not None:
                recent = [h[1:] for h in hist if h[0] >= t - 0.3]
                gaze = map_point(maps[target], np.mean(recent, axis=0)) if maps and recent else None
                ok = w.switch_to(target, gaze)
                event = f"switch{target}" if ok else f"fail{target}"
                log.info(event)

            while not w.labels.empty():
                mon, tl = w.labels.get()
                pts = [h[1:3] for h in hist if tl - 0.3 <= h[0] <= tl]
                if pts:
                    cal.update(mon, np.mean(pts, axis=0))

            # eye columns go last so replay.py's column indices stay valid
            out.writerow([f"{t:.3f}", *([f"{v:.2f}" for v in p[:2]] if p else ["", ""]),
                          f"{s:.3f}" if s is not None else "", sm.zone, fg, event,
                          *([f"{v:.2f}" for v in p[2:]] if p else [])])

            # 10 Hz while undecided or moving, 5 Hz when clearly settled in a zone
            settled = s is not None and sm.armed_at is None and abs(s - 0.5) > cal.margin + 0.1
            time.sleep(max(0.0, t + (0.2 if settled else 0.1) - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        cam.close()
        trace.close()
        w.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    win.init_process()
    cam, pose = vision.Camera(), vision.HeadPose(vision.ensure_model(MODEL))
    try:
        calibrate(cam, pose) if sys.argv[1:] == ["calibrate"] else run(cam, pose)
    finally:
        pose.close()


if __name__ == "__main__":
    main()
