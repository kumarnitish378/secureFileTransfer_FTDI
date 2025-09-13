# SecureFileTransfer_FTDI — Secure File Transfer (FTDI)


A terminal-based file transfer app for two PCs using FTDI USB-to-TTL adapters.  
Supports multi-file transfer, retries, error recovery, and real-time progress (KB/s + ETA).

This project is a terminal-based app to transfer files between two PCs using FTDI USB-to-TTL adapters.  
It supports **multi-file transfer**, **progress bar with KB/s + ETA**, **error recovery**, and runs in a **single session** (no need to restart after each file).

---

## 🔧 Hardware Setup
- 2 × FT232RL USB-TTL modules (both configured to same voltage 3.3V **or** 5V).
- Make connections:
  - FT1 TX → FT2 RX
  - FT1 RX ← FT2 TX
  - FT1 GND ↔ FT2 GND
- ⚠️ Do NOT connect USB VBUS between the modules.
- Use short, good-quality jumper wires.

### 🔌 Wiring Diagram

 PC A (FTDI)           PC B (FTDI)
 -----------           -----------
   TX  -------------->   RX

   RX  <--------------   TX
   
   GND ---------------- GND

---

## 💻 Software Requirements
- Python 3.7 or later  
- Install pyserial: `pip install pyserial`



# ▶️ How to Run
## On Receiver PC
- python usb_bridge_session.py
- Mode: recv
- Serial port: COM3
- Output folder: recFile

> Receiver will continuously listen for files.

## On Sender PC
- python usb_bridge_session.py
- Mode: send
- Serial port: COM4
- Files to send: file1.bin file2.png

## On Both Mode

One PC can run in both mode (listen + send together).

# ⚡ Tips & Troubleshooting

- Both PCs must use the same baud rate (default 115200).
- To increase transfer speed, change BAUD in code (try 1_000_000 or 2_000_000).
- If transfer hangs, check TX/RX/GND wiring and correct COM port names.
- Use Ctrl+C to exit cleanly.