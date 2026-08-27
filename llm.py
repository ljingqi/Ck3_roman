# -*- coding: utf-8 -*-
"""LLM 调用管线 (自包含, 不依赖 D:\\Journal 任何文件)。

从 Journal 项目的 journal.py 移植核心能力:
  - load_config        : 读取 config.json, 缺省项用默认值
  - log                : 控制台 + logs/journal.log
  - _log_prompt        : 每次发送给模型的 messages 原文写入 logs/prompts.log (超5MB轮转)
  - call_deepseek      : DeepSeek chat/completions 调用 (截断自动翻倍重试 / thinking 关闭 / 退避重试)
  - clean_number_spaces: 汉字与数字之间的空格清理 (提示词侧与输出侧统一)
"""
import datetime
import json
import os
import re
import sys
import threading
import time

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG = {
    # DeepSeek API 配置
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    "deepseek_base_url": "https://api.deepseek.com/chat/completions",
    # CK3 存档目录 (Documents\\Paradox Interactive\\Crusader Kings III\\save games)
    "ck3_user_dir": "",
    "save_dir": "",
    # rakaly.exe 路径 (存档熔化必需)
    "rakaly_path": os.path.join(SCRIPT_DIR, "tools", "rakaly.exe"),
    # 数据/缓存/输出/日志目录
    "data_dir": os.path.join(SCRIPT_DIR, "data"),
    "cache_dir": os.path.join(SCRIPT_DIR, "cache"),
    "output_dir": os.path.join(SCRIPT_DIR, "output"),
    "log_dir": os.path.join(SCRIPT_DIR, "logs"),
    # 监控轮询间隔(秒)
    "poll_interval_seconds": 3600,
    # LLM 生成参数
    "max_tokens": 12800,
    "temperature": 1.1,
    "prompt_log_enabled": True,
    "llm_thinking_disabled": True,
    # 流水线开关: scan 检测到玩家死亡后是否自动生成终传
    "auto_bio_on_death": True,
    # 传记板块结构: lead=首段, mid=中段, tail=尾段 (每篇文章的板块数 = 1 + 是否有 mid + 是否有 tail)
    "bio_sections": ["lead", "mid", "tail"],
}


