"""Webcam capture and head pose (yaw, pitch) via MediaPipe FaceLandmarker."""
import math
import os
import threading
import time
import urllib.request

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, RunningMode

IRIS = ((468, 33, 133), (473, 362, 263))  # face mesh: (iris center, eye corner, eye corner) per eye
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")


def ensure_model(path):
    if not os.path.exists(path):
        print(f"Downloading {MODEL_URL}")
        urllib.request.urlretrieve(MODEL_URL, path + ".part")
        os.replace(path + ".part", path)
    return path


class Camera:
    """Grabs every frame on a background thread (keeps the driver buffer drained, so no stale
    frames), but decodes only when read() asks for one."""

    def __init__(self, index=0):
        self.index = index
        self._cap = None
        self._thread = None
        self._stop = threading.Event()
        self._want = threading.Event()
        self._ready = threading.Event()
        self._frame = None

    @property
    def is_open(self):
        return self._cap is not None

    def open(self):
        cap = cv2.VideoCapture(self.index, cv2.CAP_MSMF)
        if not cap.isOpened():
            cap.release()
            return False
        # driver-side downscale is cheaper than decoding 720p; drivers may ignore these
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 15)
        self._cap = cap
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def close(self):
        if self._cap is None:
            return
        self._stop.set()
        self._thread.join(timeout=2)
        self._cap.release()
        self._cap = None

    def _run(self):
        while not self._stop.is_set():
            if not self._cap.grab():
                time.sleep(0.05)
                continue
            if self._want.is_set():
                ok, frame = self._cap.retrieve()
                if ok:
                    self._frame = (time.monotonic(), frame)
                    self._want.clear()
                    self._ready.set()

    def read(self, timeout=0.5):
        """Returns (t_monotonic, bgr_frame) of the next grabbed frame, or None."""
        if self._cap is None:
            return None
        self._ready.clear()
        self._want.set()
        if not self._ready.wait(timeout):
            return None
        return self._frame


class HeadPose:
    def __init__(self, model_path):
        opts = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=RunningMode.VIDEO,  # tracks the face ROI between frames, skips the detector
            num_faces=1,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=True,
        )
        self._lm = FaceLandmarker.create_from_options(opts)
        self._last_ms = -1

    def estimate(self, t, frame_bgr):
        """Returns (yaw, pitch, eye_x, eye_y), or None if no face. yaw/pitch are head angles in
        degrees; eye_x/eye_y are the iris offsets from the eye-corner midpoint, in percent of eye
        width, averaged over both eyes. Signs are arbitrary; calibration absorbs them."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ms = max(int(t * 1000), self._last_ms + 1)  # VIDEO mode needs strictly increasing timestamps
        self._last_ms = ms
        res = self._lm.detect_for_video(image, ms)
        if not res.facial_transformation_matrixes:
            return None
        f = np.asarray(res.facial_transformation_matrixes[0])[:3, 2]  # face normal in camera space
        if f[2] < 0:
            f = -f  # keep atan2 away from its +-180 wrap at a frontal pose
        lm, (h, w) = res.face_landmarks[0], frame_bgr.shape[:2]
        ex = ey = 0.0
        for c, a, b in IRIS:
            ax, ay, bx, by = lm[a].x * w, lm[a].y * h, lm[b].x * w, lm[b].y * h
            width = math.hypot(bx - ax, by - ay) or 1.0
            ex += 50 * (lm[c].x * w - (ax + bx) / 2) / width  # 50 = 100% / 2 eyes
            ey += 50 * (lm[c].y * h - (ay + by) / 2) / width
        return (math.degrees(math.atan2(f[0], f[2])),
                math.degrees(math.atan2(f[1], math.hypot(f[0], f[2]))), ex, ey)

    def close(self):
        self._lm.close()
