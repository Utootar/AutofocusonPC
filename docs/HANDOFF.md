# HANDOFF: Autofocusonpc

อัปเดตล่าสุด: 2026-10-23

## โปรเจกต์นี้คืออะไร
โปรแกรม Windows ที่ย้าย focus ไปจอที่ผู้ใช้หันหน้าไปมอง โดยใช้ webcam ในโน้ตบุ๊ก

ขั้นตอนการทำงาน:
1. กล้องโน้ตบุ๊กประมาณ head pose (yaw/pitch) ด้วย MediaPipe FaceLandmarker
2. แปลง pose เป็นคะแนนจอ (score) ด้วย calibration
3. กรอง noise ด้วย One-Euro filter
4. ตัดสินใจด้วย state machine (hysteresis + dwell + refractory)
5. ตรวจ guards แล้วสั่ง Windows ย้าย focus ไปหน้าต่างบนจอนั้น และคืนเมาส์ไปตำแหน่งเดิมของจอนั้น

Setup ของผู้ใช้:
- จอโน้ตบุ๊ก (กล้องอยู่ที่ขอบจอนี้)
- จอ HDMI วางด้านซ้าย จึงแยกสองจอด้วย yaw เป็นหลัก
- เครื่อง i5-1335U (12 threads) และ Windows 11

## การตัดสินใจหลัก (ตกลงกับผู้ใช้แล้ว)
- ใช้ Python 3.11 + mediapipe + numpy + ctypes ไม่ใช้ pywin32
- ไม่ hardcode องศา ใช้ calibrate 2 จุดแล้ว project ลงแกนเดียว ได้ score 0 = จอแรก, 1 = จอสอง
- ขนาด hysteresis margin คำนวณจาก noise ที่วัดได้: `max(0.15, 3σ)`
- ถ้า margin ≥ 0.35 ถือว่าแยกจอไม่ออก
- ไม่ใช้ low-level keyboard/mouse hooks guard ใช้วิธี poll ตอนจะ switch เท่านั้น:
  - `GetLastInputInfo` (ต้องว่าง ≥ 800ms)
  - `GetAsyncKeyState` (ปุ่มเมาส์และ modifier)
  - `GetGUIThreadInfo` (เมนูเปิดอยู่ หรือกำลังลาก/resize)
  - `SHQueryUserNotificationState` (fullscreen / presentation)
  - blocklist Start/Search
- วิธีย้าย focus: กด Alt ผ่าน `SendInput`, เรียก `SetForegroundWindow`, ส่ง VK `0xE8` เพื่อ mask Alt-up ถ้าไม่สำเร็จ fallback เป็น `AttachThreadInput` ถ้ายังไม่สำเร็จให้ log แล้วจบ ไม่วน retry
- ตอน switch (อัปเดต 2026-10-24): เลือกหน้าต่างใต้จุดที่หันหัวไปมอง และวางเมาส์ตรงนั้น จุดนี้ได้จาก affine map `(yaw, pitch, eye_x, eye_y) → (x, y)` ของแต่ละจอ (eye_x/eye_y คือตำแหน่ง iris เทียบกับหัวตา-หางตา) ซึ่ง fit ตอน calibrate 15 จุดต่อจอ (`CALIB_STEPS`: กลาง, ซ้าย/ขวาแบบขยับแค่ตา, แล้วตาราง 4x3 รวมมุมแบบมองปกติ; เดิมมีแค่ซ้าย ขวา บน ล่าง ซึ่งวัดจาก `tools/l2cs_test.py` แล้วพลาด 240 px เทียบกับตาราง 196 px) ขั้นตอนขยับแค่ตาใช้แยกค่าตาออกจากค่าหัว เพราะค่า iris ใน image space ปนกับ yaw (corr 0.81 ใน trace) การเลือกจอ (อัปเดตหลังผู้ใช้แจ้งว่าหันแค่หัวก็ switch) ใช้ `gaze_map` ซึ่งเป็น affine map เดียวที่ fit จากทั้งสองจอ แปลงเป็นจุดบนเดสก์ท็อปก่อน แล้วค่อยส่งให้ `Calib` project ระหว่างจุดกลางของสองจอ และจะ switch ก็ต่อเมื่อหัวหยุดนิ่งแล้ว (`steady()`: ขยับน้อยกว่า 2.5° ใน 0.3 วินาที) เพื่อไม่ให้วัดจุดมองตอนหัวกำลังหัน ถ้าใต้จุดนั้นไม่มีหน้าต่างที่ activate ได้ จะ fallback ไปใช้ MRU ถ้า `calib.json` เก่าไม่มี `point_maps` จะใช้วิธีเดิม คือ MRU + คืนเมาส์ไปตำแหน่งล่าสุด
- ถ้าเมาส์อยู่บนจอปลายทางอยู่แล้ว จะไม่ย้ายเมาส์
- เป็น exe ธรรมดา ไม่ทำ uiAccess ยอมรับว่า switch ไปหน้าต่าง admin/elevated อาจล้มเหลว
- passive recalibration: เมื่อผู้ใช้เปลี่ยน foreground เอง ระบบจะปรับ centroid ช้าๆ การปรับนี้เก็บใน memory เท่านั้น ไม่เขียนกลับ `calib.json`
- เรียนรู้จากการคลิก (เพิ่ม 2026-10-24 เพราะผู้ใช้เลื่อนเก้าอี้บ่อย):
  - ทุกครั้งที่คลิกซ้าย (poll `GetAsyncKeyState` ไม่ใช้ hook) จะบันทึก (pose เฉลี่ย 0.3 วินาที, ตำแหน่งคลิก) ลง `data/learned.csv` แล้ว `refit_maps` ทั้ง `gaze_map` และ map ต่อจอ
  - น้ำหนักแบบ weighted least squares: คลิกใช้ `exp(-age/1800s)` ส่วนแถว calibrate รวมกันมีน้ำหนักคงที่เท่ากับ 10 คลิกใหม่ (`CAL_WEIGHT`)
  - ข้ามคลิกที่: หัวไม่นิ่ง, ห่างจากจุดที่ทำนายเกิน 500 px (ถือว่าไม่ได้มองเมาส์), หรือตรงจุดที่โปรแกรมวางเมาส์เอง (กัน map เรียนรู้จากการเดาของตัวเอง)
  - เก็บคลิกล่าสุด 300 ตัว ตอนเริ่มรันจะเขียนไฟล์ใหม่แบบ atomic (`.tmp` + `os.replace`) การ calibrate ใหม่จะล้างคลิกทั้งหมด
