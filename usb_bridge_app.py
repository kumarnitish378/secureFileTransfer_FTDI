#!/usr/bin/env python3
import os,sys,struct,zlib,time
import serial

CHUNK = 4096
BAUD = 115200
# No timeout -> blocking reads. Exit with Ctrl+C.
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
    s = serial.Serial(port, BAUD, timeout=None)
    # handshake header
    for i in range(HEADER_RETRIES):
        s.write(hdr)
        r = s.read(2)  # blocking until 2 bytes arrive
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
                r = s.read(7)  # blocking ACK/NAK + seq(4)
                if not r:
                    continue
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
    s = serial.Serial(port, BAUD, timeout=None)
    # clear any stale bytes
    try:
        s.reset_input_buffer()
        s.reset_output_buffer()
    except Exception:
        pass

    print("Waiting for header... (run sender). Exit with Ctrl+C.")
    # read exact header
    hdr = s.read(4)
    if hdr != b'FILE':
        print("Unexpected header:", hdr); s.close(); return

    ln = struct.unpack('!B', s.read(1))[0]
    fname = s.read(ln).decode()
    size = struct.unpack('!Q', s.read(8))[0]
    outpath = os.path.join(outdir, fname)

    # show filename immediately
    print(f"Receiving file: {fname}  ({size} bytes) -> {outpath}")
    s.write(b'OK')

    recv_bytes = 0
    with open(outpath, 'wb') as f:
        while True:
            hdr2 = s.read(6)
            if hdr2 == b'DONE': break
            if len(hdr2) < 6:
                continue
            seq, length = struct.unpack('!I H', hdr2)
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

    # ensure progress bar final newline so message visible
    print()
    print("Received ->", outpath)
    s.close()

def main():
    print("=== USB Bridge File Transfer (blocking mode) ===")
    try:
        mode = input("Mode (send/recv): ").strip().lower()
        port = input("Serial port (e.g. COM3 or /dev/ttyUSB0): ").strip()
        if mode == 'send':
            path = input("Path to file to send: ").strip()
            send(port, path)
        elif mode == 'recv':
            outdir = input("Output folder path (default .): ").strip() or '.'
            recv(port, outdir)
        else:
            print("Invalid mode")
    except KeyboardInterrupt:
        print("\nAborted by user (Ctrl+C). Exiting.")
        try:
            # try to close serial if open
            s.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()
