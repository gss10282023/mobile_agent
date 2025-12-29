# Anti-fraud Agent

本项目实现了一套围绕移动端 X (Twitter) 应用的“探索-判断”自动化流程，核心目标是从关键词触发的账号列表中甄别潜在欺诈账户。代码分层清晰，便于快速上手、复用与扩展新的流程或判别能力。

## 项目速览
- **探索层 (Discovery)**：`agents/discovery` 提供 `TwitterExplorer` 主类，串联手机控制、截图、AI 判别与日志落地，可作为新增探索器的蓝本。
- **决策大脑 (Brain)**：`agents/gpt5` 封装 GPT-5 / OpenRouter 通用客户端，支持函数调用、自动重试及图像输入。
- **UI 执行层**：`agents/ui_agent`、`ui_tars_7b_kit`、`uia2_command_kit` 负责截图、解析 UI 操作、坐标映射与 ADB 执行，屏蔽底层实现细节。
- **运行产物**：`runs/` 保存探索过程截图、账户记录与对话 Markdown，便于复盘。
- **需求清单**：`TODO.md` 记录后续工作与里程碑，帮助规划扩展优先级。

## 核心工作流程
1. **启动探索器**：通过 CLI (`python -m agents.discovery.cli_twitter_explorer`) 指定关键词、账号数上限等参数。
2. **UI 代理执行**：`TwitterExplorer` 创建 `UITarsMobileAgent`，调用 UI-TARS 模型生成动作，借助 `uia2_command_kit` 在真实/模拟设备上执行。
3. **截图与上下文**：每次动作后截屏，`ImageLogger` 保存帧，并在账户会话期间归档关键帧。
4. **决策大脑循环**：`Gpt5Client` 接收 UI 步骤反馈、截图与自定义工具调用（`ui_step`、`report_account` 等），规划后续操作并判定可疑度。
5. **结构化输出**：完成账号评估后写出报告、标记进入/离开账户，直到达到上限或模型主动结束。

## 目录结构（关键部分）
| 路径 | 作用 |
| --- | --- |
| `agents/discovery/brain_tools.py` | 工具门面，注册 `ui_step`、`report_account` 等函数并管理截图日志。 |
| `agents/discovery/twitter_explorer.py` | 探索器主类，组装设备、UI 代理与 GPT-5 客户端，在 `run()` 中驱动整体循环。 |
| `agents/discovery/cli_twitter_explorer.py` | CLI 入口，用于本地调试探索流程。 |
| `agents/gpt5/gpt5_client_library.py` | GPT-5/OpenRouter 客户端，含内置工具、图片附件、重试与对话管理。 |
| `agents/ui_agent/uitars_agent.py` | UI 代理封装，负责截图、构造 Prompt、调用模型并执行解析后的动作。 |
| `agents/ui_agent/model_strategies.py` | 模型策略抽象，当前实现 OpenRouter 调用；可扩展自定义 API。 |
| `agents/ui_agent/screenshot_tool.py` | 截图助手，提供 uiautomator2 与 ADB 双重兜底。 |
| `ui_tars_7b_kit/` | UI-TARS 行为空间：解析模型输出 (`action_parser.py`)、动作执行 (`action_executor.py`)、Prompt 模板等。 |
| `uia2_command_kit/` | 与设备交互的命令层，封装 `click`/`drag`/`type` 等原语，由 `Invoker` 执行序列。 |
| `runs/` | 自动生成的运行目录，含帧图像、账户会话、运行日志，可用于调试与归档。 |
| `requirements.txt` | 项目依赖（ADB/UI 自动化 + OpenAI SDK + 数据库存储组件）。 |

## 模块 API 与主要符号
### `agents/discovery/twitter_explorer.py`
- `ROOT: Path`：项目根目录，确保包路径可被导入。
- `_get_device_resolution(device) -> Tuple[int, int]`：多重兜底获取手机分辨率。
- `build_adb_executor(device, invoker, rotation=0, dry_run=False, log_fn=None) -> ADBExecutor`：根据设备参数构建 ADB 执行器。
- `class TwitterExplorer`：负责串联各层组件。
  - `__init__(query, max_accounts=5, brain_model=..., ui_model=..., dry_run=True, ...)`：配置运行目录、设备、UI 代理、BrainTools 与 GPT 客户端。
  - `_log_if(message)`：在 `--debug` 模式下输出日志。
  - `run()`：调用 `Gpt5Client.run_tools_loop(max_hops=64)`，并在结束后保存对话 Markdown 与截图目录提示。
  - 重要实例属性：`run_dir`、`ui_frames_dir`、`device`、`executor`、`ui_agent`、`brain_tools`、`brain`。

### `agents/discovery/brain_tools.py`
- `class ImageLogger(frames_dir, log_fn=None)`：轻量截图记录器。
  - `save_ui_frame(b64_png)`：保存全局 UI 帧，并在会话中复制到账户目录。
  - `start_account_session(handle, display_name=None)` / `end_account_session()`：管理账户级截图文件夹。
  - `save_b64_to_current_account(b64_png)`：向当前会话追加单帧。
