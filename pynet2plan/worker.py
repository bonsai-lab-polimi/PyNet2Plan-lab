"""
Child process used by the GUI to run algorithms (see pynet2plan.jobs).

Protocol: the job (JSON) is read from stdin; JSON messages, one per line, are
written to the *original* stdout. Anything printed by the algorithm goes to
stderr (so it shows up in the terminal) and is also captured and returned
in ``result["output"]``.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import traceback

MAX_OUTPUT = 20000


class _Tee(io.TextIOBase):
    def __init__(self, stream):
        self.stream = stream
        self.parts = []
        self.size = 0

    def write(self, s):
        try:
            self.stream.write(s)
            self.stream.flush()
        except Exception:  # noqa: BLE001
            pass
        self.parts.append(s)
        self.size += len(s)
        while self.size > 4 * MAX_OUTPUT and len(self.parts) > 1:
            self.size -= len(self.parts.pop(0))
        return len(s)

    def flush(self):
        try:
            self.stream.flush()
        except Exception:  # noqa: BLE001
            pass

    def text(self):
        t = "".join(self.parts)
        return t[-MAX_OUTPUT:]


def _watch_parent():
    """Stop everything (this process and the solver it started) when the GUI
    closes our input pipe -- e.g. because it was closed or crashed."""
    try:
        sys.stdin.read()
    except Exception:  # noqa: BLE001
        pass
    if hasattr(os, "killpg") and os.getpgid(0) == os.getpid():   # we lead our own group
        import signal
        try:
            os.killpg(os.getpid(), signal.SIGKILL)
        except OSError:
            pass
    os._exit(3)


def main() -> int:
    proto = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())     # stray writes to fd 1 go to stderr
    tee = _Tee(sys.stderr)
    sys.stdout = tee

    def send(msg):
        proto.write(json.dumps(msg, default=str) + "\n")
        proto.flush()

    try:
        payload = json.loads(sys.stdin.readline())
        threading.Thread(target=_watch_parent, daemon=True).start()
        from pynet2plan import runner
        result = runner.payload_run(
            payload,
            progress=lambda d, t, s: send({"type": "progress", "done": d, "total": t, "text": s}),
            on_folder=lambda f: send({"type": "folder", "folder": f}))
        result["output"] = tee.text()
        send({"type": "done", "result": result})
    except BaseException:  # noqa: BLE001
        send({"type": "crash", "traceback": traceback.format_exc()})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
