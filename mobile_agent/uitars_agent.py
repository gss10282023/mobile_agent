from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from ui_tars_7b_kit.action_executor import ADBExecutor
from ui_tars_7b_kit.action_parser import ParsedOutput, parse_mobile_output
from ui_tars_7b_kit.prompts import MOBILE_PROMPT_TEMPLATE

from .model_strategies import ChatModelStrategy, OpenRouterStrategy
from .run_recorder import RunRecorder
from .screenshot_tool import ScreenshotTool, pil_to_base64_png


class UITarsMobileAgent:
    """Orchestrates screenshot capture, model inference, and UI action execution."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = "bytedance/ui-tars-1.5-7b",
        base_url: str = "https://openrouter.ai/api/v1",
        site_url: Optional[str] = None,
        site_name: Optional[str] = None,
        timeout: Optional[float] = None,
        executor: ADBExecutor,
        device,
        language: str = "Chinese",
        history_n: int = 3,
        temperature: float = 0.0,
        top_p: float = 0.9,
        max_tokens: int = 512,
        log_fn=print,
        model_strategy: Optional[ChatModelStrategy] = None,
        run_recorder: Optional[RunRecorder] = None,
    ) -> None:
        self.executor = executor
        self.device = device
        self.log = log_fn
        self.screenshot_tool = ScreenshotTool(device=device, log_fn=log_fn)
        self.run_recorder = run_recorder

        self.language = language
        self.history_n = max(0, int(history_n))
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens

        self.model_strategy = model_strategy or OpenRouterStrategy(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            default_model=model,
        )
        self.model = model

        env_site_url = os.getenv("OPENROUTER_SITE_URL")
        env_site_name = os.getenv("OPENROUTER_SITE_NAME")
        self.extra_headers: Dict[str, str] = {}
        if site_url or env_site_url:
            self.extra_headers["HTTP-Referer"] = site_url or env_site_url
        if site_name or env_site_name:
            self.extra_headers["X-Title"] = site_name or env_site_name

        self.history_imgs: List[str] = []
        self.history_resps: List[str] = []

    def _capture_screen(self) -> Tuple[Image.Image, Tuple[int, int]]:
        return self.screenshot_tool.capture()

    def _build_messages(self, instruction: str, cur_b64: str) -> List[Dict[str, Any]]:
        user_prompt = MOBILE_PROMPT_TEMPLATE.format(language=self.language, instruction=instruction)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": [{"type": "text", "text": "You are a helpful assistant."}]},
            {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
        ]
        hist_len = min(self.history_n, len(self.history_imgs), len(self.history_resps))
        for i in range(-hist_len, 0):
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{self.history_imgs[i]}"},
                        }
                    ],
                }
            )
            messages.append({"role": "assistant", "content": self.history_resps[i]})
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{cur_b64}"}},
                ],
            }
        )
        return messages

    def step(self, instruction: str) -> Tuple[str, ParsedOutput, List[Dict[str, Any]]]:
        try:
            img, _ = self._capture_screen()
        except Exception as exc:
            raise RuntimeError("Failed to capture screenshot. Check adb/device connection.") from exc

        b64 = pil_to_base64_png(img)

        messages = self._build_messages(instruction, b64)

        try:
            text = self.model_strategy.generate(
                messages,
                model=self.model,
                temperature=self.temperature,
                top_p=self.top_p,
                max_tokens=self.max_tokens,
                extra_headers=(self.extra_headers or None),
            )
        except Exception as exc:
            if self.run_recorder:
                self.run_recorder.record_step(
                    instruction=instruction,
                    image=img,
                    model_output=None,
                    parsed=None,
                    results=None,
                    error=f"model_error: {exc}",
                )
            raise RuntimeError("Model request failed. Check API key, network, or timeout.") from exc
        if self.log:
            self.log("\n[MODEL OUTPUT]\n" + text)

        try:
            parsed = parse_mobile_output(text)
        except Exception as exc:
            if self.run_recorder:
                self.run_recorder.record_step(
                    instruction=instruction,
                    image=img,
                    model_output=text,
                    parsed=None,
                    results=None,
                    error=f"parse_error: {exc}",
                )
            raise RuntimeError("Model output parsing failed. Check Action format.") from exc

        try:
            results = self.executor.execute(parsed.actions[0])
        except Exception as exc:
            if self.run_recorder:
                self.run_recorder.record_step(
                    instruction=instruction,
                    image=img,
                    model_output=text,
                    parsed=parsed,
                    results=None,
                    error=f"execute_error: {exc}",
                )
            raise RuntimeError("Action execution failed. Check device connection and state.") from exc

        if self.run_recorder:
            self.run_recorder.record_step(
                instruction=instruction,
                image=img,
                model_output=text,
                parsed=parsed,
                results=results if isinstance(results, list) else [results],
                error=None,
            )

        self.history_imgs.append(b64)
        self.history_resps.append(text)
        if len(self.history_imgs) > self.history_n:
            self.history_imgs = self.history_imgs[-self.history_n :]
            self.history_resps = self.history_resps[-self.history_n :]

        return text, parsed, results

    def run(self, instruction: str, max_steps: int = 20) -> List[Dict[str, Any]]:
        all_results: List[Dict[str, Any]] = []
        for step_idx in range(1, max_steps + 1):
            if self.log:
                self.log(f"\n===== UI-TARS STEP {step_idx} / {max_steps} =====")
            _, parsed, results = self.step(instruction)
            all_results.extend(results if isinstance(results, list) else [results])
            if parsed.actions and parsed.actions[0].type == "finished":
                if self.log:
                    self.log("[DONE] finished() received. Exit loop.")
                break
        return all_results