- `class BrainTools(ui_agent, image_logger, ui_global_instruction, ...)`：向 GPT 暴露工具、协调截图与日志。
  - `set_brain(brain_client)`：注入 `Gpt5Client` 引用。
  - `schema() -> List[Dict]`：返回工具的 JSON Schema；供 GPT 函数调用使用。
  - `registry() -> Dict[str, Callable]`：映射工具名到实际实现。
  - `ui_step(subtask) -> Dict`：执行单步 UI 操作，打印思考/动作，按需注入截图。
  - `mark_enter_account(handle, display_name=None)` / `mark_leave_account(handle, display_name=None)`：标记账户会话并同步日志。
  - `report_account(display_name, handle=None, profile_url=None, suspicious=False, score=0.5, reasons=None, evidence=None)`：输出结构化账号报告。
  - `log(text)`：打印脑内日志。
  - `flush()`：保持接口兼容（当前为空操作）。
  - `_default_report_sink(payload)`：默认报告打印逻辑；可被自定义回调替换。

### `agents/discovery/prompts_min.py`
- `UI_GLOBAL_INSTRUCTION_TEMPLATE: str`：UI 代理的全局操作指令模板。
- `build_brain_system_prompt(query, max_accounts) -> str`：构造决策大脑的系统提示。
- `build_brain_user_kickoff() -> str`：提供探索流程的起始用户消息。

### `agents/discovery/image_io.py`
- `decode_b64_to_image(b64_png) -> Optional[Image]`：解码 base64 PNG。
- `save_b64_png_to_file(b64_png, path) -> bool`：保存 base64 PNG 到本地文件。
- `resize_image(img, max_w) -> Image`：按等比缩放图像。
- `resize_b64_png(b64_png, max_w) -> str`：缩放后重新编码 base64 PNG。
- `stitch_vertical(images, margin=8, bg=(255,255,255)) -> Image`：竖向拼接多张图片。

### `agents/gpt5/gpt5_client_library.py`
- `DEFAULT_MODEL: str`：默认调用的 OpenRouter 模型名（可由环境变量 `OR_MODEL` 覆盖）。
- 工具函数：
  - `tool_web_search(query, max_results=5)`、`tool_fetch_url(url, max_chars=6000, timeout=15.0)`、`tool_get_time(tz=None)`、`tool_read_file(path, max_bytes=1_000_000)`、`tool_write_file(path, content, overwrite=True)`：内建函数调用工具。
  - `file_to_data_url(path) -> str`：将本地文件转换为 data URL。
  - `build_builtin_tools_json() -> List[Dict]`：返回内建工具的 JSON Schema。
  - `safe_chat_create(client, **kwargs)`：对 OpenAI SDK 调用做容错重试。
- 辅助函数：`_looks_like_cloudflare_html(text)`、`_err_status_and_text(e)`（错误分析）。
- `class Gpt5Client(...)`：对 OpenRouter / GPT-5 的高层封装。
  - `__init__(system_prompt=None, model=DEFAULT_MODEL, enable_builtin_tools=True, extra_tools_schema=None, extra_tool_registry=None, ...)`：初始化对话状态、工具集合与重试策略。
  - `set_model(model)` / `set_system_prompt(text)`：动态调整模型与系统提示。
  - `add_user_message(text)`：追加用户消息。
  - `attach_image(path_or_url, caption=None)`：把本地或远程图片编码为 Vision 消息。
  - `clear_history(keep_system=True)`：清理对话历史。
  - `run_tools_loop(max_hops=8) -> Dict[str, Any]`：在消息与函数调用之间循环，直至完成。
  - `save_markdown(path) -> str`：将对话导出为 Markdown。

### `agents/ui_agent/uitars_agent.py`
- `class UITarsMobileAgent(...)`：封装截图构建、模型调用与动作执行。
  - `__init__(executor, device, model='bytedance/ui-tars-1.5-7b', language='Chinese', history_n=3, ...)`：配置模型策略、截图工具、上下文缓存。
  - `_capture_screen() -> Tuple[Image, Tuple[int, int]]`：调用设备截图。
  - `_build_messages(instruction, cur_b64) -> List[Dict]`：按 UI-TARS 模板拼装消息历史与截图。
  - `step(instruction) -> Tuple[str, ParsedOutput, List[Dict]]`：执行一步 UI 推理并调用 `ADBExecutor`。
  - `run(instruction, max_steps=20) -> List[Dict]`：循环执行多步，直到模型返回 `finished()`。
  - 关键属性：`history_imgs`、`history_resps`、`model_strategy`、`extra_headers`。

### `agents/ui_agent/model_strategies.py`
- `class ChatModelStrategy(ABC)`：抽象基类，定义 `generate(messages, model=None, temperature, top_p, max_tokens, extra_headers=None) -> str`。
- `class OpenRouterStrategy(ChatModelStrategy)`：基于 OpenRouter API 的实现。
  - `__init__(api_key=None, base_url='https://openrouter.ai/api/v1', timeout=None, default_model='bytedance/ui-tars-1.5-7b')`。
  - `generate(...) -> str`：调用 `chat.completions.create`。
