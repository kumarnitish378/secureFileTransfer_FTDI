#!/usr/bin/env python3

# -----------------------------------------------------------------------------
#  USB Bridge Session — Secure File Transfer (FTDI)
#
#  Copyright (c) 2025 Nitish. All Rights Reserved.
#
#  License: Proprietary
#  This software and its source code are the exclusive property of Nitish.
#
#  Permissions:
#   - Use only with prior written permission from the copyright holder.
#
#  Restrictions:
#   - No copying, modifying, merging, publishing, distributing, sublicensing,
#     or selling.
#   - No reverse engineering, decompiling, or disassembling.
#
#  Liability:
#   - Provided "as is", without warranty of any kind.
#
#  Contact: nitish.ns378@gmail.com
# -----------------------------------------------------------------------------

import sys,os,struct,zlib,time
import serial

CHUNK=4096
BAUD=115200
TO=1
RETRIES=5

def hexd(b): return b.hex()

def send(port,filepath):
    s=serial.Serial(port,BAUD,timeout=TO)
    fname=os.path.basename(filepath).encode()
    size=os.path.getsize(filepath)
    hdr=b'FILE'+struct.pack('!B',len(fname))+fname+struct.pack('!Q',size)
    print("[SEND] header:",hdr, "hex:",hexd(hdr))
    # send header until OK
    for attempt in range(50):
        s.write(hdr)
        print("[SEND] header sent, waiting OK...")
        r=s.read(2)
        print("[SEND] raw recv:",r, "hex:",hexd(r))
        if r==b'OK': break
        time.sleep(0.5)
    else:
        print("No OK from receiver. Stop."); return
    with open(filepath,'rb') as f:
        seq=0
        while True:
            data=f.read(CHUNK)
            if not data: break
            pkt=struct.pack('!I H',seq,len(data))+data+struct.pack('!I',zlib.crc32(data)&0xFFFFFFFF)
            print(f"[SEND] seq={seq} len={len(data)} crc={zlib.crc32(data)&0xFFFFFFFF}")
            for _ in range(RETRIES):
                s.write(pkt)
                r=s.read(7)  # ACK/NAK + seq(4)
                print("[SEND] ack raw:",r, "hex:",hexd(r))
                if r.startswith(b'ACK'):
                    ackseq=struct.unpack('!I',r[3:7])[0]
                    if ackseq==seq: break
                time.sleep(0.2)
            else:
                print("Failed seq",seq); return
            seq+=1
    s.write(b'DONE'); print("Send done")

def recv(port,outdir):
    s=serial.Serial(port,BAUD,timeout=TO)
    print("[RECV] listening for header...")
    buf=b''
    start=time.time()
    while True:
        b=s.read(1)
        if b: buf+=b
        if b'FILE' in buf: break
        if time.time()-start>20:
            print("Timeout waiting FILE header. Got:",buf); return
    idx=buf.find(b'FILE')
    # consume rest if any
    rest=buf[idx+4:]
    ln=b''
    # need at least 1 byte len + name + 8 bytes size
    while len(rest)<1:
        rest+=s.read(1)
    ln_len=rest[0]
    while len(rest)<1+ln_len+8:
        rest+=s.read(1)
    fname=rest[1:1+ln_len].decode()
    size=struct.unpack('!Q',rest[1+ln_len:1+ln_len+8])[0]
    print(f"[RECV] fname={fname} size={size}")
    s.write(b'OK')
    outpath=os.path.join(outdir,fname)
    with open(outpath,'wb') as f:
        recvbytes=0
        while True:
            hdr=s.read(6)
            if not hdr:
                time.sleep(0.05); continue
            if hdr==b'DONE': break
            if len(hdr)<6:
                print("Short hdr:",hdr); continue
            seq,lenb=struct.unpack('!I H',hdr)
            data=s.read(lenb)
            crc_raw=s.read(4)
            crc=struct.unpack('!I',crc_raw)[0]
            print(f"[RECV] seq={seq} len={lenb} crc={crc} gotlen={len(data)}")
            if zlib.crc32(data)&0xFFFFFFFF==crc:
                f.write(data); recvbytes+=lenb
                s.write(b'ACK'+struct.pack('!I',seq))
            else:
                s.write(b'NAK'+struct.pack('!I',seq))
    print("Recv done",recvbytes,"->",outpath)

if __name__=='__main__':
    if len(sys.argv)<4: print("Usage: send/recv PORT PATH/OUTDIR"); sys.exit(1)
    mode=sys.argv[1]; port=sys.argv[2]; arg=sys.argv[3]
    if mode=='send': send(port,arg)
    else: recv(port,arg)