def load_config(path=None):
    cfg = dict(DEFAULT_CONFIG)
    path = path or os.path.join(SCRIPT_DIR, "config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            for k, v in user_cfg.items():
                if v not in (None, ""):
                    cfg[k] = v
        except Exception as e:
            log(f"警告: 读取 config.json 失败 ({e}), 使用默认配置。")
    # 目录回退
    if not cfg.get("ck3_user_dir"):
        cfg["ck3_user_dir"] = (r"C:\Users\CHINE\Documents\Paradox Interactive"
                               r"\Crusader Kings III")
    if not cfg.get("save_dir"):
        cfg["save_dir"] = os.path.join(cfg["ck3_user_dir"], "save games")
    if not cfg.get("rakaly_path") or not os.path.isfile(cfg.get("rakaly_path")):
        # 兜底: 允许相对 tools 目录
        alt = os.path.join(SCRIPT_DIR, "tools", "rakaly.exe")
        if os.path.isfile(alt):
            cfg["rakaly_path"] = alt
    for key in ("data_dir", "cache_dir", "output_dir", "log_dir"):
        if not cfg.get(key):
            cfg[key] = os.path.join(SCRIPT_DIR, key)
    return cfg


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

_LOG_LOCK = threading.Lock()
_LOG_DIR = None
LOG_FILE = None
PROMPT_LOG = None
PROMPT_LOG_MAX_BYTES = 5 * 1024 * 1024


def _init_log_paths():
    global _LOG_DIR, LOG_FILE, PROMPT_LOG
    try:
        with open(os.path.join(SCRIPT_DIR, "config.json"), encoding="utf-8") as f:
            d = (json.load(f).get("log_dir") or "").strip()
    except Exception:
        d = ""
    _LOG_DIR = d or os.path.join(SCRIPT_DIR, "logs")
    LOG_FILE = os.path.join(_LOG_DIR, "journal.log")
    PROMPT_LOG = os.path.join(_LOG_DIR, "prompts.log")


_init_log_paths()


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with _LOG_LOCK:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def _log_prompt(messages):
    """把每次发送给模型的 messages 原文写入 logs/prompts.log (超 5MB 轮转)。"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(os.path.dirname(PROMPT_LOG), exist_ok=True)
        with _LOG_LOCK:
            if os.path.exists(PROMPT_LOG) and os.path.getsize(PROMPT_LOG) > PROMPT_LOG_MAX_BYTES:
                open(PROMPT_LOG, "w", encoding="utf-8").close()
            with open(PROMPT_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n===== {ts} =====\n")
                for m in messages or []:
                    role = m.get("role", "?") if isinstance(m, dict) else "?"
                    content = m.get("content", "") if isinstance(m, dict) else str(m)
                    f.write(f"--- [{role}] ---\n{content}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 文本规范
# ---------------------------------------------------------------------------

_NUM_CJK_SPACE_RES = [
    re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=\d)"),
    re.compile(r"(?<=\d)\s+(?=[\u4e00-\u9fff])"),
]


def clean_number_spaces(text):
    """去掉汉字与阿拉伯数字之间的空格 (「第 3 街」→「第3街」)。"""
    for r in _NUM_CJK_SPACE_RES:
        text = r.sub("", text or "")
    return text


def clean_prompt_messages(messages):
    """提示词侧数字↔汉字空格清理; 原列表不修改, 返回新列表。"""
    if not messages:
        return messages or []
    cleaned = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            c = clean_number_spaces(c)
        cleaned.append({**m, "content": c})
    return cleaned


def fmt_cn_date(date_str):
    """CK3 日期 '869.2.22' → '869年2月22日'; 非法输入返回原文。"""
    if not date_str:
        return "未知"
    s = str(date_str).strip()
    parts = s.split(".")
    if len(parts) >= 3:
        try:
            y, mo, d = (int(x) for x in parts[:3])
            return f"{y}年{mo}月{d}日"
        except Exception:
            return s
    return s


# ---------------------------------------------------------------------------
# DeepSeek 调用
# ---------------------------------------------------------------------------

def call_deepseek(messages, cfg, retries=3):
    """调用 DeepSeek chat/completions, 返回正文文本。

    - max_tokens 截断时自动翻倍预算重试 (上限 16000);
    - llm_thinking_disabled 时发送 thinking:disabled 关闭思考模式;
    - 失败退避重试 (3s / 6s ...)。
    """
    messages = clean_prompt_messages(messages)
    if cfg.get("prompt_log_enabled", True):
        _log_prompt(messages)
    url = cfg["deepseek_base_url"]
    headers = {
        "Authorization": f"Bearer {cfg['deepseek_api_key']}",
        "Content-Type": "application/json",
    }
    max_tokens = cfg.get("max_tokens", 8000)
    last_err = None
    for i in range(retries):
        payload = {
            "model": cfg.get("deepseek_model", "deepseek-chat"),
            "messages": messages,
            "temperature": cfg.get("temperature", 1.0),
            "max_tokens": max_tokens,
        }
        if cfg.get("llm_thinking_disabled", True):
            payload["thinking"] = {"type": "disabled"}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            content = (choice.get("message") or {}).get("content") or ""
            finish = choice.get("finish_reason")
            if finish == "length":
                if max_tokens >= 16000:
                    log("输出仍被 max_tokens 截断(已达 16000 上限), 返回截断文本")
                    if content.strip():
                        return content
                else:
                    max_tokens = min(max_tokens * 2, 16000)
                    log(f"输出因 max_tokens 不足被截断, 提高预算至 {max_tokens} 重试")
                    continue
            if content.strip():
                return content
            if finish == "stop":
                return content
            last_err = Exception(f"模型返回空内容 (finish_reason={finish})")
        except Exception as e:
            last_err = e
            log(f"DeepSeek 调用失败 (第{i + 1}/{retries}次): {e}")
        if i < retries - 1:
            time.sleep(3 * (i + 1))
    raise last_err if last_err else Exception("生成失败")
