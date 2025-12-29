# agents/chat/cli_chat_agent.py
# -*- coding: utf-8 -*-
import os, json, re, argparse, datetime as dt
from typing import List, Tuple, Dict, Any, Optional
from ulid import ULID
from openai import OpenAI

from .prompts import (
    system_conv_triage_prompt, USER_CONV_TRIAGE_TEMPLATE,
    system_reply_prompt, USER_REPLY_TEMPLATE
)

try:
    import yaml  # optional YAML
except Exception:
    yaml = None

# ---- Defaults / constants ----
DEFAULT_ALLOWED_FLAGS = [
    "request_payment",
    "provide_wallet",
    "offsite_payment",
    "sideload_app",
    "promise_returns",
]
RULE_VERSION_DEFAULT = "harm-v1.2"
PAYLOAD_VERSION = "2025-09"

# ---- Utils ----
def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

def ulid() -> str:
    return str(ULID())

def sanitize(text: str, ban_phrases: List[str]) -> str:
    t = text
    for b in ban_phrases or []:
        if b and b in t:
            t = t.replace(b, "****")
    return t

def sanitize_unicode_str(s: Any) -> str:
    """
    把包含代理/半代理的字符串清洗为合法 UTF-8：
    - 非法码点→U+FFFD
    - 确保可安全传给 httpx / OpenRouter
    """
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.encode("utf-8", errors="replace").decode("utf-8", errors="replace")

def sanitize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    safe: List[Dict[str, Any]] = []
    for m in messages:
        role = sanitize_unicode_str(m.get("role", "user"))
        content = m.get("content", "")
        if isinstance(content, str):
            content = sanitize_unicode_str(content)
        elif isinstance(content, list):
            # 我们当前只用纯文本；为保险也清洗列表中的字符串项
            content = [sanitize_unicode_str(x) if isinstance(x, str) else x for x in content]
        elif isinstance(content, dict):
            # 罕见情况：递归清洗字符串值
            def _rec(o):
                if isinstance(o, str):
                    return sanitize_unicode_str(o)
                if isinstance(o, list):
                    return [_rec(x) for x in o]
                if isinstance(o, dict):
                    return {k: _rec(v) for k, v in o.items()}
                return o
            content = _rec(content)
        safe.append({"role": role, "content": content})
    return safe

def print_event(event: Dict[str, Any]) -> None:
    print("\n=== EVENT WOULD BE STORED ===")
    print(json.dumps(event, ensure_ascii=False, indent=2))
    print("=============================\n")

def mk_event(type_: str, payload: Dict[str, Any], conv_id: str,
             lead_id: str, platform="cli", run_id=None, step_idx=None,
             artifact_path=None) -> Dict[str, Any]:
    return {
        "event_id": ulid(),
        "ts": now_utc_iso(),
        "run_id": run_id,
        "lead_id": lead_id,
        "platform": platform,
        "type": type_,
        "payload": payload,
        "artifact_path": artifact_path,
        "step_idx": step_idx
    }

def build_transcript(turns: List[Tuple[str, str]]):  # 返回已清洗文本
    lines = []
    for role, text in turns[-48:]:
        safe = sanitize_unicode_str(text)
        lines.append(f"{role.upper()}: {safe}")
    return "\n".join(lines)

def detect_lang(s: str) -> str:
    s = s or ""
    for ch in s:
        if '\u4e00' <= ch <= '\u9fff':
            return "zh"
    return "en"

def ensure_ack_prefix(msg: str, lang: str) -> str:
    if not msg: return msg
    ack_zh = ("嗯", "好的", "行", "明白")
    ack_en = ("Ok", "Got it", "Sure", "Alright")
    if lang == "zh":
        if any(msg.startswith(a) for a in ack_zh): return msg
        return f"{ack_zh[0]}，{msg}"
    else:
        if any(msg.lower().startswith(a.lower()) for a in ack_en): return msg
        return f"{ack_en[0]}, {msg}"

def strip_question(msg: str) -> str:
    if not msg: return msg
    return re.sub(r"\?+\s*$", ".", msg.strip())

