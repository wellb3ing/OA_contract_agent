import os
import pytest
from contract_agent.config import load_config

def test_load_config_returns_dict(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("database:\n  host: testhost\nocr:\n  provider: baidu\n")
    config = load_config(str(cfg_file))
    assert isinstance(config, dict)
    assert config["database"]["host"] == "testhost"
    assert config["ocr"]["provider"] == "baidu"

def test_load_config_via_env_var(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("database:\n  host: envhost\nocr:\n  provider: baidu\n")
    monkeypatch.setenv("CONFIG_PATH", str(cfg_file))
    config = load_config()
    assert config["database"]["host"] == "envhost"

def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yaml")
