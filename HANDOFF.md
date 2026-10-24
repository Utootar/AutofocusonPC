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
- ตอน switch (อัปเดต 2026-10-24): เลือกหน้าต่างใต้จุดที่หันหัวไปมอง และวางเมาส์ตรงนั้น จุดนี้ได้จาก affine map `(yaw, pitch, eye_x, eye_y) → (x, y)` ของแต่ละจอ (eye_x/eye_y คือตำแหน่ง iris เทียบกับหัวตา-หางตา) ซึ่ง fit ตอน calibrate 5 จุดต่อจอ (กลาง ซ้าย ขวา บน ล่าง) โดยให้ผู้ใช้มองเมาส์แบบปกติ ไม่ต้องบังคับหันหัว ส่วนการเลือกจอยังใช้แค่ yaw/pitch และจะ switch ก็ต่อเมื่อหัวหยุดนิ่งแล้ว (`steady()`: ขยับน้อยกว่า 2.5° ใน 0.3 วินาที) เพื่อไม่ให้วัดจุดมองตอนหัวกำลังหัน ถ้าใต้จุดนั้นไม่มีหน้าต่างที่ activate ได้ จะ fallback ไปใช้ MRU ถ้า `calib.json` เก่าไม่มี `point_maps` จะใช้วิธีเดิม คือ MRU + คืนเมาส์ไปตำแหน่งล่าสุด
- ถ้าเมาส์อยู่บนจอปลายทางอยู่แล้ว จะไม่ย้ายเมาส์
- เป็น exe ธรรมดา ไม่ทำ uiAccess ยอมรับว่า switch ไปหน้าต่าง admin/elevated อาจล้มเหลว
- passive recalibration: เมื่อผู้ใช้เปลี่ยน foreground เอง ระบบจะปรับ centroid ช้าๆ การปรับนี้เก็บใน memory เท่านั้น ไม่เขียนกลับ `calib.json`

## ไฟล์
- `decide.py`: logic ล้วน ได้แก่ `Calib`, `OneEuro`, `StateMachine`
- `vision.py`: กล้อง MSMF 640x480 (grab ทุกเฟรม แต่ decode เฉพาะตอนขอ) + `HeadPose`
- `win.py`: Win32 ผ่าน ctypes ได้แก่ monitors, MRU ต่อจอ (WinEvent out-of-context), guards, activate, cursor restore, lock detection
- `main.py`:
  - `python main.py calibrate` เขียน `calib.json`
  - `python main.py` รันจริงและเขียน `trace.csv`
- `replay.py`: replay `trace.csv` แบบ offline เพื่อ tune ค่าต่างๆ
- `test_decide.py`: pytest 12 ตัว
- `requirements.txt` และ `.venv`: ห้ามติดตั้ง `opencv-python` เพราะ mediapipe ใช้ `opencv-contrib-python` อยู่แล้ว ถ้ามีทั้งคู่ `cv2` จะชนกัน
- `face_landmarker.task`: model โหลดอัตโนมัติตอนรันครั้งแรก

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
- `calib.json` ที่ map เป็น 3x2 (ไม่มี iris) จะถูกข้ามพร้อม warning ต้อง calibrate ใหม่
- repo: https://github.com/Utootar/AutofocusonPC

## ขั้นต่อไป
1. รัน `.venv\Scripts\python.exe main.py calibrate` ใหม่ (แบบ 5 จุดต่อจอ) แล้วดูค่า `gaze fit error` ที่พิมพ์ออกมา ตอนมองต้องหันหัวด้วย ไม่ใช่เหลือบแค่ตา
2. รัน `.venv\Scripts\python.exe main.py` แล้วทดสอบตาม checklist ในหัวข้อ Verification ของแผน `C:\Users\optim\.claude\plans\snoopy-whistling-graham.md`
3. ถ้า switch ไว/ช้าเกินไป หรือ switch ผิด ให้ tune ด้วย `replay.py trace.csv --dwell ... --beta ...` แล้วนำค่าที่ได้ไปแก้ใน `StateMachine`/`OneEuro` ใน `main.py`
4. เช็ค CPU ของ `svchost (FrameServer)` ใน Task Manager

## ความเสี่ยงที่รู้อยู่แล้ว
- ถ้าเหลือบแค่ตาโดยไม่หันหัว ระบบจะไม่รู้ ข้อนี้คือข้อจำกัดของ head pose
- การเหลือบไปอ่านอาจทำให้ focus ย้ายโดยไม่ตั้งใจ ซึ่งลดได้ด้วย dwell + quiet guard แต่ไม่หมด
- ถ้า Teams/Zoom ใช้กล้องอยู่ โปรแกรมจะเปิดกล้องไม่ได้ และจะ retry ทุก 30 วินาที
- Windows Studio Effects แบบ "Automatic framing" ทำให้ geometry เพี้ยน ต้องปิด
- ถ้ามีโปรแกรมยิง input ตลอดเวลา (mouse jiggler / keep-awake) guard จะ block ตลอด และระบบจะไม่ switch เลย
