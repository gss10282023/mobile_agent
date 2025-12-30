# action_executor.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, Optional, List, Dict, Any, Callable
import time
from .action_parser import MobileAction
# 引入你已有的三件套（不修改它们）
from uia2_command_kit.device import DeviceAdapter
from uia2_command_kit.invoker import Invoker
from uia2_command_kit.commands import (
    ClickCommand, LongPressCommand, TypeCommand, SwipeCommand,
    OpenAppCommand, DragCommand, PressHomeCommand, PressBackCommand, FinishedCommand
)

# =========================================================
# 坐标映射：渲染图 (render) -> 设备屏幕 (device)
# =========================================================
@dataclass
class CoordinateMapper:
    render_w: int
    render_h: int
    device_w: int
    device_h: int
    # 渲染图中的有效区域（去黑边/裁剪），(vx,vy,vw,vh)。若 vw/vh<=0 视为整图有效
    valid_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
    # 渲染图相对设备的旋转角（度）：0/90/180/270
    rotation: int = 0

    def to_device(self, pt: Tuple[float, float]) -> Tuple[int, int]:
        x, y = pt
        vx, vy, vw, vh = self.valid_rect
        if vw <= 0 or vh <= 0:
            vx, vy, vw, vh = 0, 0, self.render_w, self.render_h

        # 1) 去偏移 + 归一化到有效区域
        nx = (x - vx) / float(vw)
        ny = (y - vy) / float(vh)

        # 2) 旋转（以归一化坐标域为基准）
        r = self.rotation % 360
        if r == 90:
            nx, ny = ny, 1 - nx
        elif r == 180:
            nx, ny = 1 - nx, 1 - ny
        elif r == 270:
            nx, ny = 1 - ny, nx
        # 其它角度不支持（通常没必要）

        # 3) 放缩到设备像素
        X = int(round(nx * self.device_w))
        Y = int(round(ny * self.device_h))
        # 4) 夹紧到屏幕范围
        X = max(0, min(self.device_w - 1, X))
        Y = max(0, min(self.device_h - 1, Y))
        return X, Y


# =========================================================
# 执行器抽象（沿用 Step 1）
# =========================================================
class ActionExecutor:
    def execute(self, action: MobileAction):
        raise NotImplementedError


# =========================================================
# ADB 执行器：把 MobileAction 变成 commands & invoker.run()
# =========================================================
@dataclass
class ExecutorConfig:
    # 手势默认时长（秒）
    long_press_s: float = 0.6
    drag_s: float = 0.40
    swipe_s: float = 0.25
    # scroll 的位移比例（相对渲染图边长）
    scroll_frac: float = 0.28
    # 预设：wait() 的等待秒数
    wait_s: float = 1.0
    # 打印日志
    log_fn: Optional[Callable[[str], None]] = print
    # dry-run：只打印命令，不真的执行
    dry_run: bool = True


