# test_step2_adb.py
from __future__ import annotations
import os, sys, argparse

from typing import List, Tuple

# ========= 让兄弟目录 uia2_command_kit 可被 import（不改你的三件套）=========
_CUR = os.path.dirname(__file__)
_PROJ = os.path.abspath(os.path.join(_CUR, ".."))               # 项目根（Anti-fraud_agent）
_UIA2 = os.path.join(_PROJ, "uia2_command_kit")
if _UIA2 not in sys.path:
    sys.path.insert(0, _UIA2)

# ========= 我们自己的模块 =========
from action_parser import parse_mobile_output
from core_agent import MobileUITARSAgent
from action_executor import ADBExecutor, ExecutorConfig

# ========= 你已有的三件套（不改）=========
from device import DeviceAdapter
from invoker import Invoker

# =====================
# 测试开关（逐项控制）
# =====================
ENABLE_OPEN_APP   = True
ENABLE_CLICK      = False
ENABLE_LONG_PRESS = False
ENABLE_DRAG       = False
ENABLE_SCROLL     = False  # 注意：UI-TARS scroll 会被转成 SwipeCommand 执行
ENABLE_TYPE       = False
ENABLE_PRESS_HOME = False
ENABLE_PRESS_BACK = False
ENABLE_FINISHED   = True

# =====================
# 精准参数（替换成你的设备坐标）
# =====================
APP_NAME = "设置"  # 可写中文名/别名/包名

CLICK_X = 540.0; CLICK_Y = 1600.0

LONG_X = 540.0; LONG_Y = 1600.0

DRAG_SX = 540.0; DRAG_SY = 1600.0
DRAG_EX = 540.0; DRAG_EY = 400.0

SCROLL_PX = 540.0; SCROLL_PY = 1600.0
SCROLL_DIR = "down"   # up/down/left/right

TYPE_TEXT = "hello"  # 末尾 \n 会在 device.py 自动回车（ENTER）

# =====================
# 将单个动作生成为 UI-TARS 文本（Thought/Action）
# =====================
def act_click(x: float, y: float) -> str:
    return f"Thought: 点击测试\nAction: click(point='<point>{x} {y}</point>')"

def act_long_press(x: float, y: float) -> str:
    return f"Thought: 长按测试\nAction: long_press(point='<point>{x} {y}</point>')"

def act_drag(sx: float, sy: float, ex: float, ey: float) -> str:
    return ("Thought: 拖拽测试\n"
            f"Action: drag(start_point='<point>{sx} {sy}</point>', end_point='<point>{ex} {ey}</point>')")

def act_scroll(x: float, y: float, direction: str) -> str:
    return ("Thought: 滚动测试\n"
            f"Action: scroll(point='<point>{x} {y}</point>', direction='{direction}')")

def act_type(text: str) -> str:
    # 注意转义：这里直接放进单引号里，常见 \n 会被解析器还原
    safe = text.replace("\\", "\\\\").replace("'", "\\'")
    return f"Thought: 输入测试\nAction: type(content='{safe}')"

def act_open_app(name: str) -> str:
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    return f"Thought: 打开应用测试\nAction: open_app(app_name='{safe}')"

def act_press_home() -> str:
    return "Thought: 回到桌面\nAction: press_home()"

def act_press_back() -> str:
    return "Thought: 返回上一页\nAction: press_back()"

def act_finished(msg: str) -> str:
    safe = msg.replace("\\", "\\\\").replace("'", "\\'")
    return f"Thought: 流程完成\nAction: finished(content='{safe}')"


def build_enabled_actions() -> List[str]:
    cases: List[str] = []
    if ENABLE_OPEN_APP:
        cases.append(act_open_app(APP_NAME))
    if ENABLE_CLICK:
        cases.append(act_click(CLICK_X, CLICK_Y))
    if ENABLE_LONG_PRESS:
        cases.append(act_long_press(LONG_X, LONG_Y))
    if ENABLE_DRAG:
        cases.append(act_drag(DRAG_SX, DRAG_SY, DRAG_EX, DRAG_EY))
    if ENABLE_SCROLL:
        cases.append(act_scroll(SCROLL_PX, SCROLL_PY, SCROLL_DIR))
    if ENABLE_TYPE:
        cases.append(act_type(TYPE_TEXT))
    if ENABLE_PRESS_BACK:
        cases.append(act_press_back())
    if ENABLE_PRESS_HOME:
        cases.append(act_press_home())
    if ENABLE_FINISHED:
        cases.append(act_finished("测试完成"))
    return cases

def main():
    ap = argparse.ArgumentParser()
    # 执行模式
    ap.add_argument("--dry-run", type=int, default=1, help="1=只打印不执行；0=真机执行")
    ap.add_argument("--serial", type=str, default=None, help="adb 序列号；默认自动连接")
    ap.add_argument("--implicit-wait", type=float, default=10.0, help="uiautomator2 隐式等待秒数")

    # 渲染图 → 设备 映射
    ap.add_argument("--render-w", type=int, default=0, help="模型看到的图宽（0=自动取设备宽）")
    ap.add_argument("--render-h", type=int, default=0, help="模型看到的图高（0=自动取设备高）")
    ap.add_argument("--rotation", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--scroll-frac", type=float, default=0.28, help="scroll 的滑动比例（相对渲染图高/宽）")

    # 默认时长（秒）
    ap.add_argument("--long-press-s", type=float, default=0.60)
    ap.add_argument("--drag-s", type=float, default=0.40)
    ap.add_argument("--swipe-s", type=float, default=0.25)

    args = ap.parse_args()

    dev = DeviceAdapter(serial=args.serial, implicit_wait=args.implicit_wait)
    inv = Invoker(device=dev, base_settle_ms=200, duration_factor=0.6)

    # 自动推断渲染图尺寸（若未指定）
    try:
        dw, dh = dev.d.window_size()  # type: ignore[attr-defined]
    except Exception:
        dw, dh = (1080, 1920)
    render_w = args.render_w or dw
    render_h = args.render_h or dh

    # 构建执行器
    cfg = ExecutorConfig(
        long_press_s=args.long_press_s,
        drag_s=args.drag_s,
        swipe_s=args.swipe_s,
        scroll_frac=args.scroll_frac,
        dry_run=bool(args.dry_run),
    )
    executor = ADBExecutor(
        device=dev,
        invoker=inv,
        render_size=(render_w, render_h),
        valid_rect=(0, 0, 0, 0),       # 若你的渲染图有黑边/裁剪，在此填 (vx,vy,vw,vh)
        rotation=args.rotation,
        config=cfg,
    )
    agent = MobileUITARSAgent(executor=executor, language="Chinese")

    # 逐条（一步步）执行你打开的测试
    cases = build_enabled_actions()
    if not cases:
        print("未启用任何测试：请在文件顶部把对应 ENABLE_* 设为 True。")
        return

    for i, text in enumerate(cases, 1):
        print("\n" + "=" * 20 + f" STEP {i} " + "=" * 20)
        parsed = agent.step_with_model_output(text)
        print("[THOUGHT]", parsed.thought)
        print("[RAW_ACTION]", parsed.raw_action)

if __name__ == "__main__":
    main()
