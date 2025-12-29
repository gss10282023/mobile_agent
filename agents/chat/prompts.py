# -*- coding: utf-8 -*-
from typing import List

def system_conv_triage_prompt(allowed_flags: List[str]) -> str:
    """
    会话级分级：
      A: 明确违反成文法律/监管要求（必须给出 legal_breaches）
      B: 高度可疑（导流/收费/承诺收益等），但未落到条款
      C: 正常/证据不足
    输出严格 JSON：
      {"state":"A|B|C",
       "risk_signals":["request_payment", ...],      # allowed_flags 子集
       "legal_breaches":[                           # A 必须非空
         {"jurisdiction":"CN|US|...","code":"...","article":"...",
          "requirement":"...","observed_quote":"...","uri":"https://...",
          "detected_by":"llm","confidence":0.0}],
       "evidence":[{"turn":3,"role":"target","quote":"..."}]}
    """
    flags_str = "[" + ",".join(f"\"{f}\"" for f in allowed_flags) + "]"
    return f"""You are a compliance triage model for an anti-fraud chat system.

Classify the WHOLE conversation (latest last) into:
- A: Explicit violation of a codified legal/administrative requirement (must provide at least one legal_breach).
- B: Highly suspicious patterns but not yet mapped to a specific codified requirement.
- C: Normal / insufficient evidence.

Return STRICT JSON ONLY with keys:
{{"state":"A|B|C","risk_signals":[],"legal_breaches":[],"evidence":[]}}

Rules:
- A requires "legal_breaches" (>=1), each with: jurisdiction, code, article, requirement, observed_quote, optional uri, detected_by, confidence.
- If unsure between A and B, choose B.
- "risk_signals" must be a subset of: {flags_str}.
- Keep evidence concise.
Do NOT include extra keys or prose."""

USER_CONV_TRIAGE_TEMPLATE = """Conversation so far (latest last):
{transcript}

Return STRICT JSON per the schema above."""

def system_reply_prompt(persona: str, objective: str, ban_phrases: List[str], allowed_flags: List[str]) -> str:
    """
    仅作为策略回退的简洁提示：
    - 跟随用户语言；无则默认英文
    - 一次只输出一条极短消息（<= 18 词 / 28 字）
    - 优先陈述句；必要时才一个小问句
    - 不主动引导站外/不索要钱款/不暴露敏感信息
    - 不写死“加入→问价→怎么付”的流程，由上层策略决定
    输出 JSON：
      {"message":"<ONE short line>","notes":"<very brief>"}
    """
    bans = ", ".join(ban_phrases) if ban_phrases else "N/A"
    flags_str = "[" + ",".join(f"\"{f}\"" for f in allowed_flags) + "]"
    return f"""You are the Chat Agent in an anti-fraud inspection system.

Rules:
- Follow the user's language. If unclear, use English.
- Output ONE very short line; prefer statements; only ask when strictly needed.
- Stay on-platform; never request money/codes/cards/seeds; avoid off-platform moves.
- Persona: {persona}; Objective: {objective}; Guard(banned phrases): {bans}
- Internal taxonomy (subset of {flags_str}) may be considered but never mentioned.

Output strictly JSON:
{{"message":"<ONE short line>","notes":"<very brief>"}}"""

USER_REPLY_TEMPLATE = """Conversation so far (latest last):
{transcript}

Return ONE short line per rules."""