class ADBExecutor(ActionExecutor):
    """
    把解析出的 MobileAction：
      -> 坐标映射（渲染图 -> 设备）
      -> 构造 commands.py 中的 Command
      -> 使用 invoker.run() 执行（或 dry-run 打印）
    """
    def __init__(
        self,
        device: DeviceAdapter,
        invoker: Invoker,
        render_size: Tuple[int, int],
        valid_rect: Optional[Tuple[int, int, int, int]] = None,
        rotation: int = 0,
        config: Optional[ExecutorConfig] = None,
    ):
        self.device = device
        self.invoker = invoker
        self.render_w, self.render_h = render_size
        self.valid_rect = valid_rect or (0, 0, 0, 0)
        self.rotation = rotation
        self.cfg = config or ExecutorConfig()

    # ---- 工具：获取设备分辨率 ----
    def _device_size(self) -> Tuple[int, int]:
        # uiautomator2: d.window_size() -> (w, h)
        try:
            w, h = self.device.d.window_size()  # type: ignore[attr-defined]
            return int(w), int(h)
        except Exception:
            # fallback: d.info
            try:
                info = self.device.d.info  # type: ignore[attr-defined]
                return int(info.get("displayWidth", 1080)), int(info.get("displayHeight", 1920))
            except Exception:
                # 最保守兜底
                return (1080, 1920)

    def _mapper(self) -> CoordinateMapper:
        dw, dh = self._device_size()
        return CoordinateMapper(
            render_w=self.render_w, render_h=self.render_h,
            device_w=dw, device_h=dh,
            valid_rect=self.valid_rect, rotation=self.rotation
        )

    # ---- 执行入口 ----
    def execute(self, action: MobileAction) -> List[Dict[str, Any]]:
        t = action.type
        p = action.params
        mapper = self._mapper()

        cmds: List[Any] = []

        if t == "click":
            X, Y = mapper.to_device(p["point"])
            cmds.append(ClickCommand(x=X, y=Y))

        elif t == "long_press":
            X, Y = mapper.to_device(p["point"])
            cmds.append(LongPressCommand(x=X, y=Y, duration=self.cfg.long_press_s))

        elif t == "type":
            content: str = p["content"]
            cmds.append(TypeCommand(content=content))

        elif t == "open_app":
            cmds.append(OpenAppCommand(app_name=p["app_name"]))

        elif t == "press_home":
            cmds.append(PressHomeCommand())

        elif t == "press_back":
            cmds.append(PressBackCommand())


        elif t == "drag":
            sx, sy = mapper.to_device(p["start_point"])
            ex, ey = mapper.to_device(p["end_point"])
            cmds.append(DragCommand(sx=sx, sy=sy, ex=ex, ey=ey, duration=self.cfg.drag_s))

        elif t == "scroll":
            # UI-TARS: scroll(point, direction)
            # 规则：content 向下滚动 → 手指向上滑
            start_render_x, start_render_y = p["point"]
            direction = p["direction"].lower()
            # 位移像素（在渲染图坐标系下计算）
            dx = dy = 0.0
            if direction in ("up", "down"):
                mag = self.cfg.scroll_frac * self.render_h
                dy = +mag if direction == "up" else -mag  # up=手指向下, down=手指向上
            elif direction in ("left", "right"):
                mag = self.cfg.scroll_frac * self.render_w
                dx = +mag if direction == "left" else -mag  # left=手指向右, right=手指向左
            else:
                raise ValueError(f"未知 scroll 方向：{direction}")

            end_render_x = start_render_x + dx
            end_render_y = start_render_y + dy

            sx, sy = mapper.to_device((start_render_x, start_render_y))
            ex, ey = mapper.to_device((end_render_x, end_render_y))
            cmds.append(SwipeCommand(sx=sx, sy=sy, ex=ex, ey=ey, duration=self.cfg.swipe_s))

        elif t == "hotkey":
            key = str(p.get("key", "")).strip().lower()
            if key in ("enter", "return", "search", "go"):
                # 用 TypeCommand('\n') 触发输入法提交；Invoker 会用 type_submit 额外等待
                cmds.append(TypeCommand(content="\n"))
            elif key in ("back", "esc"):
                cmds.append(PressBackCommand())
            elif key in ("home", "meta"):
                cmds.append(PressHomeCommand())
            else:
                raise ValueError(f"未知/不支持的热键：{key}")


        elif t == "wait":
            seconds = float(self.cfg.wait_s)  # 一律使用预设
            if self.cfg.log_fn:
                self.cfg.log_fn(f"[WAIT] sleep {seconds:.2f}s")
            if not self.cfg.dry_run:
                time.sleep(seconds)
            # 与 invoker 风格一致的结果；wait 不经由 commands/invoker
            return [{"ok": True, "name": "wait", "index": 1, "detail": f"sleep {seconds:.2f}s"}]


        elif t == "finished":
            cmds.append(FinishedCommand(content=p.get("content", "")))

        else:
            raise ValueError(f"未知动作类型：{t}")

        if self.cfg.dry_run:
            # 打印“将要执行”的命令（含已映射坐标）
            if self.cfg.log_fn:
                for i, c in enumerate(cmds, 1):
                    self.cfg.log_fn(f"[DRY-RUN {i}] {c}")
            # 伪造 invoker 风格返回
            return [{"ok": True, "name": getattr(c, "name", c.__class__.__name__), "index": i} for i, c in enumerate(cmds, 1)]


        # 真正执行
        results = self.invoker.run(cmds)
        return results
