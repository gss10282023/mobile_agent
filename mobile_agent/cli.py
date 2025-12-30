from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple


def _env_default(key: str) -> Optional[str]:
    value = os.getenv(key)
    return value if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mobile-agent",
        description="Control an Android phone via UI-TARS 7B (OpenRouter).",
    )
    parser.add_argument("--serial", default=None, help="Android device serial (adb/uiautomator2).")
    parser.add_argument(
        "-i",
        "--instruction",
        default=None,
        help="Task instruction (if omitted, enter interactive mode).",
    )
    parser.add_argument("--dry-run", type=int, default=1, help="1=print actions only, 0=execute on device.")
    parser.add_argument("--rotation", type=int, default=0, help="Render-to-device rotation (0/90/180/270).")
    parser.add_argument("--max-steps", type=int, default=20, help="Max UI steps per instruction.")
    parser.add_argument("--language", default="Chinese", help="Thought language (e.g., Chinese/English).")
    parser.add_argument("--history-n", type=int, default=3, help="How many previous steps to include as context.")
    parser.add_argument("--model", default="bytedance/ui-tars-1.5-7b", help="UI-TARS model name.")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1", help="OpenAI-compatible base URL.")
    parser.add_argument("--api-key", default=_env_default("OPENROUTER_API_KEY"), help="OpenRouter API key.")
    parser.add_argument("--site-url", default=_env_default("OPENROUTER_SITE_URL"), help="Optional: HTTP-Referer.")
    parser.add_argument("--site-name", default=_env_default("OPENROUTER_SITE_NAME"), help="Optional: X-Title.")
    parser.add_argument("--timeout", type=float, default=None, help="Request timeout (seconds).")
    parser.add_argument("--temperature", type=float, default=0.0, help="Model temperature.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Model top_p.")
    parser.add_argument("--max-tokens", type=int, default=512, help="Model max_tokens.")
    parser.add_argument("--wait-s", type=float, default=1.0, help="Default wait() seconds.")
    parser.add_argument("--scroll-frac", type=float, default=0.28, help="Scroll magnitude as fraction of screen.")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity.",
    )
    parser.add_argument(
        "--save-runs",
        action="store_true",
        help="Save screenshots and model outputs to runs/<timestamp>/.",
    )
    return parser


def _interactive_loop(agent, *, max_steps: int, logger: logging.Logger) -> int:
    print("Interactive mode. Type your instruction and press Enter. Type 'exit' to quit.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in {"exit", "quit", ":q"}:
            return 0
        try:
            agent.run(line, max_steps=max_steps)
        except Exception as exc:
            logger.error(str(exc))


def _build_logger(level: str) -> Tuple[logging.Logger, Callable[[str], None]]:
    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    logger = logging.getLogger("mobile_agent")
    logger.setLevel(level_map.get(level.lower(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.propagate = False

    def _log_fn(msg: str) -> None:
        logger.info(msg)

    return logger, _log_fn


def _create_run_dir(base_dir: str = "runs") -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = Path(base_dir) / ts
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    logger, log_fn = _build_logger(args.log_level)

    if not args.api_key:
        logger.error("Missing OPENROUTER_API_KEY (or pass --api-key).")
        return 2

    from .agent import build_mobile_agent

    run_dir = None
    if args.save_runs:
        try:
            run_dir = _create_run_dir()
            log_fn(f"[RUNS] Saving artifacts to {run_dir}")
        except Exception as exc:
            logger.error(f"Failed to create runs directory: {exc}")
            return 2

    try:
        agent = build_mobile_agent(
            serial=args.serial,
            dry_run=bool(args.dry_run),
            rotation=args.rotation,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            site_url=args.site_url,
            site_name=args.site_name,
            timeout=args.timeout,
            language=args.language,
            history_n=args.history_n,
            temperature=args.temperature,
            top_p=args.top_p,
            max_tokens=args.max_tokens,
            wait_s=args.wait_s,
            scroll_frac=args.scroll_frac,
            run_dir=run_dir,
            log_fn=log_fn,
        )
    except Exception as exc:
        logger.error(str(exc))
        return 2

    if not args.instruction:
        return _interactive_loop(agent, max_steps=args.max_steps, logger=logger)

    try:
        agent.run(args.instruction, max_steps=args.max_steps)
        return 0
    except Exception as exc:
        logger.error(str(exc))
        return 2
