from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import json

from PIL import Image

from ui_tars_7b_kit.action_parser import ParsedOutput


LogFn = Callable[[str], None]


class RunRecorder:
    def __init__(
        self,
        run_dir: Path,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        log_fn: Optional[LogFn] = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.steps_dir = self.run_dir / "steps"
        self._step = 0
        self._log = log_fn

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.steps_dir.mkdir(parents=True, exist_ok=True)
        if metadata:
            self._write_json(self.run_dir / "metadata.json", metadata)

    def record_step(
        self,
        *,
        instruction: str,
        image: Image.Image,
        model_output: Optional[str],
        parsed: Optional[ParsedOutput],
        results: Optional[List[Dict[str, Any]]],
        error: Optional[str],
    ) -> None:
        self._step += 1
        step_id = f"step_{self._step:03d}"
        image_path = self.steps_dir / f"{step_id}.png"
        json_path = self.steps_dir / f"{step_id}.json"

        try:
            image.save(image_path)
            payload: Dict[str, Any] = {
                "instruction": instruction,
                "model_output": model_output,
                "parsed_action": asdict(parsed) if parsed else None,
                "results": results,
                "error": error,
            }
            self._write_json(json_path, payload)
        except Exception as exc:
            if self._log:
                self._log(f"[RUNS] Failed to write step artifacts: {exc}")

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
