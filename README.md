# AutofocusonPC

โปรแกรม Windows ที่ย้าย focus ไปหน้าต่างที่คุณมอง ใช้ webcam ของโน้ตบุ๊กอย่างเดียว ไม่ต้องใช้อุปกรณ์เสริม

เมื่อหันไปมองอีกจอ โปรแกรมจะ:
1. focus หน้าต่างที่อยู่ตรงจุดที่คุณมอง
2. ย้ายเมาส์ไปที่จุดนั้น

## วิธีทำงาน

1. MediaPipe FaceLandmarker อ่านทิศหัว (yaw/pitch) และตำแหน่งตาดำ (iris) จากกล้อง
2. ใช้ทิศหัวรวมกับตาเลือกจอ ถ้าหันแค่หัวแต่ตายังมองจอเดิม จะไม่ switch:
   - คำนวณจุดที่มองบนเดสก์ท็อปจาก affine map ที่ fit จากทั้งสองจอ
   - project จุดนั้นลงแกนระหว่างจุดกลางของสองจอ
   - กรอง noise ด้วย One-Euro filter
   - ตัดสินด้วย state machine (hysteresis + dwell + refractory)
3. รอให้หัวหยุดนิ่ง แล้วคำนวณจุดที่มองบนจอปลายทางด้วย map ของจอนั้น ซึ่งแม่นกว่า map รวม
4. ก่อน switch จะเช็ค guards จะไม่ switch ถ้า:
   - กดปุ่มคีย์บอร์ดไปภายใน 3 วินาที (`TYPING_HOLD_S`) ให้ focus อยู่กับหน้าที่กำลังพิมพ์
   - คลิกไปภายใน 0.8 วินาที (`QUIET_MS`)
   - หัวยังหันอยู่ (ขยับเกิน 4° ใน 0.3 วินาที, `STEADY_DEG`)
   - กำลังลากเมาส์ หรือเปิดเมนูอยู่
   - แค่ขยับเมาส์เฉย ๆ ไม่บล็อก แต่ถ้าขยับอยู่ จะ switch แค่ focus ไม่ย้ายเมาส์
   - เล่นเกมหรือ present เต็มจอ
5. เรียนรู้ระหว่างใช้งาน: ทุกครั้งที่คลิก ถือว่าคุณมองที่เมาส์ จึงบันทึกคู่ "ทิศหัวและตา → ตำแหน่งที่คลิก" ลง `data/learned.csv` แล้ว fit map ใหม่
   - คลิกใหม่มีน้ำหนักมากกว่าคลิกเก่า (น้ำหนักลดลงตามเวลา โดยหารด้วย e ทุก 30 นาที) ถ้าเลื่อนเก้าอี้ map จะค่อย ๆ ปรับตาม
   - ข้อมูลจาก calibrate ยังมีน้ำหนักคงที่ เพื่อกันไม่ให้ map เพี้ยนตอนคลิกอยู่แค่บางจุดของจอ

## ความต้องการ

- Windows 10/11
- Python 3.11
- จอ 2 จอ (จอโน้ตบุ๊กที่มีกล้อง + จอนอก)
- ปิด Windows Studio Effects แบบ "Automatic framing" ถ้าเปิดอยู่ ทิศหัวที่วัดได้จะเพี้ยน

## ติดตั้ง

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

ห้ามติดตั้ง `opencv-python` เพิ่ม เพราะ mediapipe ใช้ `opencv-contrib-python` อยู่แล้ว ถ้ามีทั้งสองตัว `cv2` จะชนกัน

ไฟล์ model `face_landmarker.task` จะดาวน์โหลดอัตโนมัติลง `data/` ตอนรันครั้งแรก

## ใช้งาน

### 1. Calibrate

```
.venv\Scripts\python.exe main.py calibrate
```

