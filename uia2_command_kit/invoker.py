# invoker.py
from __future__ import annotations
from typing import List, Dict, Any, Optional, Type, Callable
import time

from .device import DeviceAdapter
from .commands import (
    Command, ClickCommand, LongPressCommand, TypeCommand, SwipeCommand,
    OpenAppCommand, DragCommand, PressHomeCommand, PressBackCommand, FinishedCommand
)

# --- 仅作为可选工厂：字符串命令名 -> 命令类（不做任何解析/转换） ---
COMMAND_REGISTRY: Dict[str, Type[Command]] = {
    "click": ClickCommand,
    "long_press": LongPressCommand,
    "type": TypeCommand,
    "swipe": SwipeCommand,          # 注意：已替代 scroll
    "open_app": OpenAppCommand,
    "drag": DragCommand,
    "press_home": PressHomeCommand,
    "press_back": PressBackCommand,
    "finished": FinishedCommand,
}

def build_command(name: str, **kwargs) -> Command:
    cls = COMMAND_REGISTRY.get(name)
    if not cls:
        raise ValueError(f"未知命令：{name}")
    # kwargs 必须已在上游解析好（数值坐标/显式 duration 等）
    return cls(**kwargs)  # type: ignore[arg-type]

class Invoker:
    """
    纯粹的命令调用者：只执行，不构造、不解析。
    等待策略：base + per-command extra + duration_factor * cmd.duration(若有)
    """
    def __init__(
        self,
        device: DeviceAdapter,
        base_settle_ms: int = 200,
        duration_factor: float = 0.6,         # 每 1s 手势时长，额外等 0.6s
        settle_extras: Optional[Dict[str, int]] = None,
        log_fn: Optional[Callable[[str], None]] = print,
    ):
        self.device = device
        self.base_settle_ms = base_settle_ms
        self.duration_factor = max(0.0, duration_factor)
        # 基础额外等待（毫秒）：可按需覆盖
        self.settle_extras = {
            "open_app": 210,                  # app_launcher 已等待“前台稳定”，这里只做 UI 缓冲
            "type": 200,
            "type_submit": 400,               # type 且 content 以 \n 结尾
            "swipe": 200,
            "drag": 250,
            "long_press": 150,
            "click": 120,
            "press_home": 120,
            "press_back": 120,
            "finished": 0,
            "_default": 180,                  # 未列出时的默认
            **(settle_extras or {}),
        }
        self.log = log_fn

    def _settle_after(self, cmd: Command):
        # 1) 基于命令类型的基础 extra
        name = getattr(cmd, "name", cmd.__class__.__name__)
        if name == "type":
            content = getattr(cmd, "content", "")
            extra = self.settle_extras["type_submit"] if isinstance(content, str) and content.endswith("\n") \
                    else self.settle_extras["type"]
        else:
            extra = self.settle_extras.get(name, self.settle_extras["_default"])

        # 2) 基于命令自带 duration（若有）的动态 extra
        duration_s = getattr(cmd, "duration", 0.0)
        try:
            dyn = int(float(duration_s) * 1000 * self.duration_factor)
        except Exception:
            dyn = 0

        # 3) 合计
        ms = max(0, int(self.base_settle_ms + extra + dyn))
        if self.log:
            self.log(f"    ...等待界面稳定 {ms}ms")
        time.sleep(ms / 1000.0)

    def run(self, commands: List[Command]) -> List[Dict[str, Any]]:
        """
        顺序执行命令。Invoker 只负责调用与等待；不改变命令的返回。
        - 每条命令执行后统一 _settle_after()
        - 如命令抛异常，异常将向外冒泡（保持“非必要不做”原则）
        """
        results: List[Dict[str, Any]] = []
        for i, cmd in enumerate(commands, 1):
            res = cmd.execute(self.device)               # 不包 try/except：按需在更上层决定是否捕获
            # 最小化处理：补充 name/index，其他字段由命令自己决定（ok/detail/error）
            res.setdefault("name", getattr(cmd, "name", cmd.__class__.__name__))
            res["index"] = i
            results.append(res)
            if self.log:
                mark = "✓" if res.get("ok", True) else "x"
                detail = res.get("detail", "") or res.get("error", "")
                self.log(f"[{mark}][{i}] {res['name']}: {detail}")
            # 统一收敛等待
            self._settle_after(cmd)
        return results
