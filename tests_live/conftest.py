"""Minimal conftest for live hardware tests.

Lives outside tests/ to avoid tests/conftest.py loading
pytest_homeassistant_custom_component fixtures. However, that package
is still an installed entry-point plugin so its socket-blocking hooks
still apply globally (via pytest_runtest_setup).

The HA plugin does, in order, in pytest_runtest_setup():
  1. socket_allow_hosts(["127.0.0.1"]) → patches _true_socket.connect
  2. disable_socket()                  → replaces socket.socket with GuardedSocket

We must restore BOTH socket.socket AND socket.socket.connect here.
"""

import socket
import sys
from pathlib import Path

import pytest

# Make custom_components importable
sys.path.insert(0, str(Path(__file__).parent.parent))

# pytest-socket saves originals at module-import time, before any patching
try:
    from pytest_socket import _true_connect as _real_connect
    from pytest_socket import _true_socket as _real_socket
except ImportError:
    _real_socket = None
    _real_connect = None


@pytest.fixture(autouse=True)
def restore_real_socket():
    """Restore genuine socket.socket and connect() for live hardware tests."""
    if _real_socket is not None:
        socket.socket = _real_socket
        socket.socket.connect = _real_connect
    yield
