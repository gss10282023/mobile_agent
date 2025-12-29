"""Reusable screenshot utilities for UI automation."""
from __future__ import annotations

from io import BytesIO
from typing import Callable, Optional, Tuple
import base64
import subprocess
import time

from PIL import Image


LogFn = Callable[[str], None]


def pil_to_base64_png(img: Image.Image) -> str:
    """Encode a PIL image as a base64 PNG string."""
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class ScreenshotTool:
    """Centralized screenshot helper that works with uiautomator2 and ADB."""

    def __init__(self, device, log_fn: LogFn = print) -> None:
        self._device = device
        self._log = log_fn

    def capture(self) -> Tuple[Image.Image, Tuple[int, int]]:
        """Take a screenshot at native resolution with retries and ADB fallback."""
        for _ in range(2):
            try:
                img = self._device.d.screenshot()
                return img, img.size
            except Exception:
                time.sleep(0.35)

        try:
            if hasattr(self._device.d, "healthcheck"):
                self._device.d.healthcheck()
        except Exception:
            pass
        time.sleep(0.4)
        try:
            img = self._device.d.screenshot()
            return img, img.size
        except Exception:
            pass

        img = self._adb_screencap()
        return img, img.size

    def _adb_screencap(self) -> Image.Image:
        """Use `adb exec-out screencap -p` as a fallback strategy."""
        serial = self._adb_serial()

        def _take_once() -> Optional[Image.Image]:
            result = self._adb_run(["exec-out", "screencap", "-p"], serial)
            if result.returncode != 0 or not result.stdout:
                return None
            data = result.stdout.replace(b"\r\r\n", b"\n").replace(b"\r\n", b"\n")
            try:
                return Image.open(BytesIO(data))
            except Exception:
                return None

        img = _take_once()
        if img is not None:
            return img

        if self._log:
            self._log("[-] ADB screencap failed, attempting to reconnect and retry...")
        self._ensure_adb_online(serial)
        time.sleep(0.4)

        img = _take_once()
        if img is not None:
            return img

        raise RuntimeError("ADB screencap failed after reconnect (device may be offline).")

    def _adb_run(self, args: list[str], serial: Optional[str]) -> "subprocess.CompletedProcess[bytes]":
        command = ["adb"] + (["-s", serial] if serial else []) + args
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _ensure_adb_online(self, serial: Optional[str]) -> None:
        subprocess.run(["adb", "start-server"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if serial:
            self._adb_run(["wait-for-device"], serial)

    def _adb_serial(self) -> Optional[str]:
        try:
            return getattr(self._device.d, "serial", None)
        except Exception:
            return None
