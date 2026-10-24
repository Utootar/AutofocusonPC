"""Compare camera resolutions: size the driver really gives, rate, inference time, CPU, and how much
the head/eye features jitter while you hold still. Lower eye jitter means more accurate gaze.

  python -m tools.camera_bench   (run from the project root; stop main.py first, it holds the camera)
"""
import os
import time

import numpy as np

from autofocus import vision

SIZES = ((640, 480), (1280, 720))
SECONDS = 8
MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "face_landmarker.task")


def bench(w, h):
    cam = vision.Camera(0, w, h)
    if not cam.open():
        return f"{w}x{h}: cannot open the camera (is main.py still running?)"
    pose = vision.HeadPose(vision.ensure_model(MODEL))  # fresh instance: VIDEO mode needs rising timestamps
    try:
        feats, inf, size = [], [], None
        cam.read(2.0)  # let the driver start streaming
        cpu0, t0 = time.process_time(), time.monotonic()
        while time.monotonic() - t0 < SECONDS:
            f = cam.read()
            if f is None:
                continue
            size = f[1].shape[1::-1]
            s = time.perf_counter()
            p = pose.estimate(*f)
            inf.append(time.perf_counter() - s)
            if p is not None:
                feats.append(p)
        wall = time.monotonic() - t0
        cpu = 100 * (time.process_time() - cpu0) / wall / os.cpu_count()
    finally:
        cam.close()
        pose.close()
    if len(feats) < 10:
        return f"{w}x{h}: only {len(feats)} face samples (camera held by main.py, or face not visible?)"
    jit = np.median(np.abs(np.diff(np.array(feats), axis=0)), axis=0)  # frame-to-frame noise
    return (f"{w}x{h}: got {size[0]}x{size[1]}, {len(inf) / wall:.1f} Hz unthrottled, "
            f"inference {1000 * np.median(inf):.0f} ms, CPU {cpu:.1f}% of machine | jitter "
            f"yaw {jit[0]:.2f} pitch {jit[1]:.2f} eye_x {jit[2]:.2f} eye_y {jit[3]:.2f}")


def main():
    print(f"Look at the center of the notebook screen and hold still for about {len(SIZES) * (SECONDS + 3)} s.")
    time.sleep(3)
    for w, h in SIZES:
        print(bench(w, h), flush=True)


if __name__ == "__main__":
    main()
