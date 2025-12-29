# testui2.py
from __future__ import annotations
from typing import List, Optional
import subprocess
import time
import os
import signal
from contextlib import contextmanager

from device import DeviceAdapter
from invoker import Invoker
from commands import (
    Command,
    ClickCommand, LongPressCommand, DragCommand, SwipeCommand,
    TypeCommand, OpenAppCommand, PressHomeCommand, PressBackCommand,
    FinishedCommand,
)

# --------------------
# 设备连接参数
# --------------------
SERIAL: str | None = None        # 例如 "emulator-5554"；None=默认连接
IMPLICIT_WAIT: float = 10.0      # uiautomator2 全局隐式等待（秒）

# --------------------
# 录屏与触摸可视化（可选）
# --------------------
ENABLE_RECORD: bool = True
RECORD_LOCAL_PATH: str = "./run.mp4"
RECORD_REMOTE_PATH: str = "/sdcard/_auto_run.mp4"
RECORD_BITRATE: int = 6_000_000  # bps

ENABLE_SHOW_TOUCHES: bool = True  # 开启“显示触摸/指针轨迹”（推荐录屏时开启）

# --------------------
# 测试开关（按需逐步启用）
# --------------------
ENABLE_OPEN_APP   = True
ENABLE_CLICK      = False
ENABLE_LONG_PRESS = False
ENABLE_DRAG       = False
ENABLE_SWIPE      = False
ENABLE_TYPE       = False
ENABLE_PRESS_HOME = False
ENABLE_PRESS_BACK = False
ENABLE_FINISHED   = True   # 建议保留：用于标记流程结束

# --------------------
# 精准参数（请替换为你设备的真实值）
# --------------------
OPEN_APP_PACKAGE = "settings"

CLICK_X = 540.0; CLICK_Y = 1600.0

LONG_X = 540.0; LONG_Y = 1600.0; LONG_DUR = 3   # 秒

DRAG_SX = 540.0; DRAG_SY = 1600.0
DRAG_EX = 540.0; DRAG_EY = 400.0
DRAG_DUR = 0.40  # 秒

SWIPE_SX = 540.0; SWIPE_SY = 1600.0
SWIPE_EX = 540.0; SWIPE_EY = 400.0
SWIPE_DUR = 0.25  # 秒

TYPE_TEXT = "hello"  # 如需“提交”，末尾加 '\n'

# --------------------
# ADB 辅助函数
# --------------------
def adb_prefix(serial: Optional[str]) -> list[str]:
    return ["adb"] + (["-s", serial] if serial else [])

def run_adb(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)

def ensure_show_touches(serial: Optional[str], enable: bool = True) -> None:
    """开启/关闭 显示触摸 & 指针轨迹（不区分 system/secure，双写更保险）。"""
    val = "1" if enable else "0"
    for ns in ("system", "secure"):
        for key in ("show_touches", "pointer_location"):
            run_adb(adb_prefix(serial) + ["shell", "settings", "put", ns, key, val])

def _stop_screenrecord_on_device(serial: Optional[str]) -> None:
    """
    给设备端 screenrecord 发送 SIGINT（优雅收尾写 moov）。
    兼容常见 toybox：pkill 或 pidof + kill -2。
    """
    sh = (
        "if command -v pkill >/dev/null 2>&1; then pkill -2 screenrecord; "
        "elif command -v pidof >/dev/null 2>&1; then sr=$(pidof screenrecord) && kill -2 $sr; "
        "fi"
    )
    run_adb(adb_prefix(serial) + ["shell", "sh", "-c", sh])