# ---- Config for risk flags / laws (optional) ----
class FlagsConfig:
    """
    flags 文件（JSON/YAML）：
      {"rule_version":"harm-v1.2",
       "allowed_flags":[{"id":"request_payment","patterns":["\\bpay\\b","转账"]}, ...]}
    也支持：{"allowed_flags":["request_payment", ...]}
    """
    def __init__(self,
                 allowed_flags: List[str],
                 regex_map: Dict[str, List[re.Pattern]],
                 rule_version: str):
        self.allowed_flags = allowed_flags
        self.regex_map = regex_map
        self.rule_version = rule_version

    @classmethod
    def load(cls, path: Optional[str]) -> "FlagsConfig":
        # 内置默认正则
        defaults = {
            "request_payment": [re.compile(r"\b(pay|payment|transfer|wire|remit|fee|subscribe)\b", re.I),
                                re.compile("充值|转账|打钱|订阅|付费")],
            "provide_wallet":  [re.compile(r"(usdt|trx|erc20|trc20|wallet|eth|btc|binance|skrill|usdc)", re.I),
                                re.compile("钱包|地址")],
            "offsite_payment": [re.compile(r"(whatsapp|wechat|line|telegram|discord)", re.I),
                                re.compile("站外|加微信|加TG|电报")],
            "sideload_app":    [re.compile(r"(apk|download.*app|安装.*应用|签名安装)", re.I)],
            "promise_returns": [re.compile(r"(guarantee|guaranteed|稳赚|百分之百|必赚|保收益)", re.I)],
        }

        # 无配置文件：直接使用默认
        if not path:
            return cls(list(DEFAULT_ALLOWED_FLAGS), defaults.copy(), RULE_VERSION_DEFAULT)

        # 读取 JSON/YAML
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        data = _safe_parse_config_text(text)
        if not isinstance(data, dict):
            raise RuntimeError(f"Flags file {path} is not a JSON/YAML object.")

        rule_version = data.get("rule_version") or RULE_VERSION_DEFAULT
        allowed_items = data.get("allowed_flags") or []

        allowed_ids: List[str] = []
        regex_map: Dict[str, List[re.Pattern]] = {}

        # 支持两种形式：
        # 1) ["request_payment", "provide_wallet", ...]
        # 2) [{"id":"request_payment","patterns":[...]} , ...]
        if isinstance(allowed_items, list) and allowed_items:
            if isinstance(allowed_items[0], str):
                # 纯字符串列表
                seen = set()
                for fid in allowed_items:
                    if isinstance(fid, str) and fid not in seen:
                        allowed_ids.append(fid); seen.add(fid)
                regex_map = {fid: [] for fid in allowed_ids}
            elif isinstance(allowed_items[0], dict):
                # 字典列表
                seen = set()
                for item in allowed_items:
                    fid = item.get("id")
                    if not isinstance(fid, str):
                        continue
                    if fid not in seen:
                        allowed_ids.append(fid); seen.add(fid)
                    compiled: List[re.Pattern] = []
                    for p in item.get("patterns") or []:
                        flags = re.I if re.search(r"[A-Za-z]", p) else 0
                        compiled.append(re.compile(p, flags))
                    regex_map[fid] = compiled

        # 合并默认
        for fid in DEFAULT_ALLOWED_FLAGS:
            if fid not in allowed_ids:
                allowed_ids.append(fid)
        for fid, regs in defaults.items():
            if fid not in regex_map or not regex_map[fid]:
                regex_map[fid] = regs

        return cls(allowed_flags=allowed_ids, regex_map=regex_map, rule_version=rule_version)

    def detect_local(self, latest_text: str) -> List[str]:
        s = sanitize_unicode_str(latest_text or "")
        hits = set()
        for fid, regs in self.regex_map.items():
            for r in regs:
                if r.search(s):
                    hits.add(fid); break
        return [fid for fid in self.allowed_flags if fid in hits]

def _safe_parse_config_text(text: str):
    def _try_json(s):
        try: return json.loads(s)
        except Exception: return None
    def _try_yaml(s):
        try:
            import yaml as _y
            return _y.safe_load(s)
        except Exception:
            return None
    obj = _try_json(text) or _try_yaml(text)
    if isinstance(obj, str):
        obj2 = _try_json(obj) or _try_yaml(obj)
        return obj2
    return obj

