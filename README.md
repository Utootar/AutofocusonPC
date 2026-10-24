# AutofocusonPC

โปรแกรม Windows ที่ย้าย focus ไปหน้าต่างที่คุณมอง ใช้ webcam ของโน้ตบุ๊กอย่างเดียว ไม่ต้องใช้อุปกรณ์เสริม

เมื่อหันไปมองอีกจอ โปรแกรมจะ:
1. focus หน้าต่างที่อยู่ตรงจุดที่คุณมอง
2. ย้ายเมาส์ไปที่จุดนั้น

## วิธีทำงาน

1. MediaPipe FaceLandmarker อ่านทิศหัว (yaw/pitch) และตำแหน่งตาดำ (iris) จากกล้อง
2. ใช้ทิศหัวเลือกจอ:
   - project ทิศหัวลงแกนระหว่างจุดกลางของสองจอที่ได้จาก calibrate
   - กรอง noise ด้วย One-Euro filter
   - ตัดสินด้วย state machine (hysteresis + dwell + refractory)
3. รอให้หัวหยุดนิ่ง แล้วใช้ทิศหัวรวมกับตำแหน่งตาดำ คำนวณจุดที่มองบนจอผ่าน affine map ที่ fit ตอน calibrate
4. ก่อน switch จะเช็ค guards ถ้ากำลังพิมพ์ ลากเมาส์ เปิดเมนู หรือเล่นเต็มจอ จะไม่ switch

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

ไฟล์ model `face_landmarker.task` จะดาวน์โหลดอัตโนมัติตอนรันครั้งแรก

## ใช้งาน

### 1. Calibrate

```
.venv\Scripts\python.exe main.py calibrate
```

1. ย้ายเมาส์ไปไว้บนจอโน้ตบุ๊ก แล้วกด Enter
2. โปรแกรมจะย้ายเมาส์ไปให้ 5 จุดต่อจอ (กลาง ซ้าย ขวา บน ล่าง)
3. ทุกจุด ให้มองเมาส์ตามปกติ แล้วกด Enter จากนั้นมองค้างไว้ประมาณ 2 วินาที

เมื่อเสร็จ โปรแกรมจะเขียน `calib.json` และพิมพ์ `gaze fit error` ของแต่ละจอ ค่ายิ่งต่ำยิ่งแม่น

ต้อง calibrate ใหม่เมื่อ:
- ย้ายเก้าอี้หรือเปลี่ยนท่านั่ง
- ย้ายตำแหน่งจอ
- เปลี่ยนการตั้งค่า display

### 2. รัน

```
.venv\Scripts\python.exe main.py
```

กด Ctrl+C เพื่อหยุด

ระหว่างรัน โปรแกรมจะบันทึก `trace.csv` เพื่อใช้ debug หรือ tune ค่า

## Tune

ใช้ `replay.py` เล่น `trace.csv` แบบ offline เพื่อลองค่า dwell และ filter:

```
.venv\Scripts\python.exe replay.py trace.csv --dwell 0.4 --beta 0.5
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
| `decide.py` | logic ล้วน: `Calib`, gaze point map, `OneEuro`, `StateMachine` |
| `vision.py` | กล้อง และการประมาณทิศหัวกับตำแหน่งตา |
| `win.py` | Win32 ผ่าน ctypes: จอ, หน้าต่าง, guards, ย้าย focus, เมาส์ |
| `replay.py` | replay `trace.csv` แบบ offline |
| `test_decide.py` | unit tests |

## ข้อจำกัด

- ความแม่นจำกัดด้วยกล้อง 640x480 แท็บหรือปุ่มเล็ก ๆ อาจจิ้มผิด
- การเหลือบไปอ่านอาจทำให้ focus ย้ายโดยไม่ตั้งใจ dwell และ guard ช่วยลดได้ แต่ไม่หมด
- ถ้า Teams/Zoom ใช้กล้องอยู่ โปรแกรมจะเปิดกล้องไม่ได้ และจะลองใหม่ทุก 30 วินาที
- switch ไปหน้าต่างที่รันแบบ admin อาจไม่สำเร็จ เพราะโปรแกรมไม่ได้รันแบบ elevated
- ถ้ามีโปรแกรมส่ง input ตลอดเวลา (mouse jiggler / keep-awake) guard จะ block และโปรแกรมจะไม่ switch เลย

## License

MIT
