#!/usr/bin/env python3
import os,sys,struct,zlib,time
import serial

CHUNK = 4096
BAUD = 115200
TIMEOUT = 5
HEADER_RETRIES = 10
CHUNK_RETRIES = 5

def progress_bar(sent, total, width=30):
    pct = sent/total if total else 1
    filled = int(width*pct)
    bar = '[' + '#' * filled + '-'*(width-filled) + ']'
    print(f"\r{bar} {pct*100:6.2f}% {sent}/{total} bytes", end='', flush=True)

def send(port, filepath):
    if not os.path.isfile(filepath):
        print("File not found:", filepath); return
    size = os.path.getsize(filepath)
    fname = os.path.basename(filepath).encode()
    hdr = b'FILE' + struct.pack('!B', len(fname)) + fname + struct.pack('!Q', size)
    s = serial.Serial(port, BAUD, timeout=TIMEOUT)
    # handshake header
    for i in range(HEADER_RETRIES):
        s.write(hdr)
        r = s.read(2)
        if r == b'OK': break
        time.sleep(0.3)
    else:
        print("No OK from receiver. Check connection and run receiver first."); s.close(); return
    sent_bytes = 0
    seq = 0
    with open(filepath, 'rb') as f:
        while True:
            data = f.read(CHUNK)
            if not data: break
            pkt = struct.pack('!I H', seq, len(data)) + data + struct.pack('!I', zlib.crc32(data)&0xFFFFFFFF)
            for attempt in range(CHUNK_RETRIES):
                s.write(pkt)
                r = s.read(7)  # expect ACK/NAK + seq(4)
                if not r:
                    time.sleep(0.1); continue
                if r.startswith(b'ACK'):
                    ackseq = struct.unpack('!I', r[3:7])[0]
                    if ackseq == seq:
                        sent_bytes += len(data)
                        progress_bar(sent_bytes, size)
                        break
                elif r.startswith(b'NAK'):
                    time.sleep(0.05)
                    continue
            else:
                print("\nFailed to send chunk seq", seq); s.close(); return
            seq += 1
    s.write(b'DONE')
    progress_bar(size, size)
    print("\nSend complete ->", filepath)
    s.close()

def recv(port, outdir):
    os.makedirs(outdir, exist_ok=True)
    s = serial.Serial(port, BAUD, timeout=TIMEOUT)
    print("Waiting for header... (run sender)")
    buf = b''
    start = time.time()
    while True:
        b = s.read(1)
        if b: buf += b
        if b'FILE' in buf: break
        if time.time()-start > 300:
            print("Header timeout. Abort."); s.close(); return
    idx = buf.find(b'FILE')
    rest = buf[idx+4:]
    # read name len + name + size
    while len(rest) < 1:
        rest += s.read(1)
    ln = rest[0]
    while len(rest) < 1 + ln + 8:
        rest += s.read(1)
    fname = rest[1:1+ln].decode()
    size = struct.unpack('!Q', rest[1+ln:1+ln+8])[0]
    outpath = os.path.join(outdir, fname)
    s.write(b'OK')
    recv_bytes = 0
    with open(outpath, 'wb') as f:
        while True:
            hdr = s.read(6)
            if not hdr:
                time.sleep(0.02); continue
            if hdr == b'DONE': break
            if len(hdr) < 6:
                continue
            seq, length = struct.unpack('!I H', hdr)
            data = s.read(length)
            crc_raw = s.read(4)
            if len(data) != length or len(crc_raw) != 4:
                s.write(b'NAK' + struct.pack('!I', seq))
                continue
            crc = struct.unpack('!I', crc_raw)[0]
            if zlib.crc32(data)&0xFFFFFFFF == crc:
                f.write(data); recv_bytes += length
                s.write(b'ACK' + struct.pack('!I', seq))
                progress_bar(recv_bytes, size)
            else:
                s.write(b'NAK' + struct.pack('!I', seq))
    progress_bar(size, size)
    print("\nReceived ->", outpath)
    s.close()

def main():
    print("=== USB Bridge File Transfer ===")
    mode = input("Mode (send/recv): ").strip().lower()
    port = input("Serial port (e.g. COM3 or /dev/ttyUSB0): ").strip()
    if mode == 'send':
        path = input("Path to file to send: ").strip()
        send(port, path)
    elif mode == 'recv':
        outdir = input("Output folder path: ").strip()
        if outdir == '':
            outdir = '.'
        recv(port, outdir)
    else:
        print("Invalid mode")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted by user.")
