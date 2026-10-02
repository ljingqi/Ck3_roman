# -*- coding: utf-8 -*-
"""LLM 调用管线 (自包含, 不依赖 <另一项目> 任何文件)。

从 Journal 项目的 journal.py 移植核心能力:
  - load_config        : 读取 config.json, 缺省项用默认值
  - log                : 控制台 + logs/journal.log
  - _log_prompt        : 每次发送给模型的 messages 原文写入 logs/prompts.log (超5MB轮转)
  - call_deepseek      : DeepSeek chat/completions 调用 (截断自动翻倍重试 / thinking 关闭 / 退避重试)
  - clean_number_spaces: 汉字与数字之间的空格清理 (提示词侧与输出侧统一)
"""
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
    # DeepSeek API 配置
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    "deepseek_base_url": "https://api.deepseek.com/chat/completions",
    # CK3 存档目录 (Documents\\Paradox Interactive\\Crusader Kings III\\save games)
    "ck3_user_dir": "",
    "save_dir": "",
    # CK3 游戏本体根目录 (含 game/localization 与 game/common; 空则自动发现)
    "ck3_game_dir": "",
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
    # v41: Carnalitas 事件好感族 (carnal_opinions) 是否进事实面。
    # 该族的本地化文案本身就是一句「谁视谁为：曾强奸我／曾强奸家庭成员」式评断,
    # 与性事记忆渲染的「强迫之事」逐条重复 (无地点、无行为、无具体日),
    # 只增提示词长度。默认关闭; 需要在《阴私录》里看到这类评断时置 true。
    "carnal_opinions": False,
    # v73: 并发上限 —— 传记的板块期是「一篇一请求」并行发出的
    # (`biography.generate_biography` 的 ThreadPool), 六篇以上的传主可同时打出
    # 二十余个请求; 给上游一个上限, 免得 `insufficient_system_resource` 中断变多。
    "llm_max_concurrency": 6,
    # 传记板块结构: lead=首段, mid=中段 (v11: 尾段评曰已删, 太史公曰只留总纲)
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
    # 目录回退: 按当前 Windows 用户动态取 Documents (不写死旧机器用户名)
    if not cfg.get("ck3_user_dir"):
        profile = os.environ.get("USERPROFILE", "")
        if profile:
            cfg["ck3_user_dir"] = os.path.join(
                profile, "Documents", "Paradox Interactive", "Crusader Kings III")
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
# v51: 高频明细行 (逐份归档尺寸、逐角色回溯、逐角色存档) 默认只进日志文件,
# 控制台留出真正需要盯的行; config.json 置 log_console_detail=true 可全量打印。
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
    """写一行日志: 一律落 logs/journal.log。

    detail=True 表示高频明细行 (逐份/逐人粒度) —— 默认不打印到控制台;
    config.json 的 log_console_detail 置 true 时与普通行一样打印。"""
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
    # 只删空格类字符 (半角/全角空格、制表符), 不动换行——
    # 否则「营力209\n妻室：…」的换行会被当空格删掉 (实测 22:56 提示词漏换行根因)。
    re.compile(r"(?<=[\u4e00-\u9fff])[ \t\u3000]+(?=\d)"),
    re.compile(r"(?<=\d)[ \t\u3000]+(?=[\u4e00-\u9fff])"),
]


def clean_number_spaces(text):
    """去掉汉字与阿拉伯数字之间的空格 (「第 3 街」→「第3街」)。"""
    for r in _NUM_CJK_SPACE_RES:
        text = r.sub("", text or "")
    return text


# --- v51: 半角标点归正 -------------------------------------------------------
# 组装侧模板与事实层一律用全角标点, 模型偶有整篇半角漂移 (2026-09-17 沙蒂永终传
# 《阴私录》一篇 80 处半角逗号/冒号/分号, 其余五篇全 0)。凡**与汉字或中文标点
# 相邻**的半角标点一律改全角; 数字与拉丁字母旁的半角标点原样保留
# (3.5 / 1,000 / J.P. / Markdown 有序列表 1. 皆不受影响)。
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
# 句点只看**前一侧**: 汉字/中文标点后的 . 是句号; 「J.P.」「3.5」前一侧是
# 拉丁字母或数字, 原样。
_PERIOD_RE = re.compile(rf"(?<={_ZH_CLASS})\.")


def _pair_halfwidth_quotes(line):
    """行内半角双引号按奇偶配成 “”; 不满足条件时原样返回。

    条件 (缺一不动): 个数为偶数, 且**每一个**半角引号都紧贴汉字/中文标点 ——
    这样 JSON 片段、英文缩写里的半角引号不会被误配对, 而「他说"好",再来」
    「可"知情"与"握柄"」这类中文引号照改。"""
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
    """中文文本的半角标点归正 (v51, 幂等)。

    改 , ; : ! ? 与句末 . 为全角, 半角双引号按行配对成 “”; 数字/拉丁文旁的
    半角标点保持原样。引号配对先做 —— 这样「闷响:…折断".」里紧贴右引号的
    半角句点也能认出来。出稿侧 (板块/总纲/终稿) 与提示词侧
    (clean_prompt_messages) 各过一遍 —— 出稿侧保证成品干净, 提示词侧保证模型
    只见一套标点范例。"""
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
    """提示词侧规整: 数字↔汉字空格清理 + 半角标点归正 (v51);
    原列表不修改, 返回新列表。"""
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
    """CK3 日期 '869.2.22' → '869年2月22日'; 非法输入返回原文。
    v26: 1月1日只留年份 — 游戏把「出生日期不详」写成 1月1日 (只知道年份),
    年度存档快照日也一律是 1月1日; 该日的月/日不含信息, 一律渲染成 'NNNN年'。"""
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


