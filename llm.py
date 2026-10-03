# -*- coding: utf-8 -*-
"""Self-contained DeepSeek chat/completions layer: config loading, logging to console
and logs/journal.log with raw-prompt dumps, and Chinese text normalization."""
import contextlib
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
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    "deepseek_base_url": "https://api.deepseek.com/chat/completions",
    # CK3 save directory: Documents\\Paradox Interactive\\Crusader Kings III\\save games
    "ck3_user_dir": "",
    "save_dir": "",
    # CK3 install root (holds game/localization and game/common); empty = auto-discover
    "ck3_game_dir": "",
    # rakaly.exe path (required to melt saves)
    "rakaly_path": os.path.join(SCRIPT_DIR, "tools", "rakaly.exe"),
    "data_dir": os.path.join(SCRIPT_DIR, "data"),
    "cache_dir": os.path.join(SCRIPT_DIR, "cache"),
    "output_dir": os.path.join(SCRIPT_DIR, "output"),
    "log_dir": os.path.join(SCRIPT_DIR, "logs"),
    # poll interval, seconds
    "poll_interval_seconds": 3600,
    "max_tokens": 12800,
    "temperature": 1.1,
    "prompt_log_enabled": True,
    "llm_thinking_disabled": True,
    # pipeline switch: generate the final biography automatically once scan sees the player die
    "auto_bio_on_death": True,
    # carnal_opinions: include the Carnalitas event-opinion family, whose localization
    # text already repeats the sex-memory rendering item by item. Off by default.
    "carnal_opinions": False,
    # llm_max_concurrency: cap on upstream requests in flight. Biography sections are
    # issued one request each in parallel, so the cap keeps `insufficient_system_resource`
    # interruptions down.
    "llm_max_concurrency": 6,
    # biography section layout: lead = opening, mid = middle
    "bio_sections": ["lead", "mid"],
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
    # Directory fallback: derive Documents from the current Windows user, never a hardcoded one
    if not cfg.get("ck3_user_dir"):
        profile = os.environ.get("USERPROFILE", "")
        if profile:
            cfg["ck3_user_dir"] = os.path.join(
                profile, "Documents", "Paradox Interactive", "Crusader Kings III")
    if not cfg.get("save_dir"):
        cfg["save_dir"] = os.path.join(cfg["ck3_user_dir"], "save games")
    if not cfg.get("rakaly_path") or not os.path.isfile(cfg.get("rakaly_path")):
        alt = os.path.join(SCRIPT_DIR, "tools", "rakaly.exe")
        if os.path.isfile(alt):
            cfg["rakaly_path"] = alt
    for key in ("data_dir", "cache_dir", "output_dir", "log_dir"):
        if not cfg.get(key):
            cfg[key] = os.path.join(SCRIPT_DIR, key)
    return cfg


# ---------------------------------- Logging ---------------------------------

_LOG_LOCK = threading.Lock()
_LOG_DIR = None
LOG_FILE = None
PROMPT_LOG = None
PROMPT_LOG_MAX_BYTES = 5 * 1024 * 1024
# detail=True lines go to the log file only, unless config.json sets log_console_detail=true.
DETAIL_CONSOLE = False


def _init_log_paths():
    global _LOG_DIR, LOG_FILE, PROMPT_LOG, DETAIL_CONSOLE
    try:
        with open(os.path.join(SCRIPT_DIR, "config.json"), encoding="utf-8") as f:
            c = json.load(f)
            d = (c.get("log_dir") or "").strip()
            DETAIL_CONSOLE = bool(c.get("log_console_detail", False))
    except Exception:
        d = ""
    _LOG_DIR = d or os.path.join(SCRIPT_DIR, "logs")
    LOG_FILE = os.path.join(_LOG_DIR, "journal.log")
    PROMPT_LOG = os.path.join(_LOG_DIR, "prompts.log")


_init_log_paths()


def log(msg, *, detail=False):
    """Write one log line; always appended to logs/journal.log.

    detail=True marks a high-frequency per-item line, printed to the console only when
    log_console_detail is true in config.json."""
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    if not detail or DETAIL_CONSOLE:
        print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with _LOG_LOCK:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def _log_prompt(messages):
    """Dump the raw messages sent to the model into logs/prompts.log, emptied past 5MB."""
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


# ----------------------------- Text normalization ---------------------------

