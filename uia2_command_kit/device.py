# device.py
from __future__ import annotations
from typing import Optional, Dict, Any
import uiautomator2 as u2
from .app_launcher import open_app as launcher_open_app


# 可选：别名 -> 包名；open_app 时会优先使用别名解析
APP_ALIASES: Dict[str, str] = {
    # "calculator": "com.android.calculator2",
}

# 可选：桌面包名集合；用于前台稳定判断时排除桌面
LAUNCHER_PACKAGES: set[str] = {

}

class DeviceAdapter:
    def __init__(self, serial: Optional[str] = None, implicit_wait: float = 10.0):
        """
        implicit_wait: uiautomator2 全局隐式等待时长（秒），用于元素查找的默认超时。
        """
        self.d = u2.connect(serial) if serial else u2.connect()
        # 最小化健康检查：如支持则调用 healthcheck，提升鲁棒性
        try:
            if hasattr(self.d, "healthcheck"):
                self.d.healthcheck()
        except Exception:
            pass
        # 统一设置隐式等待
        try:
            self.d.implicitly_wait(implicit_wait)
        except Exception:
            pass

    # ---------- 原生动作（不预设数值，由调用方传入） ----------
    def click(self, x: float, y: float) -> None:
        self.d.click(x, y)

    def long_press(self, x: float, y: float, duration: float) -> None:
        self.d.long_click(x, y, duration)

    def drag(self, sx: float, sy: float, ex: float, ey: float, duration: float) -> None:
        self.d.drag(sx, sy, ex, ey, duration)

    def swipe(self, sx: float, sy: float, ex: float, ey: float, duration: float) -> None:
        self.d.swipe(sx, sy, ex, ey, duration)

    def press_home(self) -> None:
        self.d.press("home")

    def press_back(self) -> None:
        self.d.press("back")

    # ---------- 输入（多策略兜底） ----------
    def _enable_fast_ime(self) -> None:
        if hasattr(self.d, "set_input_ime"):
            self.d.set_input_ime(True)
        else:
            try:
                self.d.set_fastinput_ime(True)
            except Exception:
                pass

    def type_text(self, content: str) -> Dict[str, Any]:
        """
        返回: {"ok": True/False, "method": "send_keys"/"set_text"/"adb"/"none", "error"?: str}
        说明: 若走到 ADB 分支且 content 以 '\n' 结尾，会自动发送 ENTER (KEYCODE_ENTER)。
        """
        self._enable_fast_ime()

        # 1) send_keys
        try:
            self.d.send_keys(content, clear=False)
            return {"ok": True, "method": "send_keys"}
        except Exception:
            pass

        # 2) set_text 到当前焦点
        try:
            focused = self.d(focused=True)
            if focused.exists:
                focused.set_text(content)
                return {"ok": True, "method": "set_text"}
        except Exception:
            pass

        # 3) ADB input（逐行发送，换行用 ENTER）
        try:
            import re
            parts = re.split(r"\r?\n", content)
            for i, part in enumerate(parts):
                if part:
                    safe = part.replace(" ", "%s")
                    self.d.shell(f'input text "{safe}"')
                if i < len(parts) - 1:
                    self.d.shell("input keyevent 66")  # ENTER between lines
            return {"ok": True, "method": "adb"}
        except Exception as e:
            return {"ok": False, "method": "none", "error": str(e)}

    # ---------- 打开应用（委托给独立模块，保留鲁棒性逻辑） ----------
    def open_app(self, app_name: str) -> Dict[str, Any]:
        """
        接受包名、别名或人类名称；内部按：
        - 别名解析 -> app_start -> monkey 兜底 -> Launcher 搜索
        - 启动后等待前台稳定
        """
        return launcher_open_app(
            self.d,
            app_name=app_name,
            app_aliases=APP_ALIASES,
            launcher_packages=LAUNCHER_PACKAGES,
            timeout=8.0,
        )