- eye features (`vision.FEATURES = 2`): วัดตำแหน่งตาดำตามแกนซ้าย-ขวา/บน-ล่างของหัว ใช้ landmark 3D (x*w, y*h, z*w) แทนพิกัดในภาพ เพราะตอนนั่งนิ่ง ค่าตาแทบไม่สั่น (bench ที่ 640x480: eye_x 0.04) แต่วางเมาส์ยังคลาด 230–350 px จึงสรุปว่า error เป็นแบบ systematic ไม่ใช่ noise ส่วน 1280x720 ไม่ดีกว่า (สั่นมากกว่าและได้แค่ 9.5 Hz) ถ้า `calib.json` ไม่มี `features` ตรงกับเวอร์ชันนี้ ต้อง calibrate ใหม่
- guard ที่เปลี่ยน (หลังผู้ใช้แจ้งว่าบางครั้งไม่ switch และ log ขึ้น `head-moving`/`input`): `STEADY_DEG` 2.5 → 4.0 เพราะหัวขยับ 3.3–4.4° ใน 0.3 วินาทีระหว่างมองปกติ ส่วน `GetLastInputInfo` ไม่บล็อกแล้ว บล็อกแค่คลิกภายใน `QUIET_MS` (`clicked_at` จาก `poll_input`) แต่ถ้ามี input ภายใน `QUIET_MS` จะไม่ย้ายเมาส์ตอน switch เหตุผลที่บล็อกจะแสดงเป็น log `switch held back: ...` และ `wait:<reason>` ใน trace
- เลือกหน้าต่างแบบโหวต (`_window_near`, `VOTE_R = 250`): จุดรอบจุดมอง 3x3 โหวตด้วย `WindowFromPoint` (กลาง 4, ข้าง 2, มุม 1) แล้ววางเมาส์บนพื้นที่ของหน้าต่างที่ชนะ ทำเพราะจากคลิก 321 ครั้ง วางเมาส์คลาด median 257 px แนวตั้งถูกดึงเข้ากลางจอ (slope −0.46) และ affine ที่ fit กับคลิกตรง ๆ ก็ยังคลาด 257 px คือข้อมูลจากกล้องเต็มที่แล้ว ถ้ายังเลือกหน้าต่างผิด ไอเดียถัดไปคือทดลอง L2CS-Net (AI วัดสายตา) เป็นเครื่องมือแยกใน `tools/` ก่อน
- ค่าตาถ่วงน้ำหนักไปที่ตาข้างที่หันเข้ากล้อง (`FEATURES = 3`, c153add): น้ำหนักแต่ละตา = (ความกว้างตาในภาพ 2D / ความกว้าง 3D)^4 มองตรงได้ 50/50 หันหัวราว 40° ได้ราว 93/7 ทำเพราะตอนมองจอนอก ตาข้างไกลโดนจมูกบัง ค่า eye_x สั่นในจุดเดียวกัน 4.5 เทียบกับ 0.9 บนจอโน้ตบุ๊ก หลังแก้: สั่นเหลือ 2.4, fit จอโน้ตบุ๊ก 152 เป็น 112 px, จอนอก 112 เป็น 100 px, สองจอรวม 305 เป็น 197 px (ค่าตอน calibrate ยังไม่ได้วัดจากคลิกจริง) แต่ map ยังใช้ตาแค่ราว 3–7% ของการขยับแนวนอน ที่เหลือมาจาก yaw
- dwell 0.38 วินาที (ผู้ใช้ขอ) ผู้ใช้บอกว่าความไวในการ switch โอเคแล้ว
- typing guard: ไม่ switch ภายใน 3 วินาที (`TYPING_HOLD_S`) หลังกดปุ่มคีย์บอร์ด (ไม่นับ modifier และ Alt/0xE8 ที่โปรแกรมส่งเอง) ทำโดย poll `GetAsyncKeyState` ทุก tick

