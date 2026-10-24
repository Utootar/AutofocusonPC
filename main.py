"""Head-pose monitor focus switcher.

  python main.py calibrate   look at the mouse pointer at 7 spots per monitor; writes data/calib.json
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

from autofocus import vision, win
from autofocus.decide import Calib, OneEuro, StateMachine, fit_point_map, map_point, refit_maps

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CALIB = os.path.join(DATA, "calib.json")
LEARNED = os.path.join(DATA, "learned.csv")  # labeled samples: calibration + clicks while running
MAX_CLICKS = 300    # most recent click samples kept for refitting
OUTLIER_PX = 500    # a click this far from the predicted gaze: the user was not looking at the cursor
TRACE = os.path.join(DATA, "trace.csv")
MODEL = os.path.join(DATA, "face_landmarker.task")
TRACE_MAX = 10 * 1024 * 1024
OPEN_RETRY_S = 30   # camera busy (e.g. a video call): back off
STALL_S = 3         # no frames this long (e.g. after resume): reopen
CAM_SIZE = (640, 480)  # pick with: python -m tools.camera_bench
# calibration steps per monitor: (x, y as fractions of the monitor, eyes only). Center first: it fits
# Calib. Eyes-only steps keep the head on the center, so the fit can tell eye movement from head movement.
CALIB_STEPS = ((0.5, 0.5, False), (0.1, 0.5, True), (0.9, 0.5, True),
               (0.1, 0.5, False), (0.9, 0.5, False), (0.5, 0.1, False), (0.5, 0.9, False))
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
    centers, maps, all_poses, all_pts, rows = [], [], [], [], []
    for name, dev in zip(("notebook", "external"), devices):
        l, t, r, b = lay[dev]
        poses, pts = [], []
        for i, (fx, fy, eyes_only) in enumerate(CALIB_STEPS):
            x, y = int(l + fx * (r - l)), int(t + fy * (b - t))
            win.SetCursorPos(x, y)
            how = (f"keep your HEAD facing the center of the {name} screen, move ONLY your EYES to the mouse pointer"
                   if eyes_only else "look at the mouse pointer the way you normally would")
            input(f"[{name} {i + 1}/{len(CALIB_STEPS)}] {how}, keep looking, press Enter... ")
            time.sleep(0.3)  # let the head settle after the key press
            print("Hold still for 1.5 s")
            s = sample(cam, pose, 1.5)
            if len(s) < 8:
                sys.exit(f"Only {len(s)} face samples. Check lighting and that the camera sees you.")
            if i == 0:
                centers.append(s)
            poses += s
            pts += [(x, y)] * len(s)
            rows += [(time.time(), "cal", len(maps), x, y, *p) for p in s]
        a = fit_point_map(poses, pts)
        print(f"{name}: gaze fit error ~{fit_error(a, poses, pts):.0f} px")
        maps.append(a.tolist())
        all_poses += poses
        all_pts += pts
    cam.close()
    # one map over both monitors chooses the monitor, so eyes count: turning only the head does not switch
    gaze = fit_point_map(all_poses, all_pts)
    print(f"both screens: gaze fit error ~{fit_error(gaze, all_poses, all_pts):.0f} px")
    cal = Calib.fit(*[map_point(gaze, c) for c in centers])
    with open(CALIB, "w") as f:
        json.dump({**cal.to_dict(), "devices": devices, "layout": win.layout(), "features": vision.FEATURES,
                   "gaze_map": gaze.tolist(), "point_maps": maps}, f, indent=2)
    with open(LEARNED, "w", newline="") as f:  # a new calibration also forgets old clicks
        csv.writer(f).writerows(rows)
    print(f"noise {cal.sigma_s:.3f}, margin {cal.margin:.2f}")
    if not cal.feasible:
        print("WARNING: the two monitors are too close to tell apart. Calibrate again, "
              "and look straight at each pointer.")


def fit_error(a, poses, pts):
    """RMS distance in px between the map's prediction and the pointer the user looked at."""
    return np.sqrt(np.mean(np.sum((map_point(a, poses) - pts) ** 2, axis=1)))