# ---- OpenRouter wrapper ----
class ORClient:
    def __init__(self, model: str):
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is required.")
        self.client = OpenAI(
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=key,
        )
        self.model = model

    def _chat(self, messages: List[Dict[str, Any]], temperature=0.25, top_p=0.0) -> str:
        # 统一清洗所有消息，防止 surrogates 进入 httpx JSON 序列化
        safe_msgs = sanitize_messages(messages)
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=safe_msgs,
            temperature=temperature,
            top_p=top_p,
            extra_headers={
                "HTTP-Referer": os.getenv("OPENROUTER_REFERER", ""),
                "X-Title": os.getenv("OPENROUTER_X_TITLE", ""),
            }
        )
        return resp.choices[0].message.content or ""

    def triage_conversation(self, transcript: str, allowed_flags: List[str]) -> Dict[str, Any]:
        transcript = sanitize_unicode_str(transcript)
        messages = [
            {"role": "system", "content": system_conv_triage_prompt(allowed_flags)},
            {"role": "user", "content": USER_CONV_TRIAGE_TEMPLATE.format(transcript=transcript)}
        ]
        content = self._chat(messages, temperature=0.0, top_p=0.0)
        m = re.search(r"{.*}", content, re.S)
        data = json.loads(m.group(0) if m else content)

        state = (data.get("state") or "C").strip().upper()
        risk = data.get("risk_signals") or []
        breaches = data.get("legal_breaches") or []
        evid = data.get("evidence") or []
        if isinstance(evid, list) and evid and isinstance(evid[0], str):
            evid = [{"turn": None, "role":"target", "quote": s} for s in evid[:3]]
        return {"state": state, "risk": list(risk), "breaches": breaches, "evidence": evid}

    def propose_reply(self, persona: str, objective: str, ban_phrases: List[str],
                      allowed_flags: List[str], transcript: str) -> Dict[str, str]:
        transcript = sanitize_unicode_str(transcript)
        sys = system_reply_prompt(persona, objective, ban_phrases, allowed_flags)
        usr = USER_REPLY_TEMPLATE.format(transcript=transcript)
        messages = [
            {"role": "system", "content": sys},
            {"role": "user", "content": usr}
        ]
        content = self._chat(messages, temperature=0.3, top_p=0.0)
        m = re.search(r"{.*}", content, re.S)
        data = json.loads(m.group(0) if m else content)
        return {"message": data.get("message", ""), "notes": data.get("notes", "")}

# ---- Lightweight pacing policy (intent-based) ----
_PRICE_WORDS = r"(price|fee|cost|金额|价格|会费|订阅|付费)"
_JOIN_WORDS  = r"(join|subscribe|vip|加入|订阅|会员|群)"
_PAY_WORDS   = r"(pay|payment|转账|付款|汇款)"
_MONEY_RE    = re.compile(r"(\$?\s?\d+[.,]?\d*\s?(usd|usdt|cny|rmb|元|块|美元|刀)?|\d+\s?(usd|usdt|cny|rmb|元|块|美元))", re.I)
_METHODS_RE  = re.compile(r"(usdt|trx|trc20|erc20|eth|btc|binance|skrill|wallet|地址|收款|银行卡|微信|支付宝)", re.I)

def classify_intent(text: str) -> str:
    t = sanitize_unicode_str(text or "").strip()
    if not t: return "EMPTY"
    low = t.lower()
    if re.search(_JOIN_WORDS, low) or ("vip" in low):
        if re.search(_PAY_WORDS, low) or re.search(_PRICE_WORDS, low):
            return "INVITE_WITH_FEE"
        return "INVITE"
    if re.search(_PRICE_WORDS, low):
        return "PRICE_TOPIC"
    if _MONEY_RE.search(low):
        return "PRICE_QUOTED"
    if _METHODS_RE.search(low):
        return "METHODS"
    if re.search(_PAY_WORDS, low):
        return "PAY_TOPIC"
    return "OTHER"

def extract_first_method(text: str) -> Optional[str]:
    m = _METHODS_RE.search(sanitize_unicode_str(text or ""))
    if not m: return None
    word = m.group(1).lower()
    mapping = {
        "usdt": "USDT", "trx":"TRX", "trc20":"TRC20", "erc20":"ERC20",
        "eth":"ETH", "btc":"BTC", "binance":"Binance", "skrill":"Skrill",
        "wallet":"wallet", "地址":"address", "收款":"payment", "银行卡":"bank card",
        "微信":"WeChat", "支付宝":"Alipay"
    }
    return mapping.get(word, word.upper())

def extract_price_phrase(text: str) -> Optional[str]:
    m = _MONEY_RE.search(sanitize_unicode_str(text or ""))
    if not m: return None
    return m.group(0).strip()