- `_build_openrouter_client(api_key=None, base_url=..., timeout=None) -> OpenAI`：封装凭证加载（依赖环境变量 `OPENROUTER_API_KEY`）。

### `agents/ui_agent/screenshot_tool.py`
- `pil_to_base64_png(img) -> str`：PIL 图片编码为 base64 PNG。
- `class ScreenshotTool(device, log_fn=print)`：统一截图入口。
  - `capture() -> Tuple[Image, Tuple[int, int]]`：优先使用 uiautomator2 截图，失败时回退 ADB。
  - `_adb_screencap() -> Image`、`_adb_run(args, serial)`、`_ensure_adb_online(serial)`、`_adb_serial()`：ADB 相关辅助方法。

### `ui_tars_7b_kit/action_executor.py`
- `@dataclass CoordinateMapper(render_w, render_h, device_w, device_h, valid_rect=(0,0,0,0), rotation=0)`：负责渲染坐标到设备坐标的映射，提供 `to_device(point)`。
- `class ActionExecutor`：动作执行抽象基类，定义 `execute(action)`。
- `@dataclass ExecutorConfig`：配置长按、拖拽、滑动时间、滚动幅度、等待时长、dry-run 模式等。
- `class ADBExecutor(device, invoker, render_size, valid_rect=None, rotation=0, config=None)`：将解析后的动作转换为 `uia2_command_kit` 命令。
  - `_device_size()` / `_mapper()`：获取设备尺寸、构建坐标映射。
  - `execute(action) -> List[Dict]`：根据动作类型生成命令，支持 `click`、`scroll`、`drag`、`type`、`open_app`、`hotkey`、`wait`、`finished` 等。

### `ui_tars_7b_kit/action_parser.py`
- `@dataclass MobileAction(type, params)`：表示单个 UI 动作。
- `@dataclass ParsedOutput(thought, actions, raw_action)`：封装模型 Thought/Action 结构。
- 解析辅助函数：`_extract_point`、`_extract_str_arg`、`_func_name`、`_inside_parens`、`_extract_xy_tuple_arg`。
- `parse_mobile_output(text) -> ParsedOutput`：主入口，将 UI-TARS 模型输出解析为结构化动作。

### `ui_tars_7b_kit/prompts.py`
- `MOBILE_PROMPT_TEMPLATE: str`：UI-TARS 模型提示模板，描述 Thought/Action 规范与动作空间。

## 环境要求与快速上手
1. **系统依赖**
   - Python ≥ 3.10，建议使用虚拟环境。
   - 已安装 `adb`，并能连接目标 Android 设备或模拟器。
   - 设备需开启开发者模式与 USB 调试。
2. **安装依赖**
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   # 若需启用内置 web_search/fetch_url 工具：
   pip install duckduckgo-search httpx trafilatura
   ```
3. **配置环境变量**
   ```bash
   export OPENROUTER_API_KEY="<你的 OpenRouter Key>"
   export OR_SITE_URL="https://your.site"      # 可选：遵循 OpenRouter 最佳实践
   export OR_SITE_TITLE="Anti-fraud Agent"     # 可选：站点名称
   ```
4. **运行探索器（干跑示例）**
   ```bash
   python -m agents.discovery.cli_twitter_explorer \
     --query "外汇" --max-accounts 2 --dry-run 1 --debug
   ```
   - `--dry-run 1`：仅打印动作，不执行真实点击；调通流程后可改为 `0`。
   - `--print-thoughts/--print-results`：按需输出模型思考与执行反馈。
   - 输出目录位于 `runs/twitter_explorer_<时间戳>/`。

## 扩展与自定义建议
- **新增判别逻辑**：在 `BrainTools.schema()` 中补充工具描述，并于 `registry()` 注册实现；同步调整 `prompts_min.py` 的系统提示。
- **接入其他应用/场景**：复制 `TwitterExplorer`，改写全局指令与 Prompt；如需新动作集，可扩展 `action_parser.py` 与 `action_executor.py`。
- **增强数据落地**：通过自定义 `report_sink` 推送账号报告到数据库或消息队列；`runs/` 可作为最简归档。
- **替换模型或网关**：继承 `ChatModelStrategy` 实现自定义 `generate()`，并在 `UITarsMobileAgent` 初始化时注入。

## 调试技巧
- 启用 `--debug` 或 `--print-thoughts` 观察 UI 模型的 Thought/Action，定位坐标或逻辑异常。
- 查看 `runs/.../ui_tars_frames/step_XXX.png` 及 `accounts/<账户>/frame_YYY.png`，确认截图质量与会话节奏。
- 遇到截图失败时，`ScreenshotTool` 会自动切换 `adb exec-out screencap -p`，必要时检查设备连通性。
- 若函数调用出现缺参错误，优先检查 `BrainTools.schema()` 与 Prompt 模板约束。




