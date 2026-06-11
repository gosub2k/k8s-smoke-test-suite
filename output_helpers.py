"""Real-time debug output during pytest.

Writes to stderr with flush=True. With `--capture=tee-sys` in pyproject.toml,
pytest captures these messages for the report AND echoes them to the terminal
live as they happen.
"""
import sys


def debug(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, flush=True, **kwargs)
