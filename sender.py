# sender.py
import serial,sys
s = serial.Serial('COM9',115200,timeout=10)
with open('recv.py','rb') as f:
    while True:
        b = f.read(4096)
        if not b: break
        s.write(b)
s.close()
