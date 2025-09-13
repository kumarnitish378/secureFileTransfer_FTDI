#!/usr/bin/env python3
"""
usb_bridge_session.py
Single-session interactive USB-to-USB bridge app.
Usage: python usb_bridge_session.py
Modes: send | recv | both
Requires: pyserial
"""

import os, sys, struct, zlib, time, threading, queue, traceback
from typing import List
import serial

# ---------- Config ----------
CHUNK = 4096
BAUD = 115200
CHUNK_RETRIES = 5
HEADER_RETRIES = 8
# ----------------------------

def progress_bar(sent, total, width=34):
    pct = sent/total if total else 1.0
    filled = int(width*pct)
    bar = '[' + '#' * filled + '-'*(width-filled) + ']'
    print(f"\r{bar} {pct*100:6.2f}% {sent}/{total} bytes", end='', flush=True)

class TransferError(Exception):
    pass

class SerialBridge:
    def __init__(self, port: str, blocking=True):
        self.port = port
        self.blocking = blocking
        # blocking reads if timeout=None
        self.ser = serial.Serial(port, BAUD, timeout=None if blocking else 1)
        # flush stale bytes
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception:
            pass
        self.recv_thread = None
        self.recv_stop = threading.Event()
        self.recv_queue = queue.Queue()  # for optional notifications

    def close(self):
        try:
            self.recv_stop.set()
            if self.recv_thread and self.recv_thread.is_alive():
                self.recv_thread.join(timeout=1)
            self.ser.close()
        except Exception:
            pass

    # ---- Sending ----
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
        fname_bytes = os.path.basename(filepath).encode()
        hdr = b'FILE' + struct.pack('!B', len(fname_bytes)) + fname_bytes + struct.pack('!Q', size)

        # Handshake header with retries
        for attempt in range(HEADER_RETRIES):
            self.ser.write(hdr)
            # blocking read for 2 bytes (OK)
            resp = self.ser.read(2)
            if resp == b'OK':
                break
            time.sleep(0.2)
        else:
            raise TransferError("No OK from receiver. Ensure receiver running and ports connected.")

        # Send chunks
        sent = 0
        seq = 0
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(CHUNK)
                if not data:
                    break
                pkt = struct.pack('!I H', seq, len(data)) + data + struct.pack('!I', zlib.crc32(data) & 0xFFFFFFFF)
                for attempt in range(CHUNK_RETRIES):
                    self.ser.write(pkt)
                    ack = self.ser.read(7)  # expect ACK/NAK + 4-byte seq
                    if not ack:
                        # no response, retry
                        time.sleep(0.05)
                        continue
                    if ack.startswith(b'ACK'):
                        ackseq = struct.unpack('!I', ack[3:7])[0]
                        if ackseq == seq:
                            sent += len(data)
                            progress_bar(sent, size)
                            break
                        else:
                            # unexpected seq; treat as retry
                            continue
                    elif ack.startswith(b'NAK'):
                        time.sleep(0.05)
                        continue
                    else:
                        # unknown response, retry
                        time.sleep(0.05)
                        continue
                else:
                    raise TransferError(f"Chunk seq {seq} failed after retries.")
                seq += 1

        # Finish
        self.ser.write(b'DONE')      # 4 bytes marker
        try:
            self.ser.flush()
        except Exception:
            pass
        progress_bar(size, size)
        print(f"\n[+] Sent: {os.path.basename(filepath)} ({size} bytes)")

    # ---- Receiving ----
    def start_recv_loop(self, outdir: str = '.', notify_via_queue: bool = False):
        self.recv_stop.clear()
        self.recv_thread = threading.Thread(target=self._recv_loop, args=(outdir, notify_via_queue), daemon=True)
        self.recv_thread.start()

    def _recv_loop(self, outdir: str, notify_via_queue: bool):
        os.makedirs(outdir, exist_ok=True)
        print(f"[RECV] Listening on {self.port}. Save to: {os.path.abspath(outdir)}")
        try:
            while not self.recv_stop.is_set():
                # Wait for header 'FILE' (blocking read)
                hdr = self.ser.read(4)
                if not hdr:
                    # shouldn't happen in blocking mode, but safe guard
                    continue
                if hdr != b'FILE':
                    # noisy/stale bytes: keep scanning
                    continue

                # read name length, name and size
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
                print(f"\n[RECV] Incoming: {name}  ({size} bytes) -> {outpath}")
                # ACK header
                self.ser.write(b'OK')

                received = 0
                with open(outpath, 'wb') as f:
                    while True:
                        # read first 4 bytes to check for DONE or start of header
                        peek = self.ser.read(4)
                        if not peek:
                            continue
                        if peek == b'DONE':
                            # consume any extra if needed, stop file receive
                            break
                        # peek holds first 4 bytes of normal 6-byte header (seq(4) low/high)
                        # we already have 4 bytes, so read remaining 2 bytes of header
                        rest_hdr = self.ser.read(2)
                        if len(rest_hdr) < 2:
                            # incomplete header, continue loop to retry
                            continue
                        hdr2 = peek + rest_hdr  # full 6 bytes
                        seq, length = struct.unpack('!I H', hdr2)
                        # read exact payload and crc
                        data = self.ser.read(length)
                        crc_raw = self.ser.read(4)
                        if len(data) != length or len(crc_raw) != 4:
                            # missing -> NAK and continue
                            self.ser.write(b'NAK' + struct.pack('!I', seq))
                            continue
                        crc = struct.unpack('!I', crc_raw)[0]
                        if zlib.crc32(data) & 0xFFFFFFFF == crc:
                            f.write(data)
                            received += length
                            self.ser.write(b'ACK' + struct.pack('!I', seq))
                            progress_bar(received, size)
                        else:
                            self.ser.write(b'NAK' + struct.pack('!I', seq))
                progress_bar(size, size)
                print(f"\n[+] Received: {name} -> {outpath}")
                if notify_via_queue:
                    self.recv_queue.put(outpath)
                # Now loop to listen for next file
        except KeyboardInterrupt:
            print("\n[RECV] Stopping (Ctrl+C).")
        except Exception as e:
            print("\n[RECV] Exception:", e)
            traceback.print_exc()

