# Changelog — SecureFileTransfer_FTDI

All notable changes to this project will be documented in this file.  
Format inspired by [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
This project follows **semantic versioning** (MAJOR.MINOR.PATCH).

---

## [v1.1.0] - 2025-09-14
### Added
- PyQt5 GUI frontend (`usb_bridge_gui.py`)
  - Mode selection (Send / Recv / Both)
  - COM port dropdown (auto-detect + refresh)
  - Multi-file selection dialog
  - Output folder chooser
  - Start/Stop buttons with log area
  - Real-time progress bar (percentage, KB/s, ETA)
- Added GUI screenshots under `docs/` folder
- Updated README with GUI usage instructions

### Changed
- Project structure: `docs/` folder for images and future documentation

---

## [v1.0.0] - 2025-09-13
### Added
- Initial release of SecureFileTransfer_FTDI
- Terminal-based file transfer via FTDI USB-to-TTL modules
- Multi-file transfer in one session
- Progress bar with KB/s speed + ETA
- Error recovery with ACK/NAK and retries
- Persistent receiver listener mode
- Cross-platform (Windows/Linux, Python 3.7+)
- Proprietary License included
