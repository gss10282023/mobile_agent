# -*- coding: utf-8 -*-
# brain_tools.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Callable
from pathlib import Path
import json

from .image_io import (
    save_b64_png_to_file,
    resize_b64_png,
)


class ImageLogger:
    """轻量图像记录器：保存所有步骤帧；在账户会话期间，复制一份到账户文件夹。"""
    def __init__(
        self,
        frames_dir: Path,
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.frames_dir = frames_dir
        self._log = log_fn or (lambda s: None)

        # 目录
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_dir = self.frames_dir.parent / "accounts"
        self.accounts_dir.mkdir(parents=True, exist_ok=True)

        # 全量步骤计数
        self._ui_frame_idx = 0

        # 账户会话状态
        self._session_dir: Optional[Path] = None
        self._session_idx = 0
        self._account_counter = 0

    # ---- 所有步骤帧 ----
    def save_ui_frame(self, b64_png: str) -> Optional[Path]:
        """保存 step_XXX.png；若处于账户会话，则复制一份为 frame_YYY.png 到该账户文件夹。"""
        self._ui_frame_idx += 1
        path = self.frames_dir / f"step_{self._ui_frame_idx:03d}.png"
        ok = save_b64_png_to_file(b64_png, path)
        if ok:
            self._log(f"[IMG] Saved UI-TARS frame: {path}")
            if self._session_dir is not None:
                self._session_idx += 1
                save_b64_png_to_file(
                    b64_png, self._session_dir / f"frame_{self._session_idx:03d}.png"
                )
            return path
        self._log("[WARN] Failed to save UI-TARS frame")
        return None

    # ---- 账户会话：开始/结束/直接落一帧（进入瞬间用）----
    def start_account_session(self, handle: str, display_name: Optional[str] = None) -> None:
        if self._session_dir is not None:
            self.end_account_session()
        self._account_counter += 1
        folder = f"{self._account_counter:03d}__{(handle or 'unknown')}"
        self._session_dir = (self.accounts_dir / folder)
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._session_idx = 0

    def end_account_session(self) -> None:
        self._session_dir = None
        self._session_idx = 0

    def save_b64_to_current_account(self, b64_png: str) -> None:
        if self._session_dir is None:
            return
        self._session_idx += 1
        save_b64_png_to_file(b64_png, self._session_dir / f"frame_{self._session_idx:03d}.png")


class BrainTools:
    """
    门面：向 Gpt5Client 暴露工具（ui_step / mark_enter_account / mark_leave_account / report_account / log）。
    """
    def __init__(
        self,
        ui_agent: Any,
        image_logger: ImageLogger,
        ui_global_instruction: str,
        brain_vision: bool,
        vision_width: int,
        print_thoughts: bool,
        print_instruction: bool,
        print_results: bool,
        debug: bool = False,
        log_fn: Optional[Callable[[str], None]] = None,
        report_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.ui_agent = ui_agent
        self.image_logger = image_logger
        self.ui_global_instruction = ui_global_instruction
        self.brain_vision = bool(brain_vision)
        self.vision_width = int(vision_width)
        self.print_thoughts = bool(print_thoughts)
        self.print_instruction = bool(print_instruction)
        self.print_results = bool(print_results)
        self.debug = bool(debug)
        self._log = log_fn or (lambda s: None)
        self._brain = None  # set via set_brain()
        self._report_sink = report_sink or self._default_report_sink

        self._current_account: Optional[str] = None
        self._current_display_name: Optional[str] = None

    # --------- 与 Gpt5Client 的连接点 ---------
    def set_brain(self, brain_client: Any) -> None:
        self._brain = brain_client

    @staticmethod
    def schema() -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "ui_step",
                    "description": "Execute one GUI step via UI agent on the phone; returns Thought/Action and execution results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subtask": {
                                "type": "string",
                                "description": "如：'打开Twitter' / '点搜索框输入关键词' / '进入账户Tab' / '打开第一个账号' / '下滑浏览简介/帖子'",
                            },
                        },
                        "required": ["subtask"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mark_enter_account",
                    "description": "在进入某个账号主页时做标记，并在终端打印：进入账户@xxx（可含显示名）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "handle": {
                                "type": "string",
                                "description": "Twitter 账户 handle，如 '@someone'；若暂未知可传 'unknown'",
                            },
                            "display_name": {
                                "type": "string",
                                "description": "可选，显示名称（若可见）",
                            },
                        },
                        "required": ["handle"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mark_leave_account",
                    "description": "在离开当前账号主页时做标记，并在终端打印：离开账户@xxx（可含显示名）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "handle": {
                                "type": "string",
                                "description": "Twitter 账户 handle，如 '@someone'；若暂未知可传 'unknown'",
                            },
                            "display_name": {
                                "type": "string",
                                "description": "可选，显示名称（若可见）",
                            },
                        },
                        "required": ["handle"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "report_account",
                    "description": "Emit a structured suspicion report for the current account (printed immediately).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "display_name": {"type": "string"},
                            "handle": {"type": "string", "description": "e.g., @something (if visible)"},
                            "profile_url": {"type": "string", "description": "Optional; twitter.com/<handle> if known"},
                            "suspicious": {"type": "boolean"},
                            "score": {"type": "number", "minimum": 0, "maximum": 1, "description": "confidence 0-1"},
                            "reasons": {"type": "array", "items": {"type": "string"}},
                            "evidence": {"type": "array", "items": {"type": "string"}, "description": "short on-screen snippets observed"},
                        },
                        "required": ["display_name", "suspicious", "reasons"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "log",
                    "description": "Print a short status line to the console (for progress/debug).",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            },
        ]

    def registry(self) -> Dict[str, Callable[..., Dict[str, Any]]]:
        return {
            "ui_step": self.ui_step,
            "mark_enter_account": self.mark_enter_account,
            "mark_leave_account": self.mark_leave_account,
            "report_account": self.report_account,
            "log": self.log,
        }

    # --------- 工具实现 ---------
    def ui_step(self, subtask: str) -> Dict[str, Any]:
        """执行一步 UI 操作，并做图像记录；若账户会话开启，自动归档到账户文件夹。"""
        instruction = f"{self.ui_global_instruction}\n\n子任务：{subtask}"

        if self.print_thoughts:
            banner = "-" * 72
            print(banner)
            print(f"[UI INSTRUCTION] 子任务: {subtask}")
            if self.print_instruction:
                print("[UI FULL PROMPT]")
                print(instruction)

        text, parsed, results = self.ui_agent.step(instruction=instruction)

        if getattr(self.ui_agent, "history_imgs", None):
            ui_b64 = self.ui_agent.history_imgs[-1]
            self.image_logger.save_ui_frame(ui_b64)

        action_type = parsed.actions[0].type if getattr(parsed, "actions", None) else None

        if self.print_thoughts:
            print("[UI THOUGHT/ACTION]")
            try:
                print((text or "").strip())
            except Exception:
                print(str(text))
            if action_type:
                print(f"[EXECUTED ACTION] {action_type}")
            if self.print_results:
                try:
                    print("[EXECUTION RESULTS]")
                    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
                except Exception:
                    print(f"[EXECUTION RESULTS] (unserializable) {type(results)}")
            print()

        # brain-vision：只喂图，不维护 sprite
        if self.brain_vision and getattr(self.ui_agent, "history_imgs", None):
            try:
                if self._brain is None:
                    self._log("[WARN] brain-vision enabled but brain client not set")
                else:
                    b64 = self.ui_agent.history_imgs[-1]
                    b64_small = resize_b64_png(b64, self.vision_width)
                    self._brain.attach_image(f"data:image/png;base64,{b64_small}")
                    self._brain.add_user_message(
                        "SCREENSHOT_AFTER_STEP\n"
                        f"subtask: {subtask}\n"
                        "请从截图中提取并校对字段：display_name、handle、followers、following、"
                        "verified、bio、pinned_excerpt、external_url_present、top_visible_tab；"
                        "若无法确认，标注 unknown。然后基于图像+文字共同证据决定下一步的 ui_step 或报告。"
                        "\n\n（以下为 UI 代理的文字观察）\n" + (text or "")
                    )
            except Exception as e:
                self._log(f"[WARN] brain-vision failed: {e}")

        return {"ok": True, "thought_action": text, "action": action_type, "results": results}

    @staticmethod
    def _norm_handle(handle: str) -> str:
        h = (handle or "").strip()
        if not h or h.lower() == "unknown":
            return "unknown"
        return h if h.startswith("@") else f"@{h}"

    def mark_enter_account(self, handle: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """进入账户：打印标记 + 开启账户会话。"""
        h = self._norm_handle(handle)
        name = (display_name or "").strip()
        msg = f"进入账户{h}" + (f"（显示名：{name}）" if name else "")
        print(msg)
        self._log(msg)
        if h != "unknown":
            self._current_account = h
        if name:
            self._current_display_name = name

        # 只开启会话，不再把“上一帧”塞进账户文件夹
        try:
            self.image_logger.start_account_session(h, name)
        except Exception:
            pass

        return {"ok": True, "handle": h, "display_name": name}

    def mark_leave_account(self, handle: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """离开账户：打印标记 + 结束账户会话。"""
        h_in = self._norm_handle(handle)
        h = self._current_account if (h_in == "unknown" and self._current_account) else h_in
        name_in = (display_name or "").strip()
        name = self._current_display_name if (not name_in and self._current_display_name) else name_in
        msg = f"离开账户{h or 'unknown'}" + (f"（显示名：{name}）" if name else "")
        print(msg)
        self._log(msg)

        try:
            self.image_logger.end_account_session()
        except Exception:
            pass

        if h and self._current_account and h == self._current_account:
            self._current_account = None
            self._current_display_name = None
        return {"ok": True, "handle": h or "unknown", "display_name": name}

    def report_account(
        self,
        display_name: str,
        handle: Optional[str] = None,
        profile_url: Optional[str] = None,
        suspicious: bool = False,
        score: float = 0.5,
        reasons: Optional[List[str]] = None,
        evidence: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "display_name": display_name,
            "handle": handle or "",
            "profile_url": profile_url or "",
            "suspicious": bool(suspicious),
            "score": round(float(score), 3),
            "reasons": reasons or [],
            "evidence": evidence or [],
        }
        self._report_sink(payload)
        return {"ok": True}

    def log(self, text: str) -> Dict[str, Any]:
        line = f"[BRAIN] {text}"
        print(line)
        self._log(line)
        return {"ok": True}

    # --------- 其他 ---------
    def flush(self) -> None:
        """保持接口兼容：不做任何事情。"""
        return

    @staticmethod
    def _default_report_sink(payload: Dict[str, Any]) -> None:
        banner = "=" * 72
        print(banner)
        print("ACCOUNT REPORT")
        print(banner)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print()
