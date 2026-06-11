"""Process-wide singleton config loaded from local_config.json.

Usage:
    from config_helpers import Config
    node = Config().get("special_gpu_node")     # None if unset
    everything = dict(Config())                  # all keys

Subclassing `dict` gives us `.get`, `[key]`, `in`, iteration, etc. for free.
`__new__` makes every `Config()` call return the same instance, loaded once.
"""
import json
from pathlib import Path

_FILE = Path(__file__).parent / "local_config.json"


class Config(dict):
    _instance: "Config | None" = None

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            with _FILE.open() as f:
                cls._instance.update(json.load(f))
        return cls._instance