def run(cam, pose):
    if not os.path.exists(CALIB):
        sys.exit("No calib.json. Run: python main.py calibrate")
    with open(CALIB) as f:
        cfg = json.load(f)
    if cfg.get("features") != vision.FEATURES or not os.path.exists(LEARNED):
        sys.exit("calib.json is from an older version. Run: python main.py calibrate")
    cal = Calib.from_dict(cfg)  # passive updates stay in memory; calib.json is the stable baseline
    w = win.Win(cfg["devices"])
    with open(LEARNED, newline="") as f:
        learned = [(float(r[0]), r[1], int(r[2]), *map(float, r[3:])) for r in csv.reader(f)]
    cal_rows = [r for r in learned if r[1] == "cal"]
    clicks = collections.deque((r for r in learned if r[1] == "click"), maxlen=MAX_CLICKS)
    gmap, maps = refit_maps(cal_rows + list(clicks), time.time())
    with open(LEARNED + ".tmp", "w", newline="") as f:  # drop clicks beyond MAX_CLICKS; replace is atomic
        csv.writer(f).writerows(cal_rows + list(clicks))
    os.replace(LEARNED + ".tmp", LEARNED)
    learn_file = open(LEARNED, "a", newline="")
    learn_out = csv.writer(learn_file)
    log.info("loaded %d click samples", len(clicks))
    filt, sm = OneEuro(), StateMachine(cal.margin)
    hist = collections.deque(maxlen=30)  # (t, yaw, pitch, eye_x, eye_y): recalibration, gaze, steadiness
    trace = open(TRACE, "a", newline="")
    out = csv.writer(trace)
    enabled, next_check, retry_at, last_frame = False, 0.0, 0.0, time.monotonic()
    last_wait = ""
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
                s = filt(t, cal.score(map_point(gmap, p)))

            w.track_cursor()
            click = w.poll_input()
            # learn from clicks: people look at the cursor when they click. Skip clicks on the spot we
            # put the cursor ourselves, or the map would learn its own guesses.
            if click and click != w.placed_at and p is not None and steady(hist, t):
                mon = w.monitor_at(click)
                recent = [h[1:] for h in hist if h[0] >= t - 0.3]
                pm = np.mean(recent, axis=0)
                if mon is not None and np.hypot(*(map_point(maps[mon], pm) - click)) < OUTLIER_PX:
                    row = (time.time(), "click", mon, *click, *pm)
                    clicks.append(row)
                    learn_out.writerow([row[0], row[1], row[2], *row[3:5], *(f"{v:.2f}" for v in pm)])
                    learn_file.flush()
                    gmap, maps = refit_maps(cal_rows + list(clicks), time.time())
            fg = w.fg_monitor()
            held = None  # why a due switch is held back, for the console and trace.csv

            def guards():
                nonlocal held
                held = "head-moving" if not steady(hist, t) else w.guard_block()
                return held is None

            target = sm.step(t, s, fg, guards)
            event = f"wait:{held}" if held else ""
            if event != last_wait:
                if held:
                    log.info("switch held back: %s", held)
                last_wait = event
            if target is not None:
                recent = [h[1:] for h in hist if h[0] >= t - 0.3]
                gaze = map_point(maps[target], np.mean(recent, axis=0)) if recent else None
                ok = w.switch_to(target, gaze)
                event = f"switch{target}" if ok else f"fail{target}"
                log.info(event)

            while not w.labels.empty():
                mon, tl = w.labels.get()
                pts = [h[1:] for h in hist if tl - 0.3 <= h[0] <= tl]
                if pts:
                    cal.update(mon, map_point(gmap, np.mean(pts, axis=0)))

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
        learn_file.close()
        w.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    win.init_process()
    os.makedirs(DATA, exist_ok=True)
    cam, pose = vision.Camera(0, *CAM_SIZE), vision.HeadPose(vision.ensure_model(MODEL))
    try:
        calibrate(cam, pose) if sys.argv[1:] == ["calibrate"] else run(cam, pose)
    finally:
        pose.close()


if __name__ == "__main__":
    main()
