# -*- coding: utf-8 -*-
# [TEST HARNESS] 独立的 CLI，仅用于本地验证；非最终对外 API。
from __future__ import annotations
import os
import argparse
import logging

from agents.discovery.twitter_explorer import TwitterExplorer


def main() -> None:
    parser = argparse.ArgumentParser(
        description="[TEST HARNESS] Twitter(X) ADB Explorer (for local testing only)"
    )
    parser.add_argument("--query", "-q", required=True, help="Search keyword, e.g., 外汇 / Forex")
    parser.add_argument("--max-accounts", "-n", type=int, default=5, help="Max accounts to report before stopping")
    parser.add_argument("--dry-run", type=int, default=0, choices=[0, 1], help="1=print commands without executing taps")
    parser.add_argument("--debug", action="store_true", help="Enable verbose logs from UI agent/executor")
    # Printing controls
    parser.add_argument("--print-thoughts", action="store_true", help="Print UI agent Thought/Action per step")
    parser.add_argument("--print-instruction", action="store_true", help="Also print full UI prompt (may be long)")
    parser.add_argument("--print-results", action="store_true", help="Also print execution result metadata")
    # Brain-vision controls
    parser.add_argument("--brain-vision", type=int, default=1, choices=[0, 1], help="1=feed screenshot to GPT-5 mini after each step")
    parser.add_argument("--vision-width", type=int, default=768, help="Resize screenshot width before feeding to the brain")
    # Output dir
    parser.add_argument("--out-dir", type=str, default=None, help="Base output directory (default runs/twitter_explorer_YYYYmmdd-HHMMSS)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.debug else logging.WARNING,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Sanity check env
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("ERROR: OPENROUTER_API_KEY is not set")

    explorer = TwitterExplorer(
        query=args.query,
        max_accounts=args.max_accounts,
        dry_run=bool(args.dry_run),
        debug=bool(args.debug),
        print_thoughts=bool(args.print_thoughts or args.debug),  # --debug 默认打印 Thought
        print_instruction=bool(args.print_instruction),
        print_results=bool(args.print_results),
        brain_vision=bool(args.brain_vision),
        vision_width=int(args.vision_width),
        out_dir=args.out_dir,
    )
    explorer.run()


if __name__ == "__main__":
    main()
