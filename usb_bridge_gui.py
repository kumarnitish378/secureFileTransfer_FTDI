#!/usr/bin/env python3
# -----------------------------------------------------------------------------
#  USB Bridge GUI — PyQt5 frontend for SecureFileTransfer_FTDI
#
#  Copyright (c) 2025 Nitish. All Rights Reserved.
# -----------------------------------------------------------------------------
"""
Run: python usb_bridge_gui.py
Requires: PyQt5, pyserial
Install: pip install PyQt5 pyserial
Note: Place this file in same folder as usb_bridge_session.py (imports SerialBridge)
"""

import sys
import os
import re
import threading
import time
from queue import Queue, Empty

from PyQt5 import QtCore, QtGui, QtWidgets
import serial.tools.list_ports

# Try import backend SerialBridge (from your usb_bridge_session module)
try:
    from usb_bridge_session import SerialBridge
except Exception:
    SerialBridge = None  # GUI will still show but backend calls will error if missing


# ---------- Helpers ----------
PERC_RE = re.compile(r'([0-9]{1,3}\.[0-9]{2})%')
KBPS_RE = re.compile(r'([0-9]+\.[0-9]{2})\s*KB/s')
ETA_RE = re.compile(r'ETA\s+(\d{2}:\d{2})')

def list_serial_ports():
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]


# Thread-safe stdout capture to emit prints to GUI
class StdoutCatcher:
    def __init__(self, emit_func):
        self.emit = emit_func
        self._lock = threading.Lock()

    def write(self, text):
        if not text:
            return
        with self._lock:
            self.emit(text)

    def flush(self):
        pass


# Worker wrapper to run send/recv non-blocking
class TransferWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal()
    log = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(float, float, str)  # percent, kbps, eta

    def __init__(self, port, mode, files, outdir):
        super().__init__()
        self.port = port
        self.mode = mode
        self.files = files or []
        self.outdir = outdir or '.'
        self._stop = threading.Event()
        self._bridge = None

    def _emit_from_stdout(self, s):
        # normalize carriage returns
        s = s.replace('\r', '\n')
        for line in s.splitlines():
            if not line.strip():
                continue
            self.log.emit(line)
            # attempt to parse progress
            m = PERC_RE.search(line)
            kb = KBPS_RE.search(line)
            eta = ETA_RE.search(line)
            try:
                perc = float(m.group(1)) if m else None
                kbps = float(kb.group(1)) if kb else None
                et = eta.group(1) if eta else None
                if perc is not None:
                    self.progress.emit(perc, kbps or 0.0, et or '--:--')
            except Exception:
                pass

    def run(self):
        # Redirect prints from SerialBridge to GUI via StdoutCatcher
        catcher = StdoutCatcher(self._emit_from_stdout)
        old_stdout = sys.stdout
        sys.stdout = catcher
        try:
            # make bridge
            self._bridge = SerialBridge(self.port)
        except Exception as e:
            self.log.emit(f"[ERR] Failed open port {self.port}: {e}")
            sys.stdout = old_stdout
            self.finished.emit()
            return

        try:
            if self.mode == 'recv':
                self.log.emit("[WORKER] Starting receiver loop...")
                # start recv loop in background thread inside SerialBridge
                self._bridge.start_recv_loop(self.outdir)
                while not self._stop.is_set():
                    time.sleep(0.5)
            elif self.mode == 'send':
                self.log.emit(f"[WORKER] Sending files: {self.files}")
                # send_files is blocking. It prints progress which we capture.
                self._bridge.send_files(self.files)
            elif self.mode == 'both':
                self.log.emit("[WORKER] Starting receiver in background and ready to send.")
                self._bridge.start_recv_loop(self.outdir)
                # send if files provided
                if self.files:
                    self._bridge.send_files(self.files)
                # stay alive as listener
                while not self._stop.is_set():
                    time.sleep(0.5)
            else:
                self.log.emit("[ERR] Unknown mode")
        except KeyboardInterrupt:
            self.log.emit("[WORKER] Interrupted by KeyboardInterrupt")
        except Exception as e:
            self.log.emit(f"[ERR] Worker exception: {e}")
        finally:
            try:
                if self._bridge:
                    self._bridge.close()
            except Exception:
                pass
            sys.stdout = old_stdout
            self.finished.emit()

    def stop(self):
        self._stop.set()