## ไฟล์
- `autofocus/decide.py`: logic ล้วน ได้แก่ `Calib`, `fit_point_map`/`map_point`, `OneEuro`, `StateMachine`
- `autofocus/vision.py`: กล้อง MSMF 640x480 (grab ทุกเฟรม แต่ decode เฉพาะตอนขอ) + `HeadPose` (ทิศหัว + iris)
- `autofocus/win.py`: Win32 ผ่าน ctypes ได้แก่ monitors, MRU ต่อจอ (WinEvent out-of-context), guards, activate, หน้าต่างใต้จุดมอง, cursor, lock detection
- `main.py`:
  - `python main.py calibrate` เขียน `data/calib.json`
  - `python main.py` รันจริงและเขียน `data/trace.csv`
- `tools/replay.py`: replay `trace.csv` แบบ offline เพื่อ tune ค่าต่างๆ รันด้วย `python -m tools.replay data\trace.csv` จาก root
- `tests/test_decide.py`: pytest 14 ตัว (`pytest.ini` ตั้ง `pythonpath = .`)
- `requirements.txt` และ `.venv`: ห้ามติดตั้ง `opencv-python` เพราะ mediapipe ใช้ `opencv-contrib-python` อยู่แล้ว ถ้ามีทั้งคู่ `cv2` จะชนกัน
- `data/`: `calib.json`, `learned.csv`, `trace.csv`, `face_landmarker.task` (model โหลดอัตโนมัติตอนรันครั้งแรก) ทั้งโฟลเดอร์อยู่ใน `.gitignore`

## สถานะ
เสร็จและทดสอบแล้ว:
- pytest ผ่านทั้ง 11 ตัว
- smoke test ผ่าน: กล้องเปิดได้ 640x480, จับหน้าได้ครบทุกเฟรม, `layout`/`is_locked`/`fg_monitor`/`guards_ok`/`pick_target` ทำงานได้
- วัด CPU แล้ว (นับเฉพาะ process python ไม่รวม FrameServer):

  | ตั้งไว้ | ได้จริง | CPU รวมทั้งเครื่อง |
  |---|---|---|
  | 10Hz | 6.9Hz | 2.75% |
  | 5Hz | 4.3Hz | 1.08% |

- inference ใช้ราว 26ms ต่อเฟรม และ driver ไม่ยอมลด fps ยังส่ง 30fps

**ยังไม่ได้ทดสอบ** เพราะตอนทดสอบต่อจออยู่จอเดียว:
- calibrate จริง
- switch focus จริง (Alt-mask, fallback)
- cursor restore
- ถอด HDMI ระหว่างรัน
- lock/unlock
- switch ไปหน้าต่าง elevated

