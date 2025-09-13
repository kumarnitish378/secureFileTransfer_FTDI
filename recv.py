# recv.py
import serial
s = serial.Serial('COM8',115200,timeout=10)
with open('recv1.py','wb') as f:
    while True:
        data = s.read(4096)
        if not data: break
        f.write(data)
s.close()
