# commands.py
from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar, Dict, Any
from .device import DeviceAdapter

class Command:
    name: ClassVar[str] = "base"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        raise NotImplementedError

# ---------- 基本触控 ----------
@dataclass
class ClickCommand(Command):
    x: float
    y: float
    name: ClassVar[str] = "click"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        dev.click(self.x, self.y)
        return {"ok": True, "name": self.name}

@dataclass
class LongPressCommand(Command):
    x: float
    y: float
    duration: float
    name: ClassVar[str] = "long_press"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        dev.long_press(self.x, self.y, self.duration)
        return {"ok": True, "name": self.name}

@dataclass
class DragCommand(Command):
    sx: float
    sy: float
    ex: float
    ey: float
    duration: float
    name: ClassVar[str] = "drag"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        dev.drag(self.sx, self.sy, self.ex, self.ey, self.duration)
        return {"ok": True, "name": self.name}

@dataclass
class SwipeCommand(Command):
    sx: float
    sy: float
    ex: float
    ey: float
    duration: float
    name: ClassVar[str] = "swipe"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        dev.swipe(self.sx, self.sy, self.ex, self.ey, self.duration)
        return {"ok": True, "name": self.name}

# ---------- 文本输入 ----------
@dataclass
class TypeCommand(Command):
    content: str
    name: ClassVar[str] = "type"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        # 直接转发 device 的返回，避免多余加工
        return dev.type_text(self.content)

# ---------- 应用启动 ----------
@dataclass
class OpenAppCommand(Command):
    app_name: str
    name: ClassVar[str] = "open_app"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        return dev.open_app(self.app_name)

# ---------- 系统按键 ----------
class PressHomeCommand(Command):
    name: ClassVar[str] = "press_home"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        dev.press_home()
        return {"ok": True, "name": self.name}

class PressBackCommand(Command):
    name: ClassVar[str] = "press_back"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        dev.press_back()
        return {"ok": True, "name": self.name}

# ---------- 流程结束（非设备操作） ----------
@dataclass
class FinishedCommand(Command):
    content: str
    name: ClassVar[str] = "finished"
    def execute(self, dev: DeviceAdapter) -> Dict[str, Any]:
        return {"ok": True, "name": self.name, "detail": self.content}