@contextmanager
def screen_record(serial: Optional[str], remote_path: str, local_path: str, bitrate: int = 6_000_000):
    """
    方案1（优雅停止版）：
    - 启动 adb shell screenrecord（无 time-limit）
    - 退出上下文时：
        1) 发送 SIGINT 给设备上的 screenrecord（写入 moov）
        2) 结束本地 adb 进程（SIGINT -> terminate -> kill）
        3) 等待退出、短暂缓冲，再 pull MP4 到本地并清理远端文件
    """
    cmd = adb_prefix(serial) + [
        "shell", "screenrecord",
        f"--bit-rate={bitrate}",
        remote_path,
    ]
    proc = subprocess.Popen(cmd)
    try:
        yield
    finally:
        # 1) 先优雅停止设备端 screenrecord
        try:
            _stop_screenrecord_on_device(serial)
        except Exception:
            pass

        # 2) 再结束本地 adb 进程
        try:
            proc.send_signal(getattr(signal, "SIGINT", signal.SIGTERM))
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

        # 3) 等待退出，若卡住则强杀
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except Exception:
                pass

        # 4) 给文件系统/封装器留一点时间
        time.sleep(0.6)

        # 5) 拉取并清理远端文件
        run_adb(adb_prefix(serial) + ["pull", remote_path, local_path])
        run_adb(adb_prefix(serial) + ["shell", "rm", "-f", remote_path])
        print(f"[录屏] 已保存到: {os.path.abspath(local_path)}")

# --------------------
# 组装测试命令
# --------------------
def build_commands() -> List[Command]:
    cmds: List[Command] = []
    if ENABLE_OPEN_APP:
        cmds.append(OpenAppCommand(app_name=OPEN_APP_PACKAGE))
    if ENABLE_CLICK:
        cmds.append(ClickCommand(x=CLICK_X, y=CLICK_Y))
    if ENABLE_LONG_PRESS:
        cmds.append(LongPressCommand(x=LONG_X, y=LONG_Y, duration=LONG_DUR))
    if ENABLE_DRAG:
        cmds.append(DragCommand(sx=DRAG_SX, sy=DRAG_SY, ex=DRAG_EX, ey=DRAG_EY, duration=DRAG_DUR))
    if ENABLE_SWIPE:
        cmds.append(SwipeCommand(sx=SWIPE_SX, sy=SWIPE_SY, ex=SWIPE_EX, ey=SWIPE_EY, duration=SWIPE_DUR))
    if ENABLE_TYPE:
        cmds.append(TypeCommand(content=TYPE_TEXT))
    if ENABLE_PRESS_HOME:
        cmds.append(PressHomeCommand())
    if ENABLE_PRESS_BACK:
        cmds.append(PressBackCommand())
    if ENABLE_FINISHED:
        cmds.append(FinishedCommand(content="测试完成"))
    return cmds

# --------------------
# 主函数
# --------------------
def main() -> None:
    # 可选：开启触摸可视化（白点 + 轨迹）
    if ENABLE_SHOW_TOUCHES:
        ensure_show_touches(SERIAL, True)

    # 连接设备
    dev = DeviceAdapter(serial=SERIAL, implicit_wait=IMPLICIT_WAIT)

    # Invoker（只负责执行与等待，不做解析）
    inv = Invoker(
        device=dev,
        base_settle_ms=200,
        duration_factor=0.6,  # 不想要“随手势时长增加等待”则设为 0.0
    )

    # 构建命令
    commands = build_commands()
    if not commands:
        print("未启用任何测试。把需要的 ENABLE_* 置为 True 再运行。")
        return

    # 执行（可选录屏）
    if ENABLE_RECORD:
        with screen_record(SERIAL, RECORD_REMOTE_PATH, RECORD_LOCAL_PATH, bitrate=RECORD_BITRATE):
            results = inv.run(commands)
    else:
        results = inv.run(commands)

    # 汇总输出
    print("\n=== 测试结果汇总 ===")
    for r in results:
        idx = r.get("index")
        name = r.get("name")
        ok = r.get("ok", True)
        info = r.get("detail") or r.get("error") or ""
        print(f"[{idx}] {name} -> ok={ok}{(' | ' + info) if info else ''}")

    # 可选：结束后关闭触摸可视化
    ensure_show_touches(SERIAL, False)
#
# if __name__ == "__main__":
#     main()
