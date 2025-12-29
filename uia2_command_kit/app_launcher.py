# - 别名解析 -> app_start -> monkey 兜底 -> Launcher 搜索
# - 启动后等待前台稳定（两次一致）
# - 不包含对 "settings/设置" 的特殊 Intent 启动（现在可通过别名映射选择 Intent）
from __future__ import annotations

import re
import time
from typing import Optional, Dict, Any, Set, Tuple

# 语音助手/Google App 包（需排除/拦截）
ASSISTANT_PKGS: Set[str] = {
    "com.google.android.googlequicksearchbox",
    "com.google.android.apps.googleassistant",
}

# 你可以在这里放一些“常用”的默认映射（可被 app_aliases 覆盖）
# 支持两种形式：{"package": "..."} 或 {"intent": "..."}
DEFAULT_ALIAS_MAP: Dict[str, Dict[str, str]] = {
    # 系统设置常用入口
    "settings": {"intent": "android.settings.SETTINGS"},
    "设置": {"intent": "android.settings.SETTINGS"},
    "wifi": {"intent": "android.settings.WIFI_SETTINGS"},
    "无线": {"intent": "android.settings.WIFI_SETTINGS"},
    "bluetooth": {"intent": "android.settings.BLUETOOTH_SETTINGS"},
    "蓝牙": {"intent": "android.settings.BLUETOOTH_SETTINGS"},
    "location": {"intent": "android.settings.LOCATION_SOURCE_SETTINGS"},
    "位置信息": {"intent": "android.settings.LOCATION_SOURCE_SETTINGS"},

    # 常见系统/谷歌应用（按包名）
    "camera": {"package": "com.android.camera"},
    "相机": {"package": "com.android.camera"},
    "chrome": {"package": "com.android.chrome"},
    "浏览器": {"package": "com.android.chrome"},
    "play 商店": {"package": "com.android.vending"},
    "play store": {"package": "com.android.vending"},
    "电话": {"package": "com.android.dialer"},
    "phone": {"package": "com.android.dialer"},
    "短信": {"package": "com.google.android.apps.messaging"},
    "messages": {"package": "com.google.android.apps.messaging"},
    "计算器": {"package": "com.google.android.calculator"},
    "calendar": {"package": "com.google.android.calendar"},
    "日历": {"package": "com.google.android.calendar"},
    "地图": {"package": "com.google.android.apps.maps"},
    "maps": {"package": "com.google.android.apps.maps"},
    "gmail": {"package": "com.google.android.gm"},
    "youtube": {"package": "com.google.android.youtube"},
}


