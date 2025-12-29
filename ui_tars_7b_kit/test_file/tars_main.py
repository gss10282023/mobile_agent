#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立 main 启动脚本：调用 tars_client.TarsClient 的 next_action()
- 允许多张本地图片作为“上传”（路径传入，脚本自动转 data URL）
- 使用内置 GUI Agent 提示词模版（可用 --template-file 覆盖）
- 打印模型输出、原始 JSON、usage 粗估成本，及 /generation 精确费用（若可用）

用法示例：
    export OPENROUTER_API_KEY=你的Key
    python tars_main.py -i "打开设置，把 Wi-Fi 打开" -s shots/s1.png shots/s2.jpg

把本文件与 tars_client.py 放在同一目录。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from ui_tars_7b_kit.test_file.tars_client import TarsClient, DEFAULT_MODEL, GUI_AGENT_SYSTEM_PROMPT


def _resolve_paths(paths: Optional[List[str]]) -> Optional[List[Path]]:
    if not paths:
        return None
    out: List[Path] = []
    for p in paths:
        pp = Path(p).expanduser().resolve()
        if not pp.exists():
            print(f"[WARN] 路径不存在，已忽略：{pp}", file=sys.stderr)
            continue
        if not pp.is_file():
            print(f"[WARN] 不是文件，已忽略：{pp}", file=sys.stderr)
            continue
        out.append(pp)
    return out or None


def _title(s: str) -> None:
    print("\n" + "=" * 8 + f" {s} " + "=" * 8)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "UI-TARS 模型 next_action() 测试：\n"
            "- 使用 GUI Agent 模版组装 system/user 消息\n"
            "- 支持多张截图(本地图片自动 data URL)\n"
            "- 打印模型输出、usage 成本估算与 /generation 精确费用"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("-i", "--instruction", required=True, help="任务指令（放入 user 消息的 Instruction 段）")
    parser.add_argument("-H", "--history", default=None, help="动作历史文本，可选")
    parser.add_argument("-F", "--history-file", default=None, help="从文件读取动作历史，可选")
    parser.add_argument("-s", "--screenshots", nargs="*", default=None, help="截图路径，支持多张，例如 -s a.png b.jpg")
    parser.add_argument("-l", "--language", default="中文", help="在系统模板中替换 {language}")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="OpenRouter 模型名")
    parser.add_argument("--http-referer", default=os.getenv("HTTP_REFERER"), help="HTTP-Referer 头，可选")
    parser.add_argument("--x-title", default=None, help="X-Title 头，可选")
    parser.add_argument("--timeout", type=int, default=600, help="HTTP 超时秒数")
    parser.add_argument("--json-out", default=None, help="把完整 JSON 响应保存到此文件路径")
    parser.add_argument("--template-file", default=None, help="使用自定义系统提示词模版文件(替代内置模版)")

    args = parser.parse_args()

    # 处理动作历史的合并
    action_history = args.history
    if args.history_file:
        try:
            file_text = Path(args.history_file).read_text(encoding="utf-8")
            action_history = (action_history + "\n" if action_history else "") + file_text
        except Exception as e:
            print(f"[WARN] 读取动作历史文件失败：{e}", file=sys.stderr)

    # 处理截图
    screenshots = _resolve_paths(args.screenshots)

    # 系统提示词模版（可覆盖）
    system_prompt_template = GUI_AGENT_SYSTEM_PROMPT
    if args.template_file:
        try:
            system_prompt_template = Path(args.template_file).read_text(encoding="utf-8")
        except Exception as e:
            print(f"[WARN] 读取 --template-file 失败，改用内置模版：{e}", file=sys.stderr)

    # 实例化客户端（API Key 从环境变量读取）
    try:
        client = TarsClient(
            http_referer=args.http_referer,
            x_title=args.x_title,
            timeout=args.timeout,
        )
    except Exception as e:
        print(f"[FATAL] 初始化失败：{e}\n请先设置环境变量 OPENROUTER_API_KEY=你的Key", file=sys.stderr)
        return 1

    # 调用 next_action（按模板）
    try:
        resp = client.next_action(
            instruction=args.instruction,
            action_history=action_history,
            screenshots=screenshots,
            language=args.language,
            model=args.model,
            system_prompt_template=system_prompt_template,
        )
    except Exception as e:
        print(f"[FATAL] 请求失败：{e}", file=sys.stderr)
        return 2

    # 输出结果
    _title("Model Output (choices[0].message.content)")
    try:
        content = resp.get("choices", [{}])[0].get("message", {}).get("content")
        print(content if content else "<无内容>")
    except Exception:
        print("<解析失败，原始响应见下>")

    _title("Raw JSON")
    try:
        print(json.dumps(resp, ensure_ascii=False, indent=2))
    except Exception:
        print(resp)

    usage = resp.get("usage")
    if usage:
        _title("Usage & Rough Cost (估算)")
        try:
            print(json.dumps(usage, indent=2))
        except Exception:
            print(usage)
        rough = TarsClient.rough_cost(usage)
        if rough is not None:
            print(f"Rough cost (USD, est.): ${rough:.6f}")

    gen_id = resp.get("id")
    if gen_id:
        detail = client.generation_detail(gen_id)
        if detail:
            _title("/generation Detail (精确费用)")
            try:
                print(json.dumps(detail, ensure_ascii=False, indent=2))
            except Exception:
                print(detail)
            tc = detail.get("total_cost")
            if tc is not None:
                print(f"Exact cost: ${tc}")

    if args.json_out:
        try:
            Path(args.json_out).write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n已保存完整响应到: {args.json_out}")
        except Exception as e:
            print(f"[WARN] 保存 json 失败：{e}", file=sys.stderr)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
