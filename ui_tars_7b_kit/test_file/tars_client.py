#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tars_client.py
封装：
- OpenRouter Chat Completions 调用 (bytedance/ui-tars-1.5-7b)
- 本地图片 -> data URL (多模态)
- /generation 查询精确费用
- 基于 usage 的费用粗估
- 针对 UI-TARS 的高阶方法 next_action()（内置 GUI Agent prompt 与多图/动作历史拼装）
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests

# ---------------- 常量 ----------------

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "bytedance/ui-tars-1.5-7b"

# 你提供的 GUI Agent 模板（注意：此处故意不包含 {instruction}；任务指令将放到 user 消息中）
GUI_AGENT_SYSTEM_PROMPT = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task. 
## Output Format
```
Thought: ...
Action: ...
```
## Action Space

click(point='<point>x1 y1</point>')
long_press(point='<point>x1 y1</point>')
type(content='') #If you want to submit your input, use "\\n" at the end of `content`.
scroll(point='<point>x1 y1</point>', direction='down or up or right or left')
open_app(app_name=\'\')
drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')
press_home()
press_back()
finished(content='xxx') # Use escape characters \\\', \\\", and \\\\n in content part to ensure we can parse the content in normal python string format.


## Note
- Use {language} in `Thought` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.
"""

# ---------------- 工具函数 ----------------

def _as_openrouter_image_item(data_url: str) -> Dict[str, Any]:
    """把 data URL 打包成 OpenRouter 兼容的多模态图片块。"""
    return {"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}}


def _raise_for_status_verbose(resp: requests.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        detail = resp.json()
    except Exception:
        detail = resp.text
    raise requests.HTTPError(f"HTTP {resp.status_code}: {detail}")


# ---------------- 核心客户端 ----------------

class TarsClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        http_referer: Optional[str] = None,
        x_title: Optional[str] = None,
        timeout: int = 600,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("缺少 OPENROUTER_API_KEY。请先设置环境变量。")
        self.http_referer = http_referer
        self.x_title = x_title
        self.timeout = timeout

    # ---------- 通用 Chat Completions ----------

    def chat(
        self,
        prompt: str,
        image_path: Optional[Path | str] = None,
        system_prompt: str = "你是一个擅长理解界面与图文的中文助手。",
        model: str = DEFAULT_MODEL,
        stream: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        调用 Chat Completions。返回 JSON dict。
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.x_title:
            headers["X-Title"] = self.x_title

        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if image_path:
            data_url = self._image_path_to_data_url(Path(image_path))
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if extra:
            payload.update(extra)

        resp = requests.post(
            f"{OPENROUTER_API_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        _raise_for_status_verbose(resp)
        return resp.json()

    # ---------- UI-TARS 便捷方法：根据模板产出下一步 Action ----------

    def next_action(
        self,
        instruction: str,
        action_history: Optional[str] = None,
        screenshots: Optional[List[Path | str]] = None,
        language: str = "中文",
        model: str = DEFAULT_MODEL,
        stream: bool = False,
        extra: Optional[Dict[str, Any]] = None,
        system_prompt_template: str = GUI_AGENT_SYSTEM_PROMPT,
    ) -> Dict[str, Any]:
        """
        针对 UI-TARS 的便捷调用：
        - 把“角色/输出格式/动作空间/注意事项”固定放 system prompt
        - 把本次 {instruction} 放到 user
        - 可选拼接动作历史与多张截图
        """
        # 渲染 system prompt（主要填 {language}）
        system_prompt = system_prompt_template.format(language=language)

        # 组装 user 内容（文本 + 多图）
        user_contents: List[Dict[str, Any]] = []
        text_parts = [f"## User Instruction\n{instruction}"]
        if action_history:
            text_parts.append(f"## Action History\n{action_history}")
        user_text = "\n\n".join(text_parts)
        user_contents.append({"type": "text", "text": user_text})

        if screenshots:
            for p in screenshots:
                data_url = self._image_path_to_data_url(Path(p))
                user_contents.append(_as_openrouter_image_item(data_url))

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_contents},
        ]

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }

        # 稳定输出建议：低温度，避免格式跑飞
        default_extra = {"temperature": 0.2, "top_p": 0.95}
        if extra:
            default_extra.update(extra)
        payload.update(default_extra)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.x_title:
            headers["X-Title"] = self.x_title

        resp = requests.post(
            f"{OPENROUTER_API_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        _raise_for_status_verbose(resp)
        return resp.json()

    # ---------- 计费与工具 ----------

    def generation_detail(self, generation_id: str) -> Optional[Dict[str, Any]]:
        """
        用响应里的 id 查询 /generation，拿到 total_cost 和原生 token 数。
        可能因权限/延迟等返回 None。
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}
        r = requests.get(
            f"{OPENROUTER_API_BASE}/generation",
            headers=headers,
            params={"id": generation_id},
            timeout=60,
        )
        if r.status_code >= 400:
            return None
        data = r.json()
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            return data["data"]
        return data if isinstance(data, dict) else None

    @staticmethod
    def rough_cost(
        usage: Optional[Dict[str, Any]],
        in_usd_per_mtok: float = 0.10,
        out_usd_per_mtok: float = 0.20,
    ) -> Optional[float]:
        """
        基于 usage 的粗略费用估算（USD）。最终计费请以 /generation 为准。
        """
        if not usage:
            return None
        pt = usage.get("prompt_tokens", 0) or 0
        ct = usage.get("completion_tokens", 0) or 0
        return (pt * in_usd_per_mtok + ct * out_usd_per_mtok) / 1_000_000.0

    # ---------- 内部工具 ----------

    @staticmethod
    def _guess_mime(path: Path) -> str:
        mime, _ = mimetypes.guess_type(str(path))
        return mime or "image/png"

    def _image_path_to_data_url(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"图片不存在：{path}")
        if not path.is_file():
            raise IsADirectoryError(f"不是文件：{path}")
        mime = self._guess_mime(path)
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"