#!/usr/bin/env python3
"""
Provider-agnostic LLM adapter for the C4C homework solver.

Design constraint discovered on the target machine: there is NO domestic-LLM
credential, no local model server (checked ports 11434 / 1234 / 8000 / 8080 /
5000: all refused), and outbound HTTPS to dashscope / moonshot / deepseek is
reachable but unauthenticated (401). So a solver that *depends* on an LLM would
be dead on arrival here.

Therefore the architecture is: deterministic SymPy first, LLM as an OPTIONAL
second opinion. This module exposes a single interface and degrades to
"offline" with a machine-readable reason instead of raising. Every solution
record carries `backend` so a reader can tell which path produced it -- the
pipeline never labels a SymPy answer as an LLM answer.

Provider matrix (all OpenAI-compatible /v1/chat/completions unless noted):
    qwen      -> https://dashscope.aliyuncs.com/compatible-mode/v1   env DASHSCOPE_API_KEY
    kimi      -> https://api.moonshot.cn/v1                          env MOONSHOT_API_KEY
    deepseek  -> https://api.deepseek.com/v1                         env DEEPSEEK_API_KEY
    openai    -> https://api.openai.com/v1                           env OPENAI_API_KEY

Only ASCII source: Chinese strings are \\uXXXX escapes (see render_html_pdf.py
header for why).

Usage:
    python llm_backend.py status            # print JSON capability report
    python llm_backend.py ask "prompt"      # one-shot call (never fabricates)
    python llm_backend.py check "sympy expr"  # verify an expression parses
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

PROVIDERS = {
    "qwen": {
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_env": ["DASHSCOPE_API_KEY", "C4C_LLM_API_KEY", "QWEN_API_KEY"],
        "model": "qwen-plus",
    },
    "kimi": {
        "base": "https://api.moonshot.cn/v1",
        "key_env": ["MOONSHOT_API_KEY", "C4C_LLM_API_KEY", "KIMI_API_KEY"],
        "model": "moonshot-v1-8k",
    },
    "deepseek": {
        "base": "https://api.deepseek.com/v1",
        "key_env": ["DEEPSEEK_API_KEY", "C4C_LLM_API_KEY"],
        "model": "deepseek-chat",
    },
    "openai": {
        "base": "https://api.openai.com/v1",
        "key_env": ["OPENAI_API_KEY", "C4C_LLM_API_KEY"],
        "model": "gpt-4o-mini",
    },
}


def _pick_provider():
    want = (os.environ.get("C4C_LLM_PROVIDER") or "auto").strip().lower()
    if want not in ("auto", ""):
        return want
    for name in ("qwen", "kimi", "deepseek", "openai"):
        for env in PROVIDERS[name]["key_env"]:
            if os.environ.get(env):
                return name
    return None


def status():
    name = _pick_provider()
    report = {"provider": name, "available": False, "reason": "", "model": None,
              "base": None, "key_env_present": None, "mode": "offline-deterministic"}
    if name is None:
        report["reason"] = "no provider selected and no *_API_KEY env var present"
        return report
    if name not in PROVIDERS:
        report["reason"] = "unknown provider '%s' (expected qwen/kimi/deepseek/openai)" % name
        return report
    cfg = PROVIDERS[name]
    key, used_env = None, None
    for env in cfg["key_env"]:
        if os.environ.get(env):
            key, used_env = os.environ[env].strip(), env
            break
    report["model"] = os.environ.get("C4C_LLM_MODEL") or cfg["model"]
    report["base"] = os.environ.get("C4C_LLM_BASE_URL") or cfg["base"]
    if not key:
        report["reason"] = "provider '%s' selected but none of %s is set" % (name, cfg["key_env"])
        return report
    report.update({"available": True, "reason": "key found in %s" % used_env,
                   "key_env_present": used_env, "mode": "llm-assisted"})
    return report


def chat(prompt, system=None, temperature=0.0, timeout=90, max_tokens=1200):
    """Return (text, meta). Raises RuntimeError if no provider is usable."""
    st = status()
    if not st["available"]:
        raise RuntimeError("LLM unavailable: " + st["reason"])
    key = None
    for env in PROVIDERS[st["provider"]]["key_env"]:
        if os.environ.get(env):
            key = os.environ[env].strip()
            break
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"model": st["model"], "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}).encode("utf-8")
    req = urllib.request.Request(
        st["base"].rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("HTTP %s from %s: %s" % (exc.code, st["base"],
                                                   exc.read().decode("utf-8", "replace")[:200]))
    text = data["choices"][0]["message"]["content"]
    meta = {"provider": st["provider"], "model": st["model"],
            "usage": data.get("usage", {})}
    return text, meta


CHECK_SNIPPET = r"""
import json, sys
import sympy
expr = sys.stdin.read()
try:
    parsed = sympy.sympify(expr, evaluate=True)
    free = sorted(str(s) for s in parsed.free_symbols)
    print(json.dumps({"ok": True, "srepr": sympy.srepr(parsed)[:400],
                      "free_symbols": free, "is_number": parsed.is_number}))
except Exception as exc:
    print(json.dumps({"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:200]}))
"""


def verify_expr(expr, timeout=30):
    """Ask a fresh SymPy process whether `expr` parses. Isolated on purpose:
    an LLM-proposed expression must never be evaluated in our own process."""
    try:
        proc = subprocess.run([sys.executable, "-c", CHECK_SNIPPET], input=(expr or "").encode("utf-8"),
                              capture_output=True, timeout=timeout)
        out = proc.stdout.decode("utf-8", "replace").strip()
        return json.loads(out) if out else {"ok": False, "error": "empty output"}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:200]}


def main(argv):
    if len(argv) < 2:
        print(json.dumps(status(), ensure_ascii=True, indent=2))
        return 0
    cmd = argv[1]
    if cmd == "status":
        print(json.dumps(status(), ensure_ascii=True, indent=2))
        return 0
    if cmd == "check":
        print(json.dumps(verify_expr(argv[2] if len(argv) > 2 else ""), ensure_ascii=True))
        return 0
    if cmd == "ask":
        try:
            text, meta = chat(argv[2] if len(argv) > 2 else "")
        except RuntimeError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
            return 2
        print(json.dumps({"ok": True, "text": text, "meta": meta}, ensure_ascii=True))
        return 0
    print("unknown command: " + cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