อัปเดต 2026-10-24:
- calibrate จริงแบบ 2 จุดผ่านแล้ว และ switch ทั้งสองทางทำงานใน `trace.csv`
- ผู้ใช้แจ้งว่าเมาส์ไปแค่ริมจอ ไม่ไปตรงที่หันไปมอง จึงเพิ่ม gaze point mapping ผู้ใช้บอกว่าดีขึ้นมาก แต่ยังไม่ตรง จาก trace พบว่าตอนใช้งานจริงหันหัวน้อยกว่าตอน calibrate (ใช้ตาช่วย) และวัดจุดมองตอนหัวยังหันไม่เสร็จ จึงเพิ่ม iris features และ steady gate แล้ว pytest ผ่าน 12 ตัว แต่ยังไม่ได้ทดสอบ iris กับกล้องจริง เพราะตอนนั้นกล้องถูก `main.py` ที่ผู้ใช้รันอยู่ใช้งาน
- `calib.json` ที่ไม่มี `gaze_map` (เวอร์ชันเก่า) ใช้ไม่ได้ `main.py` จะสั่งให้ calibrate ใหม่ ยังไม่ได้ทดสอบกับกล้องจริง ทดสอบแค่ dry run ของ calibrate ด้วยกล้องปลอม และ pytest 13 ตัว
- repo: https://github.com/Utootar/AutofocusonPC
- คลิก 8 ครั้งแรกหลัง calibrate 15 จุด (ก่อนแก้เรื่องตา) อยู่บนจอโน้ตบุ๊กทั้งหมด: คลาด median 257 px แกน x ทำนายเกินจริง (slope 1.61) แกน y ขาด (0.39) ผู้ใช้บอกว่าบนจอนอกเมาส์ชอบไปเกินจุดที่มอง แต่ยังไม่มีคลิกบนจอนอกมายืนยัน
- `tools/l2cs_test.py` ยังไม่ได้ commit (ผู้ใช้ยังไม่ได้ตัดสินว่าจะเก็บหรือลบ) ต้องใช้ torch/torchvision/safetensors ที่ลงใน `.venv` แล้วแต่ไม่อยู่ใน `requirements.txt` และ `data/l2cs_gaze360.safetensors`
- ลองแล้วไม่ได้ผล (อย่าลองซ้ำแบบเดิม):
  - L2CS-Net (ResNet-50, weights `py-feat/l2cs`): per monitor ดีขึ้นแค่ 196 เป็น 172 px แต่ใช้ 419 ms/เฟรมบน CPU ส่วนขนาด 224 แย่กว่าของเดิม จึงไม่ใส่
  - ตำแหน่งหัว head_x/y/z เป็น input พร้อม calibrate 2 ท่า (นั่งตรง/พิง; f5d1538 revert ใน d610fdf): ตอน calibrate ดีขึ้น (LOO 316 เป็น 177 px) แต่คลิกจริงแย่ลง (302 เป็น 438-558 px) ใส่ ridge ก็ไม่ชนะแบบเดิม เพราะตำแหน่งหัวสัมพันธ์กับ pitch และตอน calibrate มีแค่ 2 กลุ่มท่า map เลยจำท่าแทนที่จะเรียนเรขาคณิต ถ้าจะลองใหม่ต้องใช้โมเดลเรขาคณิต (ray จากตำแหน่งหัวตัดระนาบจอ) ไม่ใช่ affine

## ขั้นต่อไป
1. ผู้ใช้ calibrate หลังแก้เรื่องตาแล้ว และกำลังลองใช้ เมื่อมีคลิกพอ ให้วัดจาก `data/learned.csv` ว่าคลาดกี่ px แยกตามจอ (โดยเฉพาะจอนอก) ถ้ายังไม่ตรง ตกลงกับผู้ใช้ไว้ว่าจะหยุดไล่ความแม่นของตำแหน่งเมาส์ แล้วพึ่งการเลือกจอกับการโหวตหน้าต่างแทน ทางเดียวที่เหลือคือโมเดลเรขาคณิต (ray จากตำแหน่งหัวตัดระนาบจอ) ซึ่งเป็นงานใหญ่
2. รัน `.venv\Scripts\python.exe main.py` แล้วทดสอบตาม checklist ในหัวข้อ Verification ของแผน `C:\Users\optim\.claude\plans\snoopy-whistling-graham.md`
3. ถ้า switch ไว/ช้าเกินไป หรือ switch ผิด ให้ tune ด้วย `python -m tools.replay data\trace.csv --dwell ... --beta ...` แล้วนำค่าที่ได้ไปแก้ใน `StateMachine`/`OneEuro` ใน `main.py`
4. เช็ค CPU ของ `svchost (FrameServer)` ใน Task Manager

## ความเสี่ยงที่รู้อยู่แล้ว
- ถ้าเหลือบแค่ตาโดยไม่หันหัว ระบบจะไม่รู้ ข้อนี้คือข้อจำกัดของ head pose
- การเหลือบไปอ่านอาจทำให้ focus ย้ายโดยไม่ตั้งใจ ซึ่งลดได้ด้วย dwell + quiet guard แต่ไม่หมด
- ถ้า Teams/Zoom ใช้กล้องอยู่ โปรแกรมจะเปิดกล้องไม่ได้ และจะ retry ทุก 30 วินาที
- Windows Studio Effects แบบ "Automatic framing" ทำให้ geometry เพี้ยน ต้องปิด
- ถ้ามีโปรแกรมยิง input ตลอดเวลา (mouse jiggler / keep-awake) guard จะ block ตลอด และระบบจะไม่ switch เลย
