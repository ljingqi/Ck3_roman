# -*- coding: utf-8 -*-
r"""极简 requests 替身 —— 仅供离线只读探针/快照工具的导入链通过。

本机可执行解释器只有 codex 运行时自带的 Python 3.12（未装 requests），而
llm.py 顶层 `import requests`。离线工具（tools/tests/snap.py 等）不发网络请求，
故用本替身占位：把 tools/_stub 放进 PYTHONPATH 即可。

用法（PowerShell）：
    $env:PYTHONPATH = 'tools\_stub'
    & tools\py.ps1 tools\tests\snap.py 崔佛 38660 final
"""


class HTTPError(Exception):
    response = None


class RequestException(Exception):
    response = None


ConnectionError = RequestException
Timeout = RequestException
exceptions = RequestException


def _no_net(*_a, **_k):
    raise RuntimeError("requests 替身（tools/_stub）：本工具不发网络请求")


post = _no_net
get = _no_net
request = _no_net
