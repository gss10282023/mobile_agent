# test_step1_parser.py
from action_parser import parse_mobile_output
from action_executor import PrintExecutor
from core_agent import MobileUITARSAgent

CASES = [
    """Thought: 我将点击搜索框以激活输入。
Action: click(point='<point>120 240</point>')""",
    """Thought: 长按第一个应用图标以进入编辑模式。
Action: long_press(point="<point>360 640</point>")""",
    r"""Thought: 输入关键词并回车。
Action: type(content='UI-TARS 测试\\n')""",
    """Thought: 向下滚动以显示更多结果。
Action: scroll(point='<point>540 1600</point>', direction='down')""",
    """Thought: 打开设置应用。
Action: open_app(app_name='设置')""",
    """Thought: 拖拽通知面板。
Action: drag(start_point='<point>540 0</point>', end_point='<point>540 800</point>')""",
    """Thought: 返回上一页。
Action: press_back()""",
    """Thought: 回到桌面。
Action: press_home()""",
    r"""Thought: 任务完成，已收集到目标信息。
Action: finished(content='已完成，结果保存在 /sdcard/Download/result.txt')""",
]

if __name__ == "__main__":
    exe = PrintExecutor()
    agent = MobileUITARSAgent(executor=exe, language="Chinese")

    for i, text in enumerate(CASES, 1):
        print("\n" + "="*20 + f" CASE {i} " + "="*20)
        parsed = agent.step_with_model_output(text)
        print("[THOUGHT]", parsed.thought)
        print("[RAW_ACTION]", parsed.raw_action)
