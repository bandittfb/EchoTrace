"""USB foot pedal listener for Banditt-Tek EchoTrace.

Supports the VEC Infinity USB Foot Pedal (VID 0x05F3, PID 0x00FF), the
classic transcription pedal that ships with Express Scribe. The pedal is
a raw HID device — Windows detects it but sends no keystrokes, so apps
must read its HID reports directly.

Wire protocol (for VEC Infinity):
    Byte 0: button bitmask
        0x01 = left pedal
        0x02 = center pedal
        0x04 = right pedal
        0x00 = all released
    Byte 1: unused

Usage:
    listener = FootPedalListener()
    listener.pressed.connect(handler)
    listener.start()
"""
from __future__ import annotations

from enum import IntEnum

import hid
from PySide6.QtCore import QThread, Signal

# Known pedal models. Extend this list as we support more.
KNOWN_PEDALS = [
    {"vid": 0x05F3, "pid": 0x00FF, "name": "VEC Infinity USB Foot Pedal"},
]


class PedalButton(IntEnum):
    """Bitmask values that match what the pedal reports."""
    LEFT = 0x01
    CENTER = 0x02
    RIGHT = 0x04


class FootPedalListener(QThread):
    """Background thread that reads the pedal and emits Qt signals.

    Signals are delivered on the Qt event loop, so handlers can touch UI
    widgets safely.
    """

    pressed = Signal(int)          # PedalButton value
    released = Signal(int)         # PedalButton value
    connected = Signal(str)        # pedal name
    disconnected = Signal()
    error = Signal(str)            # human-readable error

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._running = False
        self._device: hid.device | None = None
        self._last_state = 0
        self._pedal_name = ""

    # -- Discovery ----------------------------------------------------------

    @staticmethod
    def find_pedal() -> dict | None:
        """Return the first connected pedal descriptor, or None."""
        for pedal in KNOWN_PEDALS:
            matches = hid.enumerate(pedal["vid"], pedal["pid"])
            if matches:
                return {**pedal, "path": matches[0]["path"]}
        return None

    @staticmethod
    def is_connected() -> bool:
        return FootPedalListener.find_pedal() is not None

    # -- Thread loop --------------------------------------------------------

    def run(self) -> None:
        self._running = True
        # Reconnection loop: if the pedal is unplugged mid-session,
        # keep trying to find it again until stop() is called.
        while self._running:
            pedal = self.find_pedal()
            if pedal is None:
                # No pedal present — sleep and retry
                self.msleep(1500)
                continue

            try:
                self._device = hid.device()
                self._device.open_path(pedal["path"])
                self._device.set_nonblocking(False)
                self._pedal_name = pedal["name"]
                self._last_state = 0
                self.connected.emit(self._pedal_name)
                self._read_loop()
            except OSError as exc:
                self.error.emit(f"Could not open pedal: {exc}")
                self.msleep(2000)
            finally:
                if self._device is not None:
                    try:
                        self._device.close()
                    except Exception:
                        pass
                    self._device = None
                if self._pedal_name:
                    self.disconnected.emit()
                    self._pedal_name = ""

    def _read_loop(self) -> None:
        """Blocking read loop. Exits when device errors or stop() is called."""
        assert self._device is not None
        while self._running:
            try:
                data = self._device.read(8, timeout_ms=500)
            except OSError:
                # Device disconnected or disappeared
                break
            if not data:
                continue
            state = data[0] & 0x07  # low 3 bits = L|C|R
            if state == self._last_state:
                continue
            # Figure out which buttons changed
            changed = state ^ self._last_state
            for button in (PedalButton.LEFT, PedalButton.CENTER, PedalButton.RIGHT):
                if changed & button:
                    if state & button:
                        self.pressed.emit(int(button))
                    else:
                        self.released.emit(int(button))
            self._last_state = state

    def stop(self) -> None:
        self._running = False
        self.wait(2000)