_NUM_CJK_SPACE_RES = [
    # Only space-like characters are removed; newlines are left alone, as they separate
    # entries.
    re.compile(r"(?<=[\u4e00-\u9fff])[ \t\u3000]+(?=\d)"),
    re.compile(r"(?<=\d)[ \t\u3000]+(?=[\u4e00-\u9fff])"),
]


def clean_number_spaces(text):
    """Remove spaces between CJK characters and ASCII digits."""
    for r in _NUM_CJK_SPACE_RES:
        text = r.sub("", text or "")
    return text


# --- Halfwidth punctuation normalization -------------------------------------
# Assembly templates and the fact layer use fullwidth punctuation, so model-side
# halfwidth drift is normalized back: halfwidth punctuation next to CJK text becomes
# fullwidth, while next to digits or Latin letters it stays as-is
# (3.5 / 1,000 / J.P. / Markdown "1." lists are unaffected).
_ZH_NEIGHBOR = ("\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
                "\u3000-\u303f\uff00-\uffef"
                "\u2018\u2019\u201c\u201d\u2026\u2014")
_ZH_CLASS = f"[{_ZH_NEIGHBOR}]"
_ZH_RE = re.compile(_ZH_CLASS)
_HALF2FULL = {",": "，", ";": "；", ":": "：", "!": "！", "?": "？"}
_PUNCT_SIDE_RES = [
    (re.compile(rf"(?<={_ZH_CLASS}){re.escape(a)}|{re.escape(a)}(?={_ZH_CLASS})"), b)
    for a, b in _HALF2FULL.items()
]
# A period is converted only after a CJK character; after a Latin letter or digit it stays.
_PERIOD_RE = re.compile(rf"(?<={_ZH_CLASS})\.")


def _pair_halfwidth_quotes(line):
    """Pair halfwidth double quotes within a line into “”; the line is returned unchanged
    unless the count is even and every quote touches CJK text or CJK punctuation, which
    keeps quotes inside JSON fragments or English abbreviations untouched."""
    idx = [i for i, ch in enumerate(line) if ch == '"']
    if not idx or len(idx) % 2:
        return line
    for i in idx:
        before = line[i - 1] if i else ""
        after = line[i + 1] if i + 1 < len(line) else ""
        if not (_ZH_RE.match(before) or _ZH_RE.match(after)):
            return line
    out, opening = [], True
    for ch in line:
        if ch == '"':
            out.append("“" if opening else "”")
            opening = not opening
        else:
            out.append(ch)
    return "".join(out)


def normalize_zh_punct(text):
    """Normalize halfwidth punctuation in Chinese text to fullwidth; idempotent.
    , ; : ! ? and a sentence-final . become fullwidth, halfwidth double quotes are
    paired per line, and punctuation beside digits or Latin text is untouched. Quotes
    are paired first so a period right after a closing quote is still caught. Applied
    on the output side (sections/summary/final) and on the prompt side."""
    if not text:
        return text
    out = text
    if '"' in out:
        out = "\n".join(_pair_halfwidth_quotes(ln) for ln in out.split("\n"))
    for pat, rep in _PUNCT_SIDE_RES:
        out = pat.sub(rep, out)
    out = _PERIOD_RE.sub("。", out)
    return out


def clean_prompt_messages(messages):
    """Prompt-side cleanup: digit/CJK space removal plus halfwidth punctuation
    normalization; returns a new list, the input list is left unchanged."""
    if not messages:
        return messages or []
    cleaned = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            c = normalize_zh_punct(clean_number_spaces(c))
        cleaned.append({**m, "content": c})
    return cleaned


def fmt_cn_date(date_str):
    """Render a CK3 date such as '869.2.22' as a Chinese date string; illegal input is
    returned as-is. January 1 renders as the year alone: the game writes unknown dates
    and yearly snapshot dates as Jan 1, so month and day carry no information there."""
    if not date_str:
        return "未知"
    s = str(date_str).strip()
    parts = s.split(".")
    if len(parts) >= 3:
        try:
            y, mo, d = (int(x) for x in parts[:3])
            if mo == 1 and d == 1:
                return f"{y}年"
            return f"{y}年{mo}月{d}日"
        except Exception:
            return s
    return s


# -------------------------------- DeepSeek call -----------------------------