1. ย้ายเมาส์ไปไว้บนจอโน้ตบุ๊ก แล้วกด Enter
2. โปรแกรมจะย้ายเมาส์ไปให้ 15 จุดต่อจอ (ทั่วจอรวมมุม)
3. ทุกจุด ให้ทำตามข้อความ แล้วกด Enter จากนั้นมองค้างไว้ประมาณ 2 วินาที:
   - ข้อความ "look at the mouse pointer the way you normally would": มองเมาส์ตามปกติ
   - ข้อความ "keep your HEAD facing the center ... move ONLY your EYES": หันหัวไปกลางจอค้างไว้ แล้วกลอกแค่ตาไปที่เมาส์ ขั้นนี้ทำให้โปรแกรมแยกได้ว่าคุณขยับตาหรือขยับหัว

เมื่อเสร็จ โปรแกรมจะเขียน `data/calib.json` และพิมพ์ `gaze fit error` ของแต่ละจอและของสองจอรวมกัน ค่ายิ่งต่ำยิ่งแม่น

ต้อง calibrate ใหม่เมื่อ:
- ย้ายตำแหน่งจอ
- เปลี่ยนการตั้งค่า display
- เลื่อนเก้าอี้ไปไกลมากจนจิ้มผิดหลายร้อย pixel (ถ้าเลื่อนนิดหน่อย การคลิกระหว่างใช้งานจะช่วยปรับให้เอง)

calibrate ใหม่จะล้างข้อมูลการคลิกที่เรียนรู้ไว้ใน `data/learned.csv`

### 2. รัน

```
.venv\Scripts\python.exe main.py
```

กด Ctrl+C เพื่อหยุด

ระหว่างรัน โปรแกรมจะบันทึก `data/trace.csv` เพื่อใช้ debug หรือ tune ค่า

## Tune

ใช้ `tools/replay.py` เล่น `data/trace.csv` แบบ offline เพื่อลองค่า dwell และ filter (รันจากโฟลเดอร์โปรเจกต์):

```
.venv\Scripts\python.exe -m tools.replay data\trace.csv --dwell 0.4 --beta 0.5
```

ได้ค่าที่ต้องการแล้ว ให้แก้ค่าใน `StateMachine` และ `OneEuro` ใน `main.py`

## ทดสอบ

```
.venv\Scripts\python.exe -m pytest -q
```

## ไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `main.py` | จุดเริ่มโปรแกรม: calibrate และ loop หลัก |
| `autofocus/decide.py` | logic ล้วน: `Calib`, gaze point map, `OneEuro`, `StateMachine` |
| `autofocus/vision.py` | กล้อง และการประมาณทิศหัวกับตำแหน่งตา |
| `autofocus/win.py` | Win32 ผ่าน ctypes: จอ, หน้าต่าง, guards, ย้าย focus, เมาส์ |
| `tools/replay.py` | replay `trace.csv` แบบ offline |
| `tests/test_decide.py` | unit tests |
| `docs/HANDOFF.md` | บันทึกสถานะงานและการตัดสินใจ |
| `data/` | ไฟล์เฉพาะเครื่อง: `calib.json`, `learned.csv`, `trace.csv`, model (ไม่อยู่ใน git) |

## ข้อจำกัด

- ความแม่นจำกัดด้วยกล้อง 640x480 แท็บหรือปุ่มเล็ก ๆ อาจจิ้มผิด
- การเหลือบไปอ่านอาจทำให้ focus ย้ายโดยไม่ตั้งใจ dwell และ guard ช่วยลดได้ แต่ไม่หมด
- ถ้า Teams/Zoom ใช้กล้องอยู่ โปรแกรมจะเปิดกล้องไม่ได้ และจะลองใหม่ทุก 30 วินาที
- switch ไปหน้าต่างที่รันแบบ admin อาจไม่สำเร็จ เพราะโปรแกรมไม่ได้รันแบบ elevated
- ถ้ามีโปรแกรมส่ง input ตลอดเวลา (mouse jiggler / keep-awake) guard จะ block และโปรแกรมจะไม่ switch เลย

## License

MIT