def policy_reply(turns: List[Tuple[str,str]], target_text: str) -> Optional[str]:
    """
    顺从推进策略（无状态，但依据最新 target 与上下文）：
      - 邀请(含收费) → 表达想加入；若未见价格 → 只问一次“多少钱”
      - 已出现价格 → 只问一次“怎么付”
      - 提到支付方式/钱包 → 选择一种并让“细节发这里”
    """
    intent = classify_intent(target_text)
    last3_agent = [t for r,t in turns if r=="agent"][-3:]
    asked_price  = any(re.search(_PRICE_WORDS + r".*\?$", s, re.I) for s in last3_agent)
    asked_method = any(re.search(r"(how.*pay|怎么(付|支付)|payment method).*\?$", s, re.I) for s in last3_agent)

    if intent in ("INVITE_WITH_FEE","INVITE"):
        price_ph = extract_price_phrase(target_text)
        if price_ph:
            return f"I'm in. {price_ph} works—how do I pay?"
        if not asked_price:
            return "I'm in. What's the price?"
        if not asked_method:
            return "Great. How do I pay?"
        return "Sounds good, send the details here."

    if intent in ("PRICE_TOPIC","PAY_TOPIC"):
        if not asked_price:
            return "I'm interested—what's the price?"
        if not asked_method:
            return "Okay, how do I pay?"
        return "Okay, share the details here."

    if intent == "PRICE_QUOTED":
        if not asked_method:
            return "Okay, how do I pay?"
        return "Sounds good, send the details here."

    if intent == "METHODS":
        method = extract_first_method(target_text) or "a method"
        return f"I can use {method}. Send the details here."

    return None  # 其它交给 LLM 兜底

# ---- Main CLI loop ----
def cli_loop(plan: Dict[str, Any], model: str, flags_cfg: FlagsConfig,
             stop_mode: str = "none", a_needs_legal: bool = True) -> None:
    conv_id = plan["conv_id"]
    persona = plan.get("persona", "consumer")
    objective = plan.get("objective", "先建立信任，再逐步推进了解细节（仅在有明确法规证据时判A）")
    limits = plan.get("limits", {"max_turns": 6, "wait_seconds": 10})
    max_turns = int(limits.get("max_turns", 6))
    guard = plan.get("guard", {})
    ban_phrases = guard.get("ban_phrases", ["验证码", "银行卡", "助记词"])
    stop_on = set(plan.get("stop_on_flags", flags_cfg.allowed_flags))
    lead_id = plan.get("lead_id", "lead_cli_demo")
    run_id = plan.get("run_id")

    print(f"\nChatAgent CLI demo  |  model={model}  |  conv_id={conv_id}  |  rule_version={flags_cfg.rule_version}")
    print("You are TARGET. Type your replies. Commands: /stop to end.\n")

    turns: List[Tuple[str, str]] = []
    orc = ORClient(model=model)

    # ChatPlanIssued + 首句 "hi"
    cp_payload = dict(plan); cp_payload.setdefault("version", PAYLOAD_VERSION)
    print_event(mk_event("ChatPlanIssued", cp_payload, conv_id, lead_id, platform="cli", run_id=run_id))
    next_agent: Optional[str] = "hi"
    question_budget = 1  # 滑动窗口问号预算（每 3 个 agent 回合最多 1 个问句）

    for turn_index in range(1, max_turns + 1):
        # 发送 agent
        if turn_index == 1:
            msg = "hi"
        else:
            last_target = next((t for r,t in reversed(turns) if r=="target"), "")
            msg = policy_reply(turns, last_target)
            if not msg:
                # LLM 兜底
                transcript_txt = build_transcript(turns)
                prop = orc.propose_reply(persona, objective, ban_phrases, flags_cfg.allowed_flags, transcript_txt)
                msg = prop["message"] or "Okay, share a bit more here."

            # 问号预算：过去 2 条 agent + 本条，最多 1 个问号
            recent_agents = [t for r,t in turns if r=="agent"][-2:]
            q_count = sum(1 for s in recent_agents if s.strip().endswith("?"))
            if msg.strip().endswith("?") and q_count >= question_budget:
                msg = strip_question(msg)

            # 语言 + ack
            lang = detect_lang(last_target)
            msg = ensure_ack_prefix(msg, lang)

        safe_agent = sanitize_unicode_str(sanitize(msg, ban_phrases))
        print_event(mk_event("DialogueTurn", {
            "version": PAYLOAD_VERSION,
            "conv_id": conv_id, "role": "agent", "modality": "text", "text": safe_agent
        }, conv_id, lead_id, run_id=run_id))
        turns.append(("agent", safe_agent))
        print(f"AGENT> {safe_agent}")

        # 读取 target（立即做 unicode 清洗）
        target_raw = input("TARGET> ")
        target = sanitize_unicode_str((target_raw or "").strip())
        if target == "/stop":
            print("Stopped by user."); break

        print_event(mk_event("DialogueTurn", {
            "version": PAYLOAD_VERSION,
            "conv_id": conv_id, "role": "target", "modality": "text", "text": target
        }, conv_id, lead_id, run_id=run_id))
        turns.append(("target", target))

        # === Conversation-level triage ===
        transcript_txt = build_transcript(turns)
        tri = orc.triage_conversation(transcript_txt, flags_cfg.allowed_flags)
        model_state   = tri["state"]
        model_risk    = tri["risk"]
        model_breaches= tri["breaches"]
        model_evid    = tri["evidence"]

        local_hits = flags_cfg.detect_local(target)
        taxonomy_hits: List[str] = []
        for fid in model_risk + local_hits:
            if fid in flags_cfg.allowed_flags and fid not in taxonomy_hits:
                taxonomy_hits.append(fid)

        final_state = model_state
        if a_needs_legal and final_state == "A" and not model_breaches:
            final_state = "B"

        print_event(mk_event("ScoreChat", {
            "version": PAYLOAD_VERSION,
            "conv_id": conv_id,
            "verdict": final_state,
            "turn_index": turn_index,
            "rule_version": flags_cfg.rule_version or RULE_VERSION_DEFAULT,
            "basis": {
                "legal_breaches": model_breaches if final_state == "A" else [],
                "risk_signals": taxonomy_hits
            },
            "certainty": "med",
            "model_state_raw": model_state,
            "model_evidence": model_evid
        }, conv_id, lead_id, run_id=run_id))
        print(f"[ScoreChat] verdict={final_state}  breaches={len(model_breaches if final_state=='A' else [])}  risk_signals={taxonomy_hits}")

        # 停止策略
        should_stop = False
        if stop_mode == "taxonomy":
            should_stop = bool(set(taxonomy_hits) & set(stop_on))
        elif stop_mode == "legal":
            should_stop = len(model_breaches) > 0

        if should_stop:
            print_event(mk_event("EvidenceStored", {
                "version": PAYLOAD_VERSION,
                "files": [{"kind":"screenshot","duration_s":0}],
                "note": "stop_on_flags",
                "preview": transcript_txt[:500]
            }, conv_id, lead_id, run_id=run_id))
            print("⚠️  Risk detected — stopping as per stop-mode.")
            break

    # 结束快照
    transcript_txt = build_transcript(turns)
    print_event(mk_event("EvidenceStored", {
        "version": PAYLOAD_VERSION,
        "files": [{"kind":"screenshot","duration_s":0}],
        "note": "on_end_transcript",
        "preview": transcript_txt[:800]
    }, conv_id, lead_id, run_id=run_id))
    print("ChatAgent CLI demo finished.")