# ---------------------------------------------------------------------------
# DeepSeek 调用
# ---------------------------------------------------------------------------

def _usage_line(usage, messages, finish=None):
    """v27: 缓存用量单行 (口径见 DeepSeek 上下文硬盘缓存文档)。
    命中 token 单价是未命中的 1/50, 因此「未命中」才是真实成本与验收指标。
    v71: 末尾附带 `finish_reason` —— 官方取值 stop/length/content_filter/
    tool_calls/insufficient_system_resource/aborted; 从日志即可判「这次收尾是否正常」
    (旧日志只记 usage, 中断的响应与正常收尾在事后无从分辨)。"""
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


# v39: 单次 call_deepseek 的墙钟预算 (三次尝试合计)。上游挂死时逐次 timeout
# 叠加会把一轮生成拖成几十分钟 (2026-09-14 诺兰实测: 两次生成各白耗 45 分钟),
# 超出预算即停止重试, 把失败尽快交回流水线。
CALL_BUDGET_SECONDS = 360

# v89 (问题1, 用户 2026-10-02 拍板): **单次尝试的墙钟上限**。
# 起因: 2026-10-01 21:32:59 洪氏2 洪天贵福第 1 个十年传记的总纲请求 (全文仅 56 行)
# 被上游排队, 连接挂满 **901 秒**后才回 200 + `{"error":{"message":"We were unable to
# start processing your request within the 900-second timeout limit…"}}`; 而
# `requests` 的 `timeout` 只约束**连接**与**单次 socket 读静默**, 管不住"上游持续
# 涓流/保持连接"这种情形 —— 于是一次尝试白耗 15 分钟, `CALL_BUDGET_SECONDS` 又是
# 失败**之后**才检查, 整篇传记就此卡死 (logs/journal.log:19078)。
# 现改为**流式读取 + 自建总时限**: 无论静默还是涓流, 到点即断。
ATTEMPT_DEADLINE_SECONDS = 240
# (连接超时, 单次 socket 读静默超时) —— socket 层兜底; 总时限由上面那条把关。
_SOCKET_TIMEOUT = (15, 120)
# 上游**排队超时**的官方文案 (瞬时容量事件, 应退避重试而非判死)。
_QUEUE_TIMEOUT_RE = re.compile(r"timeout limit|unable to start processing", re.I)


def _body_head(body_bytes, limit=500):
    """响应体 bytes → 单行摘要 (供日志; 与 `_resp_head` 同形)。"""
    try:
        txt = (body_bytes or b"").decode("utf-8", "replace")
    except Exception:
        txt = ""
    return " ".join(txt.split())[:limit]


def _read_body(resp, t_try, deadline=None):
    """流式读完响应体, 超过**单次尝试墙钟上限**即断连接并抛出 (v89 问题1)。

    返回 bytes。上游只回错误体时同样走这条路 (200 + error 体)。"""
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
    """响应体摘要 (单行, 截断) — 上游返回非 OpenAI 形状时留证用。"""
    try:
        txt = resp.text or ""
    except Exception:
        txt = ""
    return " ".join(txt.split())[:limit]


# v73: 并发上限 (档案期一次读 config.json 定死) —— 上游同时收到的请求数上限。
# 0 或负值 = 不限 (旧口径)。`_LIMIT_LOCK` 只在首次建闸门时用一次。
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
    """调用 DeepSeek chat/completions, 返回正文文本。

    - max_tokens 截断时自动翻倍预算重试 (上限 16000);
    - v71: 其余中断型收尾 (content_filter / insufficient_system_resource /
      aborted) 按未完成处理 (重试, 三次皆中断则抛错) —— 这几种官方都会返回
      部分内容, 旧代码只防 length, 半截正文会被静默当成功收下;
      每次调用的 finish_reason 随 usage 一并落日志;
    - llm_thinking_disabled 时发送 thinking:disabled 关闭思考模式;
    - 失败退避重试 (3s / 6s ...);
    - v27: 每次调用把 usage (缓存命中/未命中 token) 落日志, 供上下文瘦身验收;
    - v39: 每次尝试落「耗时Ns」; 上游 200 返回非 OpenAI 形状 (无 choices,
      网关/中转的 error 体) 时不再重发同一 payload —— 直接落 status 与响应体
      摘要并抛可读异常 (旧行为只抛裸 KeyError: 'choices', 根因无从查证);
      多次尝试合计超出 CALL_BUDGET_SECONDS 即停。
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
    t_start = time.monotonic()
    # v73: 并发上限 —— 整个调用 (含重试) 占一个名额, 并发的板块请求各自排队
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
                      # v89 (问题1): 上游排队超时 = 瞬时容量事件 (排队 900s 未开始处理),
                      # 官方文案就是 "Please try again later" —— 退避重试, 不判死。
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
                      # v71: 上游中断 (content_filter / insufficient_system_resource /
                      # aborted 都会返回**部分内容**) —— 旧代码只防 length, 这几种一律
                      # 当成功收下, 半截正文于是写进成稿 (板块末尾落在开括号上, 见
                      # docs/调研_v71_姓名倒置与孤立括号.md)。此处按未完成处理: 重试;
                      # 三次都中断则抛出, 由流水线把该板块标成「生成失败」等待重跑。
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
                  # 400 = 客户端错误 (上下文超限/参数非法): 同一 payload 重试必败且烧 token
                  body = _resp_head(e.response, 300)
                  log(f"DeepSeek 调用失败 (400, 不再重试, "
                      f"耗时{time.monotonic() - t_try:.0f}s): {e} | {body}")
                  raise
              if isinstance(e, RuntimeError) and "非 OpenAI 形状" in str(e):
                  # 形状错误是上游/网关给出的确定答复: 同一 payload 重发不会有别的结果
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