def _usage_line(usage, messages, finish=None):
    """One-line usage summary (per the DeepSeek context disk-cache docs). A cache hit
    costs 1/50 of a miss, so misses are the real cost and acceptance metric; the
    finish_reason is appended (stop/length/content_filter/tool_calls/
    insufficient_system_resource/aborted) to tell a clean finish from an interruption."""
    u = usage if isinstance(usage, dict) else {}
    hit = u.get("prompt_cache_hit_tokens") or 0
    miss = u.get("prompt_cache_miss_tokens") or 0
    inp = u.get("prompt_tokens") or (hit + miss)
    out = u.get("completion_tokens")
    chars = sum(len(m.get("content") or "") for m in (messages or [])
                if isinstance(m, dict))
    tail = f" | 收尾{finish}" if finish is not None else ""
    return (f"token: 输入{inp} = 命中{hit} + 未命中{miss}"
            f" | 输出{out if out is not None else '?'} | 字符{chars}"
            f" (命中率{hit * 100 // inp if inp else 0}%){tail}")


# Wall-clock budget for one call_deepseek call, all attempts combined; retrying stops past it.
CALL_BUDGET_SECONDS = 360

# Wall-clock cap on a single attempt: requests' timeout covers only connect and one silent
# socket read, so an upstream that trickles or holds the connection open is cut off here,
# while the body is streamed.
ATTEMPT_DEADLINE_SECONDS = 240
# (connect timeout, per-read socket timeout) — socket-level fallback only.
_SOCKET_TIMEOUT = (15, 120)
# Official wording for an upstream queue timeout (transient capacity event: back off and retry).
_QUEUE_TIMEOUT_RE = re.compile(r"timeout limit|unable to start processing", re.I)


def _body_head(body_bytes, limit=500):
    """Response body bytes -> single-line summary for logs (same shape as _resp_head)."""
    try:
        txt = (body_bytes or b"").decode("utf-8", "replace")
    except Exception:
        txt = ""
    return " ".join(txt.split())[:limit]


def _read_body(resp, t_try, deadline=None):
    """Stream the response body, aborting and raising once the per-attempt wall-clock
    deadline (ATTEMPT_DEADLINE_SECONDS) is exceeded. Returns bytes; an upstream that
    answers 200 with an error body is read through the same path."""
    dl = ATTEMPT_DEADLINE_SECONDS if deadline is None else deadline
    chunks = []
    for chunk in resp.iter_content(65536):
        if not chunk:
            continue
        chunks.append(chunk)
        if time.monotonic() - t_try > dl:
            try:
                resp.close()
            except Exception:
                pass
            raise RuntimeError(
                f"单次尝试超过墙钟上限 {dl}s (上游未在时限内回完响应体), 已断开")
    return b"".join(chunks)


def _resp_head(resp, limit=500):
    """Truncated single-line response body summary, as evidence when upstream returns a
    non-OpenAI shape."""
    try:
        txt = resp.text or ""
    except Exception:
        txt = ""
    return " ".join(txt.split())[:limit]


# Concurrency cap, read from config.json once per process; 0 or negative = unlimited.
# _LIMIT_LOCK guards the one-time creation of the semaphore.
_LIMIT_LOCK = threading.Lock()
_LIMIT_N = None
_LIMIT_SEM = None


def _limiter():
    global _LIMIT_N, _LIMIT_SEM
    n = _LIMIT_N
    if n is None:
        try:
            with open(os.path.join(SCRIPT_DIR, "config.json"), encoding="utf-8") as f:
                n = int((json.load(f) or {}).get("llm_max_concurrency")
                        or DEFAULT_CONFIG["llm_max_concurrency"])
        except Exception:
            n = DEFAULT_CONFIG["llm_max_concurrency"]
        _LIMIT_N = n
    if n <= 0:
        return contextlib.nullcontext()
    if _LIMIT_SEM is None:
        with _LIMIT_LOCK:
            if _LIMIT_SEM is None:
                _LIMIT_SEM = threading.BoundedSemaphore(n)
    return _LIMIT_SEM