# ---------- GUI ----------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SecureFileTransfer_FTDI — GUI")
        self.setMinimumSize(800, 520)
        self._worker_thread = None
        self._worker = None

        # Main layout
        w = QtWidgets.QWidget()
        self.setCentralWidget(w)
        layout = QtWidgets.QVBoxLayout(w)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(12)

        # Top controls: Mode, Port, Baud (readonly), Refresh
        top_h = QtWidgets.QHBoxLayout()
        layout.addLayout(top_h)

        mode_label = QtWidgets.QLabel("Mode:")
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["send", "recv", "both"])
        self.mode_combo.setToolTip("Choose operation mode")

        top_h.addWidget(mode_label)
        top_h.addWidget(self.mode_combo)

        port_label = QtWidgets.QLabel("COM Port:")
        self.port_combo = QtWidgets.QComboBox()
        self.port_combo.setEditable(True)
        self.refresh_ports()

        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_ports)

        top_h.addWidget(port_label)
        top_h.addWidget(self.port_combo)
        top_h.addWidget(refresh_btn)

        # Files and output
        grid = QtWidgets.QGridLayout()
        layout.addLayout(grid)

        self.files_edit = QtWidgets.QLineEdit()
        self.files_edit.setPlaceholderText("Selected files (space-separated)")
        btn_select_files = QtWidgets.QPushButton("Select Files")
        btn_select_files.clicked.connect(self.select_files)

        self.outdir_edit = QtWidgets.QLineEdit()
        self.outdir_edit.setPlaceholderText("Output folder for receiver")
        btn_select_outdir = QtWidgets.QPushButton("Select Output Folder")
        btn_select_outdir.clicked.connect(self.select_outdir)

        grid.addWidget(QtWidgets.QLabel("Files to send:"), 0, 0)
        grid.addWidget(self.files_edit, 0, 1)
        grid.addWidget(btn_select_files, 0, 2)

        grid.addWidget(QtWidgets.QLabel("Output folder:"), 1, 0)
        grid.addWidget(self.outdir_edit, 1, 1)
        grid.addWidget(btn_select_outdir, 1, 2)

        # Buttons
        btn_h = QtWidgets.QHBoxLayout()
        layout.addLayout(btn_h)
        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.on_start)
        self.stop_btn.clicked.connect(self.on_stop)
        btn_h.addWidget(self.start_btn)
        btn_h.addWidget(self.stop_btn)

        # Progress & stats
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0,10000)  # use 2-decimal percent as int
        self.progress_label = QtWidgets.QLabel("0.00%   0.00 KB/s   ETA --:--")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)

        # Log area
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        font = QtGui.QFont("Consolas", 10)
        self.log_view.setFont(font)
        layout.addWidget(self.log_view, 1)

        # Footer small help
        footer = QtWidgets.QLabel("Note: Ensure both sides use same baud and wiring. Press Stop to end listener.")
        footer.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(footer)

        # Shortcuts
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+R"), self, activated=self.refresh_ports)

    def refresh_ports(self):
        ports = list_serial_ports()
        self.port_combo.clear()
        if ports:
            self.port_combo.addItems(ports)
        else:
            self.port_combo.addItem("COM3")  # hint

    def select_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Select files to send")
        if files:
            self.files_edit.setText(" ".join(files))

    def select_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select output folder")
        if d:
            self.outdir_edit.setText(d)

    def append_log(self, text):
        # thread-safe append
        self.log_view.appendPlainText(text)
        # auto-scroll
        cursor = self.log_view.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.log_view.setTextCursor(cursor)

    def update_progress(self, percent, kbps, eta):
        try:
            p = float(percent)
            val = int(round(p*100))  # keep 2 decimals: 100.00% -> 10000
            self.progress_bar.setValue(val)
            self.progress_label.setText(f"{p:6.2f}%   {kbps:7.2f} KB/s   ETA {eta}")
        except Exception:
            pass

    def on_start(self):
        port = self.port_combo.currentText().strip()
        if not port:
            self.append_log("[ERR] Select COM port first")
            return
        mode = self.mode_combo.currentText()
        files = self.files_edit.text().strip()
        files_list = files.split() if files else []
        outdir = self.outdir_edit.text().strip() or '.'

        # disable start
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.append_log(f"[UI] Starting mode={mode} port={port}")

        # create worker
        self._worker = TransferWorker(port, mode, files_list, outdir)
        self._worker.log.connect(self.append_log)
        self._worker.progress.connect(self.update_progress)
        self._worker.finished.connect(self.on_worker_finished)

        # run worker in QThread
        self._worker_thread = QtCore.QThread()
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker_thread.start()

    def on_stop(self):
        self.append_log("[UI] Stopping...")
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(True)
        if self._worker:
            try:
                self._worker.stop()
            except Exception:
                pass
        if self._worker_thread:
            try:
                self._worker_thread.quit()
                self._worker_thread.wait(1000)
            except Exception:
                pass
        self.append_log("[UI] Stopped.")

    def on_worker_finished(self):
        self.append_log("[WORKER] Finished.")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        # ensure thread cleanup
        if self._worker_thread:
            try:
                self._worker_thread.quit()
                self._worker_thread.wait(500)
            except Exception:
                pass
        self._worker = None
        self._worker_thread = None


def main():
    app = QtWidgets.QApplication(sys.argv)
    # set fusion style for consistent look
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
