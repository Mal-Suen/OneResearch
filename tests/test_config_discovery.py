# -*- coding: utf-8 -*-
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oneresearch.config as c

SETTINGS = {
    "model": {"name": "model-a", "baseUrl": "https://api.example.test/v2"},
    "env": {"TEST_PROVIDER_KEY": "sk-test-123"},
    "modelProviders": {"openai": [
        {"id": "budget-model-b", "baseUrl": "https://api.example.test/v2",
         "envKey": "TEST_PROVIDER_KEY"},
        {"id": "model-a", "baseUrl": "https://api.example.test/v2",
         "envKey": "TEST_PROVIDER_KEY"},
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
    assert found["base_url"] == "https://api.example.test/v2"
    assert found["model"] == "model-a"
    assert found["api_key"] == "sk-test-123"


def test_load_config_autodiscovers(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = c.load_config()
    assert c.llm_configured(cfg)
    assert cfg["llm"]["model"] == "model-a"


def test_load_config_low_value_model_override(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"llm": {"model": "budget-model-b"}})
    cfg = c.load_config()
    assert cfg["llm"]["model"] == "budget-model-b"
    assert cfg["llm"]["base_url"] == "https://api.example.test/v2"
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