# ---- Plan & CLI ----
def load_plan(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {
            "conv_id": f"conv-{ulid()}",
            "persona": "consumer",
            "objective": "顺从推进（先表明愿意→若无价格只问一次→若有价格只问一次怎么付）",
            "entrypoint": {"platform":"cli","contact":{"type":"username","value":"@demo"}},
            "script": ["hi"],  # 首句固定
            "limits": {"max_turns": 6, "wait_seconds": 10},
            "stop_on_flags": DEFAULT_ALLOWED_FLAGS,
            "evidence_snapshot": "each_turn",
            "guard": {"ban_phrases": ["验证码","银行卡","助记词"], "tone":"polite_probe"},
            "idempotencyKey": f"cp_{ulid()}",
            "version": PAYLOAD_VERSION,
            "lead_id": "lead_cli_demo"
        }
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", help="Path to ChatPlan JSON")
    ap.add_argument("--conv-id", help="Override conv_id")
    ap.add_argument("--lead-id", help="Override lead_id")
    ap.add_argument("--run-id", help="Optional run_id")
    ap.add_argument("--model", required=True, help="OpenRouter model, e.g. google/gemini-2.5-flash")
    ap.add_argument("--flags-file", help="Path to flags config (JSON or YAML). Optional.")
    ap.add_argument("--stop-mode", choices=["none","taxonomy","legal"], default="none")
    ap.add_argument("--a-needs-legal", action="store_true",
                    help="Require legal_breaches to allow A; otherwise downgrade to B")
    args = ap.parse_args()

    plan = load_plan(args.plan)
    if args.conv_id: plan["conv_id"] = args.conv_id
    if args.lead_id: plan["lead_id"] = args.lead_id
    if args.run_id:  plan["run_id"]  = args.run_id

    flags_cfg = FlagsConfig.load(args.flags_file)
    cli_loop(plan, model=args.model, flags_cfg=flags_cfg,
             stop_mode=args.stop_mode, a_needs_legal=bool(args.a_needs_legal))

if __name__ == "__main__":
    main()