def open_app(
    d,
    app_name: str,
    app_aliases: Optional[Dict[str, object]] = None,  # 兼容：str 或 {"package"/"intent": "..."}
    launcher_packages: Optional[Set[str]] = None,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """
    打开应用（包名/别名/人类名称），返回 d.app_current() 的结果字典。
    - d: uiautomator2 设备对象
    - app_name: 包名、别名或人类可读名称
    - app_aliases: 可选；别名映射（支持 "com.pkg" 字符串、或 {"package": "..."}、{"intent": "..."}）
    - launcher_packages: 可选；桌面包名集合（用于排除桌面）
    - timeout: 前台稳定等待时长（秒）
    """
    if not app_name:
        raise ValueError("app_name 不能为空")

    app_aliases = app_aliases or {}
    launcher_packages = launcher_packages or set()

    # 统一规范化键
    name_in = app_name.strip()
    name_norm = _norm(name_in)

    # 解析目标：优先用户传入 -> 其次内置默认映射 -> 否则走原逻辑
    kind, target = _resolve_target(name_norm, app_aliases, DEFAULT_ALIAS_MAP)

    # 1) 已解析到包名：优先原生启动，失败用 monkey 兜底
    if kind == "package" or (kind is None and "." in name_in):
        pkg = target or name_in  # 用户没映射但输入里是包名
        try:
            d.app_start(pkg, use_monkey=False)
        except Exception:
            try:
                d.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
            except Exception:
                pass
        return _wait_front(
            d,
            launcher_packages=launcher_packages,
            expect_pkgs=None,
            timeout=timeout,
            exclude_pkgs=ASSISTANT_PKGS,
        )

    # 2) 已解析到 Intent：直接用 am start，避开 Launcher 搜索与 IME
    if kind == "intent":
        try:
            d.shell(f"am start -a {target}")
        except Exception:
            pass
        return _wait_front(
            d,
            launcher_packages=launcher_packages,
            expect_pkgs=None,
            timeout=timeout,
            exclude_pkgs=ASSISTANT_PKGS,
        )

    # 3) 非包名且无映射：走 Launcher 搜索兜底（保留你认可的两点：HOME Intent + 不自动 \n）
    return _open_via_launcher_search(
        d, label=name_in, launcher_packages=launcher_packages, timeout=timeout
    )


def _open_via_launcher_search(
    d, label: str, launcher_packages: Set[str], timeout: float
) -> Dict[str, Any]:
    # 用 HOME Intent 回到桌面（避免双击 Home 触发语音/手势）
    try:
        d.shell("am start -a android.intent.action.MAIN -c android.intent.category.HOME")
        time.sleep(0.2)
    except Exception:
        pass
    # 兜底按一次 Home（仅一次）
    try:
        d.press("home")
        time.sleep(0.2)
    except Exception:
        pass

    # 尝试启用快速输入法
    try:
        if hasattr(d, "set_input_ime"):
            d.set_input_ime(True)
        else:
            try:
                d.set_fastinput_ime(True)
            except Exception:
                pass
    except Exception:
        pass

    # 首页搜索 —— 仅尝试真实可编辑输入框（避免命中“搜索入口”导致跳 Google App）
    search_selectors = [
        dict(resourceId="com.google.android.apps.nexuslauncher:id/search_box_input"),
        dict(resourceId="com.google.android.apps.nexuslauncher:id/search_box_text"),
        dict(className="android.widget.EditText"),
    ]
    if _try_launcher_search_and_open(d, label, search_selectors):
        return _wait_front(
            d,
            launcher_packages=launcher_packages,
            expect_pkgs=None,
            timeout=timeout,
            exclude_pkgs=ASSISTANT_PKGS,
        )

    # 打开抽屉后再试
    try:
        w, h = d.window_size()
        d.swipe(w * 0.5, h * 0.95, w * 0.5, h * 0.10, 0.30)
        time.sleep(0.3)
    except Exception:
        pass

    drawer_search_selectors = [
        dict(resourceId="com.google.android.apps.nexuslauncher:id/apps_list_search_box"),
        dict(className="android.widget.EditText"),
    ]
    if _try_launcher_search_and_open(d, label, drawer_search_selectors):
        return _wait_front(
            d,
            launcher_packages=launcher_packages,
            expect_pkgs=None,
            timeout=timeout,
            exclude_pkgs=ASSISTANT_PKGS,
        )

    raise RuntimeError(f"launcher 搜索未找到目标应用：{label}")


def _try_launcher_search_and_open(d, label: str, selectors: list) -> bool:
    for sel in selectors:
        obj = d(**sel)
        if not obj.exists:
            continue

        # 点击聚焦输入框
        try:
            obj.click()
            time.sleep(0.1)
        except Exception:
            pass

        # 如果此时已被语音助手占前台，退回并尝试下一个 selector
        if _guard_assistant_and_recover(d):
            continue

        # 先只输入文本，不自动追加换行
        typed = False
        try:
            d.send_keys(label, clear=True)
            typed = True
        except Exception:
            try:
                obj.set_text(label)
                typed = True
            except Exception:
                typed = False

        # 打字过程中若被语音助手顶前台，退回并换下一个 selector
        if _guard_assistant_and_recover(d):
            continue

        if not typed:
            continue  # 这个 selector 不可输入，换下一个

        # 轮询搜索结果：先精确匹配，再模糊匹配
        for _ in range(12):
            exact = d(textMatches=f"(?i)^{re.escape(label)}$")
            if exact.exists:
                try:
                    exact.click()
                    return True
                except Exception:
                    pass

            fuzzy = d(textMatches=f"(?i).*{re.escape(label)}.*")
            if fuzzy.exists:
                try:
                    fuzzy.click()
                    return True
                except Exception:
                    pass

            time.sleep(0.35)

            # 轮询中若语音助手前台，立即退回继续尝试
            if _guard_assistant_and_recover(d):
                break  # 结束当前 selector，尝试下一个

        # 结果未出现，最后再试一次回车（ENTER）
        try:
            d.shell("input keyevent 66")  # KEYCODE_ENTER
            time.sleep(0.25)
        except Exception:
            pass

        if _guard_assistant_and_recover(d):
            continue  # ENTER 引发助手，退回后换 selector

        # 回车后再短轮询一次
        for _ in range(6):
            exact = d(textMatches=f"(?i)^{re.escape(label)}$")
            if exact.exists:
                try:
                    exact.click()
                    return True
                except Exception:
                    pass

            fuzzy = d(textMatches=f"(?i).*{re.escape(label)}.*")
            if fuzzy.exists:
                try:
                    fuzzy.click()
                    return True
                except Exception:
                    pass

            time.sleep(0.35)

            if _guard_assistant_and_recover(d):
                break

    return False


def _guard_assistant_and_recover(d) -> bool:
    """
    若前台被语音助手占据，则按一次返回键恢复；返回 True 表示刚刚触发了助手且已处理。
    """
    try:
        cur = d.app_current() or {}
        pkg = cur.get("package")
    except Exception:
        return False

    if pkg in ASSISTANT_PKGS:
        try:
            d.press("back")
            time.sleep(0.2)
        except Exception:
            pass
        return True
    return False


def _wait_front(
    d,
    launcher_packages: Set[str],
    expect_pkgs: Optional[Set[str]] = None,
    timeout: float = 8.0,
    *,
    exclude_pkgs: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    等待前台稳定（两次一致）：
    - 若给 expect_pkgs：必须命中其中之一；
    - 否则：只要当前包存在且不在 launcher_packages/排除集合 就视为成功。
    """
    exclude_pkgs = exclude_pkgs or set()

    end = time.time() + timeout
    last = None
    stable_hits = 0

    while time.time() < end:
        cur = d.app_current() or {}
        pkg = cur.get("package")
        ok = False
        if expect_pkgs:
            ok = pkg in expect_pkgs
        else:
            ok = bool(pkg) and pkg not in launcher_packages and pkg not in exclude_pkgs

        if ok:
            if last == cur:
                stable_hits += 1
                if stable_hits >= 2:
                    return cur
            else:
                stable_hits = 1
                last = cur
        time.sleep(0.35)

    return d.app_current() or {}


# ---------- 别名解析 ----------

def _norm(s: str) -> str:
    """大小写不敏感 + 合并多空格"""
    return re.sub(r"\s+", " ", s.strip().lower())


def _resolve_target(
    name_norm: str,
    user_aliases: Dict[str, object],
    default_alias_map: Dict[str, Dict[str, str]],
) -> Tuple[Optional[str], Optional[str]]:
    """
    返回 (kind, value)
      kind ∈ {"package","intent", None}
      value 为对应字符串或 None
    解析优先级：用户别名 > 默认别名
    支持三种 value 形态：
      1) 纯字符串包名，例如 "com.android.chrome"
      2) "intent:android.settings.SETTINGS" 这类字符串
      3) dict: {"package":"..." } 或 {"intent":"..."}
    """
    # 组装“规范化键 -> 映射值”
    user_map_norm: Dict[str, object] = {}
    for k, v in user_aliases.items():
        user_map_norm[_norm(str(k))] = v

    default_map_norm: Dict[str, object] = { _norm(k): v for k, v in default_alias_map.items() }

    # 命中用户
    if name_norm in user_map_norm:
        return _parse_alias_value(user_map_norm[name_norm])
    # 命中默认
    if name_norm in default_map_norm:
        return _parse_alias_value(default_map_norm[name_norm])

    return (None, None)


def _parse_alias_value(v: object) -> Tuple[Optional[str], Optional[str]]:
    # dict 形式
    if isinstance(v, dict):
        if "package" in v and isinstance(v["package"], str):
            return ("package", v["package"])
        if "intent" in v and isinstance(v["intent"], str):
            return ("intent", v["intent"])
        return (None, None)
    # 字符串形式
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("intent:"):
            return ("intent", s.split(":", 1)[1].strip())
        if "." in s:
            return ("package", s)
        return (None, None)
    return (None, None)
