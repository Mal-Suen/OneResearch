# -*- coding: utf-8 -*-
"""配置加载：config.json ＋ 环境变量覆盖＋代理在线探测。"""
import copy
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
QWEN_SETTINGS_PATH = Path.home() / ".qwen" / "settings.json"


def _discover_llm() -> dict:
    """从 Qwen Code 的 settings.json 自动发现当前激活模型（端点＋密钥＋模型名）。
    内部 LLM 通道默认复用 Qwen Code 正在用的模型，不要求用户另配任何 key。"""
    try:
        data = json.loads(QWEN_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    model = data.get("model") or {}
    name = str(model.get("name") or "").strip()
    if not name:
        return {}
    base_url = str(model.get("baseUrl") or "").strip()
    env_key = ""
    for providers in (data.get("modelProviders") or {}).values():
        if not isinstance(providers, list):
            continue
        for p in providers:
            if isinstance(p, dict) and p.get("id") == name:
                if not base_url:
                    base_url = str(p.get("baseUrl") or "").strip()
                env_key = str(p.get("envKey") or "")
                break
        if env_key:
            break
    api_key = ""
    if env_key:
        api_key = str((data.get("env") or {}).get(env_key)
                      or os.environ.get(env_key) or "")
    if not (base_url and api_key):
        return {}
    return {"base_url": base_url, "api_key": api_key, "model": name}

DEFAULTS = {
    "proxy": "http://127.0.0.1:7890",
    "search": {
        "engines": ["duckduckgo", "baidu"],
        "max_results_per_engine": 8,
        "timeout": 15,
    },
    "fetch": {
        "max_concurrent": 6,
        "per_page_timeout": 12,
        "max_bytes_per_page": 2000000,
        "deadline_seconds": 55,
    },
    "output": {
        "max_report_chars": 14000,
        "per_source_chars": 1800,
        "max_sources": 8,
    },
    "llm": {"enabled": True, "base_url": "", "api_key": "", "model": ""},
    "doubao": {"api_key": "", "version": "global"},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg = _deep_merge(cfg, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    env = os.environ
    if env.get("ONERESEARCH_PROXY"):
        cfg["proxy"] = env["ONERESEARCH_PROXY"]
    for key, var in (("base_url", "ONERESEARCH_LLM_BASE_URL"),
                     ("api_key", "ONERESEARCH_LLM_API_KEY"),
                     ("model", "ONERESEARCH_LLM_MODEL")):
        if env.get(var):
            cfg["llm"][key] = env[var]
    if env.get("ONERESEARCH_DOUBAO_API_KEY"):
        cfg["doubao"]["api_key"] = env["ONERESEARCH_DOUBAO_API_KEY"]
    llm = cfg["llm"]
    if not llm.get("enabled", True):
        cfg["llm"] = {"enabled": False, "base_url": "", "api_key": "", "model": ""}
    elif not (llm.get("base_url") and llm.get("api_key")):
        found = _discover_llm()
        if found:
            llm["base_url"] = llm.get("base_url") or found["base_url"]
            llm["api_key"] = llm.get("api_key") or found["api_key"]
            llm["model"] = llm.get("model") or found["model"]
    return cfg


def proxy_alive(proxy_url: str, timeout: float = 1.5) -> bool:
    """探测代理端口是否在线（默认 Clash Verge 127.0.0.1:7890）。"""
    if not proxy_url:
        return False
    try:
        p = urlparse(proxy_url)
        host = p.hostname or "127.0.0.1"
        port = p.port or (443 if p.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def llm_configured(cfg: dict) -> bool:
    llm = cfg.get("llm") or {}
    if not llm.get("enabled", True):
        return False
    return bool(llm.get("base_url") and llm.get("api_key") and llm.get("model"))
