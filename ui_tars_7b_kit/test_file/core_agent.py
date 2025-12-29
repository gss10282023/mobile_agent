# core_agent.py
from __future__ import annotations
from action_parser import parse_mobile_output, ParsedOutput
from action_executor import ActionExecutor

"""
Step 1：先提供一个“已知模型输出文本”的入口，方便在不调用模型的前提下测试：
- 解析是否稳
- 执行分发是否正确
Step 2：我们会在这里接入 UI-TARS-1.5-7B 的实际调用（含截图、多轮历史等）。
"""

class MobileUITARSAgent:
    def __init__(self, executor: ActionExecutor, language: str = "Chinese"):
        self.executor = executor
        self.language = language

    def step_with_model_output(self, model_text: str) -> ParsedOutput:
        """
        直接给模型输出（包含 Thought/Action），解析后交由执行器执行。
        返回解析结果，便于上层断言 thought/raw_action 等。
        """
        parsed = parse_mobile_output(model_text)
        # 官方模板每步仅 1 个动作
        action = parsed.actions[0]
        self.executor.execute(action)
        return parsed