# ---------- Interactive shell ----------
def input_files(prompt: str) -> List[str]:
    raw = input(prompt).strip()
    if not raw:
        return []
    parts = raw.split()
    return parts

def interactive():
    print("=== USB Bridge Session (single-run multi-file) ===")
    mode = input("Mode (send / recv / both) : ").strip().lower()
    port = input("Serial port (e.g. COM3 or /dev/ttyUSB0): ").strip()
    outdir = input("Default output folder for recv (default .): ").strip() or '.'

    bridge = None
    try:
        bridge = SerialBridge(port)
    except Exception as e:
        print("Failed to open serial port:", e)
        return

    try:
        if mode == 'recv':
            bridge.start_recv_loop(outdir)
            print("[RECV] Running. Press Ctrl+C to stop.")
            while True:
                time.sleep(1)  # keep main alive
        elif mode == 'send':
            print("[SEND] Enter file paths to send (space separated). Type 'exit' to quit.")
            while True:
                files = input_files("Files to send: ")
                if not files:
                    # maybe user typed nothing; confirm continue
                    cmd = input("No files. Type 'exit' to quit or press Enter to continue: ").strip().lower()
                    if cmd == 'exit':
                        break
                    else:
                        continue
                if len(files) == 1 and files[0].lower() == 'exit':
                    break
                bridge.send_files(files)
                # after batch, ask continue
                cont = input("Send more? (y/n): ").strip().lower()
                if cont != 'y':
                    break
        elif mode == 'both':
            # start receiver thread and let user send interactively
            bridge.start_recv_loop(outdir, notify_via_queue=False)
            print("[BOTH] Receiver running in background. You can send files anytime.")
            print("Enter file paths to send (space separated). Type 'exit' to quit.")
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
                    # continue listening; ask if user wants to quit entirely
                    q = input("Quit program (y/n)? ").strip().lower()
                    if q == 'y':
                        break
                    else:
                        continue
        else:
            print("Invalid mode.")
    except KeyboardInterrupt:
        print("\n[MAIN] Interrupted by user. Exiting.")
    finally:
        if bridge:
            bridge.close()
        print("Bye.")

if __name__ == '__main__':
    interactive()