def call_deepseek(messages, cfg, retries=3):
    """Call DeepSeek chat/completions and return the assistant message text; retries with
    a doubled max_tokens budget on truncation and gives up after CALL_BUDGET_SECONDS."""
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
    t_start = time.monotonic()
    # The whole call, retries included, holds one slot; concurrent section requests queue.
    with _limiter():
      for i in range(retries):
          t_try = time.monotonic()
          payload = {
              "model": cfg.get("deepseek_model", "deepseek-chat"),
              "messages": messages,
              "temperature": cfg.get("temperature", 1.0),
              "max_tokens": max_tokens,
          }
          if cfg.get("llm_thinking_disabled", True):
              payload["thinking"] = {"type": "disabled"}
          try:
              resp = requests.post(url, json=payload, headers=headers,
                                   timeout=_SOCKET_TIMEOUT, stream=True)
              resp.raise_for_status()
              body_bytes = _read_body(resp, t_try)
              try:
                  data = json.loads(body_bytes.decode("utf-8", "replace"))
              except Exception as e:
                  body = _body_head(body_bytes)
                  log(f"上游响应非 JSON (status={resp.status_code}, "
                      f"耗时{time.monotonic() - t_try:.0f}s): {body}")
                  raise RuntimeError(
                      f"上游响应非 JSON (status={resp.status_code}, {e}): {body[:200]}")
              if not isinstance(data, dict) or not data.get("choices"):
                  body = _body_head(body_bytes)
                  msg = ""
                  if isinstance(data, dict):
                      _err = data.get("error")
                      msg = str(_err.get("message") or "") if isinstance(_err, dict) \
                          else (str(_err) if _err else "")
                  if _QUEUE_TIMEOUT_RE.search(msg or body):
                      # Queue timeout = transient capacity event: back off and retry, not fatal.
                      last_err = RuntimeError(
                          f"上游排队超时 (status={resp.status_code}, "
                          f"耗时{time.monotonic() - t_try:.0f}s): "
                          f"{(msg or body)[:200]}")
                      log(f"上游排队超时, 退避重试 (耗时"
                          f"{time.monotonic() - t_try:.0f}s): {(msg or body)[:200]}")
                  else:
                      log(f"上游返回非 OpenAI 形状 (status={resp.status_code}, "
                          f"耗时{time.monotonic() - t_try:.0f}s): {body}")
                      raise RuntimeError(
                          f"上游返回非 OpenAI 形状 (status={resp.status_code}): "
                          f"{body[:200]}")
              else:
                  choice = data["choices"][0]
                  content = (choice.get("message") or {}).get("content") or ""
                  finish = choice.get("finish_reason")
                  log(_usage_line(data.get("usage"), messages, finish))
                  if finish == "length":
                      if max_tokens >= 16000:
                          log("输出仍被 max_tokens 截断(已达 16000 上限), 返回截断文本")
                          if content.strip():
                              return content
                      else:
                          max_tokens = min(max_tokens * 2, 16000)
                          log(f"输出因 max_tokens 不足被截断, 提高预算至 {max_tokens} 重试")
                          continue
                  elif finish and finish != "stop":
                      # Non-stop finish reasons (content_filter / insufficient_system_resource /
                      # aborted) can carry partial content, so treat them as incomplete: retry,
                      # then let the pipeline mark the section failed.
                      raise RuntimeError(
                          f"生成被上游中断 (finish_reason={finish}, "
                          f"输出{(data.get('usage') or {}).get('completion_tokens')} token) "
                          f"— 内容不完整, 按未完成处理")
                  if content.strip():
                      return content
                  if finish == "stop":
                      return content
                  last_err = Exception(f"模型返回空内容 (finish_reason={finish})")
          except Exception as e:
              last_err = e
              if isinstance(e, requests.HTTPError) and e.response is not None \
                      and e.response.status_code == 400:
                  # 400 = client error (context overflow / bad parameters): resending the same
                  # payload always fails and burns tokens
                  body = _resp_head(e.response, 300)
                  log(f"DeepSeek 调用失败 (400, 不再重试, "
                      f"耗时{time.monotonic() - t_try:.0f}s): {e} | {body}")
                  raise
              if isinstance(e, RuntimeError) and "非 OpenAI 形状" in str(e):
                  # A malformed-shape answer is a definite reply: resending cannot change it
                  log("上游答复非 OpenAI 形状, 停止重试")
                  raise
              log(f"DeepSeek 调用失败 (第{i + 1}/{retries}次, "
                  f"耗时{time.monotonic() - t_try:.0f}s): {e}")
          if i < retries - 1:
              if time.monotonic() - t_start > CALL_BUDGET_SECONDS:
                  log(f"调用失败累计超过 {CALL_BUDGET_SECONDS}s 预算, 停止重试")
                  break
              time.sleep(3 * (i + 1))
    raise last_err if last_err else Exception("生成失败")
