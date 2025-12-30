from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Union

from uia2_command_kit.device import DeviceAdapter
from uia2_command_kit.invoker import Invoker
from ui_tars_7b_kit.action_executor import ADBExecutor, ExecutorConfig

from .run_recorder import RunRecorder
from .screenshot_tool import ScreenshotTool
from .uitars_agent import UITarsMobileAgent


LogFn = Callable[[str], None]


@dataclass(frozen=True)
class MobileAgent:
    device: DeviceAdapter
    invoker: Invoker
    executor: ADBExecutor
    ui: UITarsMobileAgent

    def step(self, instruction: str):
        return self.ui.step(instruction)

    def run(self, instruction: str, *, max_steps: int = 20):
        return self.ui.run(instruction, max_steps=max_steps)


def build_mobile_agent(
    *,
    serial: Optional[str] = None,
    dry_run: bool = True,
    rotation: int = 0,
    model: str = "bytedance/ui-tars-1.5-7b",
    api_key: Optional[str] = None,
    base_url: str = "https://openrouter.ai/api/v1",
    site_url: Optional[str] = None,
    site_name: Optional[str] = None,
    timeout: Optional[float] = None,
    language: str = "Chinese",
    history_n: int = 3,
    temperature: float = 0.0,
    top_p: float = 0.9,
    max_tokens: int = 512,
    wait_s: float = 1.0,
    scroll_frac: float = 0.28,
    run_dir: Optional[Union[str, Path]] = None,
    log_fn: LogFn = print,
) -> MobileAgent:
    try:
        device = DeviceAdapter(serial=serial)
    except Exception as exc:
        raise RuntimeError(
            "Failed to connect to device. Ensure adb is installed, the device is online, "
            "and USB debugging is enabled."
        ) from exc

    screenshot_tool = ScreenshotTool(device=device, log_fn=log_fn)
    try:
        _, render_size = screenshot_tool.capture()
    except Exception as exc:
        raise RuntimeError(
            "Failed to capture screenshot from device. Check adb connectivity and device authorization."
        ) from exc

    invoker = Invoker(device=device, log_fn=log_fn)
    executor_config = ExecutorConfig(
        log_fn=log_fn,
        dry_run=dry_run,
        wait_s=wait_s,
        scroll_frac=scroll_frac,
    )
    executor = ADBExecutor(
        device=device,
        invoker=invoker,
        render_size=render_size,
        rotation=rotation,
        config=executor_config,
    )

    run_recorder = None
    if run_dir:
        run_recorder = RunRecorder(
            Path(run_dir),
            metadata={
                "model": model,
                "serial": serial,
                "dry_run": dry_run,
                "rotation": rotation,
                "language": language,
                "history_n": history_n,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
                "wait_s": wait_s,
                "scroll_frac": scroll_frac,
            },
            log_fn=log_fn,
        )

    ui = UITarsMobileAgent(
        api_key=api_key,
        model=model,
        base_url=base_url,
        site_url=site_url,
        site_name=site_name,
        timeout=timeout,
        executor=executor,
        device=device,
        language=language,
        history_n=history_n,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        log_fn=log_fn,
        run_recorder=run_recorder,
    )
    return MobileAgent(device=device, invoker=invoker, executor=executor, ui=ui)
