# -*- coding: utf-8 -*-
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oneresearch.config as c

SETTINGS = {
    "model": {"name": "glm-5.3-oc", "baseUrl": "https://x.example/v2/cp"},
    "env": {"CTYUN_EAI_API_KEY": "sk-test-123"},
    "modelProviders": {"openai": [
        {"id": "deepseek-v4-flash-0731-oc", "baseUrl": "https://x.example/v2/cp",
         "envKey": "CTYUN_EAI_API_KEY"},
        {"id": "glm-5.3-oc", "baseUrl": "https://x.example/v2/cp",
         "envKey": "CTYUN_EAI_API_KEY"},
    ]},
}


def _setup(tmp_path, monkeypatch, config_json=None):
    sf = tmp_path / "settings.json"
    sf.write_text(json.dumps(SETTINGS), encoding="utf-8")
    monkeypatch.setattr(c, "QWEN_SETTINGS_PATH", sf)
    cfgf = tmp_path / "config.json"
    if config_json is not None:
        cfgf.write_text(json.dumps(config_json), encoding="utf-8")
    monkeypatch.setattr(c, "CONFIG_PATH", cfgf)


def test_discover_llm_from_qwen_settings(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    found = c._discover_llm()
    assert found["base_url"] == "https://x.example/v2/cp"
    assert found["model"] == "glm-5.3-oc"
    assert found["api_key"] == "sk-test-123"


def test_load_config_autodiscovers(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = c.load_config()
    assert c.llm_configured(cfg)
    assert cfg["llm"]["model"] == "glm-5.3-oc"


def test_load_config_low_value_model_override(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"llm": {"model": "deepseek-v4-flash-0731-oc"}})
    cfg = c.load_config()
    assert cfg["llm"]["model"] == "deepseek-v4-flash-0731-oc"
    assert cfg["llm"]["base_url"] == "https://x.example/v2/cp"
    assert cfg["llm"]["api_key"] == "sk-test-123"


def test_load_config_llm_disabled(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"llm": {"enabled": False}})
    cfg = c.load_config()
    assert not c.llm_configured(cfg)
    assert cfg["llm"]["base_url"] == ""


def test_discover_no_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "QWEN_SETTINGS_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(c, "CONFIG_PATH", tmp_path / "missing.json")
    assert c._discover_llm() == {}
    cfg = c.load_config()
    assert not c.llm_configured(cfg)
