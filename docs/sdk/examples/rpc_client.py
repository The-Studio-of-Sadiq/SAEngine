"""A minimal JSON-RPC client of SAEngine's backend (SAEngine SDK example).

Starts ``python -m saengine.rpc.server``, sends requests framed with ``Content-Length`` headers
(as the Language Server Protocol does) and prints the answers. Any language can do the same.

    python rpc_client.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import IO, Any


def send(stdin: IO[bytes], message: dict[str, Any]) -> None:
    body = json.dumps(message).encode("utf-8")
    stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    stdin.flush()


def receive(stdout: IO[bytes]) -> dict[str, Any]:
    length = 0
    while True:
        line = stdout.readline()
        if not line:
            raise EOFError("the backend closed its output")
        if line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("ascii").partition(":")
        if name.strip().lower() == "content-length":
            length = int(value)
    return json.loads(stdout.read(length))


def main() -> int:
    server = subprocess.Popen(
        [sys.executable, "-m", "saengine.rpc.server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    assert server.stdin and server.stdout
    try:
        calls = [("saengine/info", {}), ("codes/list", {"kind": "all"})]
        for number, (method, params) in enumerate(calls, start=1):
            send(server.stdin, {"jsonrpc": "2.0", "id": number, "method": method, "params": params})
            while True:
                answer = receive(server.stdout)
                if answer.get("id") == number:  # skip notifications
                    break
            print(method, "->", json.dumps(answer.get("result", answer.get("error")))[:400])
        send(server.stdin, {"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
        send(server.stdin, {"jsonrpc": "2.0", "method": "exit"})
    finally:
        server.wait(timeout=30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
