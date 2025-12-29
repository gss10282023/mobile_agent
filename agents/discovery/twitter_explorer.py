#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitter(X) ADB Explorer core (library). The CLI test harness has been moved to
`agents.discovery.cli_twitter_explorer`.
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, List, Optional, Tuple, Callable

# Ensure project root on sys.path when running module form
import sys
from pathlib import Path

# --- Project imports (must exist in your repo) ---
from ui_tars_7b_kit.action_executor import ADBExecutor, ExecutorConfig
from agents.ui_agent import UITarsMobileAgent
# Try package-local import first; fallback if you placed the file elsewhere
try:
    from agents.gpt5.gpt5_client_library import Gpt5Client
except Exception:  # pragma: no cover
    from gpt5_client_library import Gpt5Client  # fallback when running ad-hoc

# The phone control stack (you already have these in your project)
try:
    from uia2_command_kit.device import DeviceAdapter  # type: ignore
    from uia2_command_kit.invoker import Invoker        # type: ignore
except Exception:  # pragma: no cover
    from device import DeviceAdapter  # type: ignore
    from invoker import Invoker        # type: ignore

# Step B prompts
from .prompts_min import (
    UI_GLOBAL_INSTRUCTION_TEMPLATE,
    build_brain_system_prompt,
    build_brain_user_kickoff,
)

# Step C facade
from .brain_tools import BrainTools, ImageLogger


# --------------------------------------------------------------------------------------
# Helpers to wire up the ADB/UI layer
# --------------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

def _get_device_resolution(dev: DeviceAdapter) -> Tuple[int, int]:
    """Fetch device (w,h) with multiple fallbacks."""
    try:
        w, h = dev.d.window_size()  # uiautomator2 style
        return int(w), int(h)
    except Exception:
        try:
            info = dev.d.info
            return int(info.get("displayWidth", 1080)), int(info.get("displayHeight", 1920))
        except Exception:
            return (1080, 1920)


def build_adb_executor(
    device: DeviceAdapter,
    invoker: Invoker,
    rotation: int = 0,
    dry_run: bool = False,
    log_fn: Optional[Callable[[str], None]] = None,
) -> ADBExecutor:
    dw, dh = _get_device_resolution(device)
    cfg = ExecutorConfig(
        long_press_s=0.6,
        drag_s=0.40,
        swipe_s=0.3,
        scroll_frac=0.3,
        wait_s=1.0,
        log_fn=log_fn or (lambda s: None),
        dry_run=dry_run,
    )
    return ADBExecutor(
        device=device,
        invoker=invoker,
        render_size=(dw, dh),
        valid_rect=(0, 0, 0, 0),
        rotation=rotation,
        config=cfg,
    )


class TwitterExplorer:
    """Library class; orchestrates device, agents, and BrainTools."""
    def __init__(
        self,
        query: str,
        max_accounts: int = 5,
        brain_model: str = os.environ.get("OR_MODEL", "openai/gpt-5-mini"),
        ui_model: str = "bytedance/ui-tars-1.5-7b",
        dry_run: bool = True,
        debug: bool = False,
        print_thoughts: bool = False,
        print_instruction: bool = False,
        print_results: bool = False,
        # --- Brain-vision + logging controls ---
        brain_vision: bool = True,
        vision_width: int = 768,
        out_dir: Optional[str] = None,
    ) -> None:
        self.query = query
        self.max_accounts = max_accounts
        self.debug = debug
        # Printing controls
        self.print_thoughts = bool(print_thoughts or debug)
        self.print_instruction = bool(print_instruction)
        self.print_results = bool(print_results)
        self.brain_vision = bool(brain_vision)
        self.vision_width = int(vision_width)

        # Per-run output directories / files
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.run_dir = Path(out_dir) if out_dir else Path(f"runs/twitter_explorer_{ts}")
        self.ui_frames_dir = self.run_dir / "ui_tars_frames"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.ui_frames_dir.mkdir(parents=True, exist_ok=True)

        # Device + Invoker
        self.device = DeviceAdapter()
        self.invoker = Invoker(self.device)
        self.executor = build_adb_executor(
            self.device,
            self.invoker,
            rotation=0,
            dry_run=dry_run,
            log_fn=self._log_if,
        )

        # UI Agent (low-level GUI executor)
        self.ui_agent = UITarsMobileAgent(
            executor=self.executor,
            device=self.device,
            model=ui_model,
            language="Chinese",
            history_n=3,
            temperature=0.0,
            top_p=0.9,
            max_tokens=512,
            log_fn=self._log_if,
        )

        # 全局 UI 指令模板
        self.ui_global_instruction = UI_GLOBAL_INSTRUCTION_TEMPLATE.format(query=self.query)

        # BrainTools + ImageLogger（极简）
        self.image_logger = ImageLogger(
            frames_dir=self.ui_frames_dir,
            log_fn=(self._log_if if self.debug else (lambda s: None)),
        )
        self.brain_tools = BrainTools(
            ui_agent=self.ui_agent,
            image_logger=self.image_logger,
            ui_global_instruction=self.ui_global_instruction,
            brain_vision=self.brain_vision,
            vision_width=self.vision_width,
            print_thoughts=self.print_thoughts,
            print_instruction=self.print_instruction,
            print_results=self.print_results,
            debug=self.debug,
            log_fn=self._log_if,
        )

        # Decision Agent (high-level planner/analyst) with BrainTools
        self.brain = Gpt5Client(
            system_prompt=build_brain_system_prompt(self.query, self.max_accounts),
            model=brain_model,
            enable_builtin_tools=False,
            extra_tools_schema=BrainTools.schema(),
            extra_tool_registry=self.brain_tools.registry(),
        )
        self.brain_tools.set_brain(self.brain)  # 允许 BrainTools 喂图/加消息

        # Seed the conversation
        self.brain.add_user_message(build_brain_user_kickoff())

        print(f"[INIT] Output dir: {self.run_dir}")
        print(f"[INIT] UI-TARS frames dir: {self.ui_frames_dir}")

    # -------------------- Logging helper --------------------
    def _log_if(self, s: str) -> None:
        if self.debug:
            logging.info(s)

    # -------------------- Public API --------------------
    def run(self) -> None:
        """Run the tool-calling loop; results are persisted to run_dir."""
        resp = self.brain.run_tools_loop(max_hops=64)

        # After finishing, print a final line if the model produced text
        try:
            final_msg = resp["choices"][0]["message"].get("content")
            if final_msg:
                print("\n[SUMMARY]\n" + final_msg.strip() + "\n")
        except Exception:
            pass

        # 保持兼容：BrainTools.flush() 现在为空操作
        try:
            self.brain_tools.flush()
        except Exception:
            pass

        # Optional: persist conversation for post-mortem
        try:
            self.brain.save_markdown(str(self.run_dir / "session.md"))
            print(f"[SAVED] Conversation markdown → {self.run_dir / 'session.md'}")
            print(f"[SAVED] UI-TARS frames → {self.ui_frames_dir}")
        except Exception:
            pass
