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

"""
usb_bridge_session.py
Single-run session: send/recv/both. Single-line progress + KB/s + ETA.
Requires: pyserial
"""
import os, sys, struct, zlib, time, threading, traceback
from typing import List
import serial

# config
CHUNK = 4096
BAUD = 2000000
CHUNK_RETRIES = 5
HEADER_RETRIES = 8

def format_eta(seconds):
    if seconds is None or seconds == float('inf'):
        return "--:--"
    m = int(seconds // 60); s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

def progress_line(sent, total, start_t, width=34):
    pct = sent / total if total else 1.0
    filled = int(width * pct)
    bar = '[' + '#' * filled + '-' * (width - filled) + ']'
    elapsed = max(1e-6, time.perf_counter() - start_t)
    speed = sent / elapsed
    kbps = speed / 1024.0
    remaining = max(0, total - sent)
    eta = remaining / speed if speed > 0 else None
    return f"\r{bar} {pct*100:6.2f}% {sent}/{total} bytes  {kbps:7.2f} KB/s ETA {format_eta(eta)}", kbps, eta

class TransferError(Exception):
    pass

class SerialBridge:
    def __init__(self, port: str, blocking=True):
        self.port = port
        self.blocking = blocking
        try:
            self.ser = serial.Serial(port, BAUD, timeout=None if blocking else 1)
            self.ser.reset_input_buffer(); self.ser.reset_output_buffer()
        except Exception as e:
            raise e
        self.recv_thread = None
        self.recv_stop = threading.Event()

    def close(self):
        try:
            self.recv_stop.set()
            if self.recv_thread and self.recv_thread.is_alive():
                self.recv_thread.join(timeout=1)
            self.ser.close()
        except Exception:
            pass

    # Sending
    def send_files(self, filepaths: List[str]):
        for fp in filepaths:
            fp = fp.strip()
            if not fp:
                continue
            if not os.path.isfile(fp):
                print(f"\n[ERR] File not found: {fp}")
                continue
            try:
                self._send_file(fp)
            except KeyboardInterrupt:
                print("\n[SEND] Aborted by user.")
                return
            except Exception as e:
                print("\n[ERR] Send failed:", e)
                traceback.print_exc()

    def _send_file(self, filepath: str):
        size = os.path.getsize(filepath)
        fname = os.path.basename(filepath).encode()
        hdr = b'FILE' + struct.pack('!B', len(fname)) + fname + struct.pack('!Q', size)
        # handshake
        for attempt in range(HEADER_RETRIES):
            self.ser.write(hdr)
            resp = self.ser.read(2)
            if resp == b'OK':
                break
            time.sleep(0.15)
        else:
            raise TransferError("No OK from receiver. Ensure receiver active.")
        sent = 0; seq = 0; start_t = time.perf_counter()
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(CHUNK)
                if not data:
                    break
                pkt = struct.pack('!I H', seq, len(data)) + data + struct.pack('!I', zlib.crc32(data) & 0xFFFFFFFF)
                for attempt in range(CHUNK_RETRIES):
                    self.ser.write(pkt)
                    ack = self.ser.read(7)
                    if not ack:
                        time.sleep(0.05); continue
                    if ack.startswith(b'ACK'):
                        ackseq = struct.unpack('!I', ack[3:7])[0]
                        if ackseq == seq:
                            sent += len(data)
                            line, kbps, eta = progress_line(sent, size, start_t)
                            print(line, end='', flush=True)
                            break
                        else:
                            continue
                    elif ack.startswith(b'NAK'):
                        time.sleep(0.05); continue
                    else:
                        time.sleep(0.05); continue
                else:
                    raise TransferError(f"Chunk seq {seq} failed after retries.")
                seq += 1
        # DONE marker and flush
        self.ser.write(b'DONE')
        try:
            self.ser.flush()
        except Exception:
            pass
        line, kbps, eta = progress_line(size, size, start_t)
        print(line)  # newline after finish
        print(f"[+] Sent: {os.path.basename(filepath)} ({size} bytes) @ {kbps:7.2f} KB/s")

    # Receiving (loop)
    def start_recv_loop(self, outdir: str = '.'):
        self.recv_stop.clear()
        self.recv_thread = threading.Thread(target=self._recv_loop, args=(outdir,), daemon=True)
        self.recv_thread.start()

    def _recv_loop(self, outdir: str):
        os.makedirs(outdir, exist_ok=True)
        print(f"[RECV] Listening on {self.port}. Save to: {os.path.abspath(outdir)}")
        try:
            while not self.recv_stop.is_set():
                hdr = self.ser.read(4)
                if not hdr:
                    continue
                if hdr != b'FILE':
                    # skip stray bytes
                    continue
                ln_b = self.ser.read(1)
                if not ln_b:
                    continue
                ln = struct.unpack('!B', ln_b)[0]
                name = self.ser.read(ln).decode(errors='ignore')
                size_b = self.ser.read(8)
                if len(size_b) < 8:
                    continue
                size = struct.unpack('!Q', size_b)[0]
                outpath = os.path.join(outdir, name)
                print(f"\n[RECV] Incoming: {name} ({size} bytes) -> {outpath}")
                # ack header
                self.ser.write(b'OK')
                received = 0; start_t = time.perf_counter()
                with open(outpath, 'wb') as f:
                    while True:
                        peek = self.ser.read(4)
                        if not peek:
                            continue
                        if peek == b'DONE':
                            break
                        rest = self.ser.read(2)
                        if len(rest) < 2:
                            continue
                        hdr2 = peek + rest
                        seq, length = struct.unpack('!I H', hdr2)
                        data = self.ser.read(length)
                        crc_raw = self.ser.read(4)
                        if len(data) != length or len(crc_raw) != 4:
                            self.ser.write(b'NAK' + struct.pack('!I', seq))
                            continue
                        crc = struct.unpack('!I', crc_raw)[0]
                        if zlib.crc32(data) & 0xFFFFFFFF == crc:
                            f.write(data)
                            received += length
                            self.ser.write(b'ACK' + struct.pack('!I', seq))
                            line, kbps, eta = progress_line(received, size, start_t)
                            print(line, end='', flush=True)
                        else:
                            self.ser.write(b'NAK' + struct.pack('!I', seq))
                line, kbps, eta = progress_line(size, size, start_t)
                print(line)
                print(f"[+] Received: {name} -> {outpath} @ {kbps:7.2f} KB/s")
        except KeyboardInterrupt:
            print("\n[RECV] Interrupted by user.")
        except Exception as e:
            print("\n[RECV] Exception:", e)
            traceback.print_exc()

# Interactive shell
def input_files(prompt: str):
    raw = input(prompt).strip()
    if not raw:
        return []
    return raw.split()

def interactive():
    print("=== USB Bridge Session (single-run multi-file) ===")
    mode = input("Mode (send / recv / both): ").strip().lower()
    port = input("Serial port (e.g. COM3 or /dev/ttyUSB0): ").strip()
    outdir = input("Default output folder for recv (default .): ").strip() or '.'
    try:
        bridge = SerialBridge(port)
    except Exception as e:
        print("Failed open port:", e); return
    try:
        if mode == 'recv':
            bridge.start_recv_loop(outdir)
            print("[RECV] Running. Press Ctrl+C to stop.")
            while True:
                time.sleep(1)
        elif mode == 'send':
            print("[SEND] Enter file paths to send (space separated). Type 'exit' to quit.")
            while True:
                files = input_files("Files to send: ")
                if not files:
                    cmd = input("No files. Type 'exit' to quit or press Enter to continue: ").strip().lower()
                    if cmd == 'exit':
                        break
                    else:
                        continue
                if len(files) == 1 and files[0].lower() == 'exit':
                    break
                bridge.send_files(files)
                cont = input("Send more? (y/n): ").strip().lower()
                if cont != 'y':
                    break
        elif mode == 'both':
            bridge.start_recv_loop(outdir)
            print("[BOTH] Receiver running in background. You can send anytime. Type 'exit' to quit.")
            while True:
                files = input_files("Files to send: ")
                if not files:
                    cmd = input("No files. Type 'exit' to quit or press Enter to continue: ").strip().lower()
                    if cmd == 'exit':
                        break
                    else:
                        continue
                if len(files) == 1 and files[0].lower() == 'exit':
                    break
                bridge.send_files(files)
                cont = input("Send more? (y/n): ").strip().lower()
                if cont != 'y':
                    q = input("Quit program (y/n)? ").strip().lower()
                    if q == 'y':
                        break
        else:
            print("Invalid mode.")
    except KeyboardInterrupt:
        print("\n[MAIN] Interrupted by user. Exiting.")
    finally:
        bridge.close()
        print("Bye.")

if __name__ == '__main__':
    interactive()
