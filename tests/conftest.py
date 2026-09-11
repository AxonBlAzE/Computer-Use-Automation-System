import socket
import subprocess
import sys
import time
import urllib.request

import pytest


@pytest.fixture(scope="module")
def origin():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "demo_app.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                with urllib.request.urlopen(base, timeout=1):
                    break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    pytest.fail("demo server failed to start")
                time.sleep(0.1)
        yield base
    finally:
        process.terminate()
        process.wait(timeout=10)
