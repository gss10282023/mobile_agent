# test_step3_model.py
from __future__ import annotations
import os, sys, argparse

# 兄弟目录可导入（不改你的三件套）
_CUR = os.path.dirname(__file__)
_PROJ = os.path.abspath(os.path.join(_CUR, ".."))
_UIA2 = os.path.join(_PROJ, "uia2_command_kit")
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from uia2_command_kit.device import DeviceAdapter
from uia2_command_kit.invoker import Invoker
from ui_tars_7b_kit.action_executor import ADBExecutor, ExecutorConfig
from agents.ui_agent import UITarsMobileAgent

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruction", type=str, required=True)

    # 设备
    ap.add_argument("--serial", type=str, default=None)
    ap.add_argument("--implicit-wait", type=float, default=10.0)

    # 执行器
    ap.add_argument("--dry-run", type=int, default=0)
    ap.add_argument("--scroll-frac", type=float, default=0.28)
    ap.add_argument("--swipe-s", type=float, default=0.25)
    ap.add_argument("--drag-s", type=float, default=0.40)
    ap.add_argument("--long-press-s", type=float, default=0.60)
    ap.add_argument("--rotation", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--render-w", type=int, default=0)
    ap.add_argument("--render-h", type=int, default=0)

    # 推理
    ap.add_argument("--history-n", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=20)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=0.9)
    ap.add_argument("--max-tokens", type=int, default=512)

    # OpenRouter（也可走环境变量）
    ap.add_argument("--api-key", type=str, default=None)
    ap.add_argument("--model", type=str, default="bytedance/ui-tars-1.5-7b")
    ap.add_argument("--site-url", type=str, default=os.getenv("OPENROUTER_SITE_URL"))
    ap.add_argument("--site-name", type=str, default=os.getenv("OPENROUTER_SITE_NAME"))
    ap.add_argument("--base-url", type=str, default="https://openrouter.ai/api/v1")

    args = ap.parse_args()

    # 设备与 invoker
    dev = DeviceAdapter(serial=args.serial, implicit_wait=args.implicit_wait)
    inv = Invoker(device=dev, base_settle_ms=200, duration_factor=0.6)

    # render 尺寸默认与设备一致（避免坐标偏差）
    try:
        dw, dh = dev.d.window_size()
    except Exception:
        dw, dh = (1080, 1920)
    render_w = args.render_w or dw
    render_h = args.render_h or dh

    ex_cfg = ExecutorConfig(
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
        valid_rect=(0, 0, 0, 0),
        rotation=args.rotation,
        config=ex_cfg,
    )

    # Agent（内部创建 OpenRouter 客户端）
    agent = UITarsMobileAgent(
        api_key=args.api_key,           # 可不传 → 用 OPENROUTER_API_KEY
        model=args.model,
        base_url=args.base_url,
        site_url=args.site_url,
        site_name=args.site_name,
        executor=executor,
        device=dev,
        language="Chinese",
        history_n=args.history_n,
        temperature=args.temperature,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
        log_fn=print,
    )

    print(f"[Boot] device=({dw}x{dh}), render=({render_w}x{render_h}), dry_run={bool(args.dry_run)}, model={args.model}")
    results = agent.run(args.instruction, max_steps=args.max_steps)

    print("\n=== 执行结果汇总 ===")
    for r in results:
        idx = r.get("index")
        name = r.get("name")
        ok = r.get("ok", True)
        info = r.get("detail") or r.get("error") or ""
        print(f"[{idx}] {name} -> ok={ok}{(' | ' + info) if info else ''}")

if __name__ == "__main__":
    main()
