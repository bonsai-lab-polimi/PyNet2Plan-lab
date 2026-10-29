"""
pynet2plan.jobs
==============

Runs algorithms in a separate Python *process* (``python -m pynet2plan.worker``),
so that the GUI never freezes and a run can be cancelled -- even if a
student's code is stuck in an infinite loop or the solver takes too long.

The job description and the results are plain JSON, exchanged through the
pipes of the child process. Whatever the algorithm prints (``print`` is the
students' best debugging tool!) is captured and returned with the result.

If the child process cannot be started, the job runs in a background thread
instead (then "Cancel" can only stop a sweep between two runs).
"""

from __future__ import annotations

import json
import os
import queue as _queue
import subprocess
import sys
import threading
import traceback

from .loader import PROJECT_ROOT


class Job:
    """A running background job. Poll it with :meth:`poll` (non-blocking)."""

    def __init__(self, payload: dict, use_process: bool | None = None):
        self.payload = payload
        self.result = None          # dict returned by runner.payload_run (+ "output")
        self.crash = None           # traceback text if the job itself crashed
        self.cancelled = False
        self.progress = (0, 0, "")
        self.folder = None          # sweep folder, known as soon as the sweep starts
        self.mode = None
        self._q: _queue.Queue = _queue.Queue()
        self._stop_flag = threading.Event()
        self._proc = None
        self._stderr_tail: list = []
        if use_process is None:
            use_process = os.environ.get("PYNET2PLAN_INPROCESS", "") in ("", "0")
        if use_process:
            try:
                self._start_process()
                self.mode = "process"
            except Exception:  # noqa: BLE001 - fall back to a thread
                self._proc = None
        if self._proc is None:
            self._thread = threading.Thread(target=self._thread_main, daemon=True)
            self._thread.start()
            self.mode = "thread"

    # -- child process ------------------------------------------------------
    def _start_process(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = PROJECT_ROOT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("MPLBACKEND", "Agg")
        kwargs = {}
        if sys.platform.startswith("win"):
            # own process group, so that Cancel can also stop the solver started by the worker
            kwargs["creationflags"] = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                       | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        else:
            kwargs["start_new_session"] = True
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "pynet2plan.worker"], cwd=PROJECT_ROOT, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        data = json.dumps(self.payload).encode("utf-8")
        threading.Thread(target=self._feed, args=(data,), daemon=True).start()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _feed(self, data):
        # the pipe stays open: if this (GUI) process dies, the worker sees the
        # end of its input and stops itself (no orphan computations)
        try:
            self._proc.stdin.write(data + b"\n")
            self._proc.stdin.flush()
        except OSError:
            pass

    def _close_stdin(self):
        try:
            if self._proc is not None and self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except OSError:
            pass

    def _read_stdout(self):
        for raw in self._proc.stdout:
            try:
                msg = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            self._q.put(msg)
        self._q.put({"type": "eof"})

    def _read_stderr(self):
        for raw in self._proc.stderr:
            line = raw.decode("utf-8", "replace")
            try:                            # visible in the terminal that started the GUI
                if sys.stderr is not None:  # (None with pythonw.exe on Windows)
                    sys.stderr.write(line)
            except Exception:  # noqa: BLE001 - never stop draining the pipe
                pass
            self._stderr_tail.append(line)
            del self._stderr_tail[:-200]

    # -- thread fallback ----------------------------------------------------
    def _thread_main(self):
        try:
            from . import runner
            res = runner.payload_run(
                self.payload,
                progress=lambda d, t, s: self._q.put({"type": "progress", "done": d, "total": t, "text": s}),
                should_stop=self._stop_flag.is_set,
                on_folder=lambda f: self._q.put({"type": "folder", "folder": f}))
            self._q.put({"type": "done", "result": res})
        except BaseException:  # noqa: BLE001
            self._q.put({"type": "crash", "traceback": traceback.format_exc()})
        self._q.put({"type": "eof"})

    # -----------------------------------------------------------------------
    @property
    def finished(self) -> bool:
        return self.result is not None or self.crash is not None or self.cancelled

    def poll(self) -> bool:
        """Read the messages sent by the job. Returns True when it has finished."""
        eof = False
        while True:
            try:
                msg = self._q.get_nowait()
            except _queue.Empty:
                break
            kind = msg.get("type")
            if kind == "progress":
                self.progress = (msg.get("done", 0), msg.get("total", 0), msg.get("text", ""))
            elif kind == "folder":
                self.folder = msg.get("folder")
            elif kind == "done":
                self.result = msg.get("result") or {}
            elif kind == "crash":
                self.crash = msg.get("traceback", "unknown error")
            elif kind == "eof":
                eof = True
        if self.finished:
            self._close_stdin()
        if eof and not self.finished:
            if self._proc is not None:
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                code = self._proc.returncode
                tail = "".join(self._stderr_tail[-40:])
                self.crash = (f"The computation process stopped unexpectedly (exit code {code}).\n\n"
                              f"{tail}")
            else:
                self.crash = "The computation stopped unexpectedly."
        return self.finished

    def wait(self, timeout: float | None = None) -> bool:
        """Block until finished (used by tests and scripts)."""
        import time
        t0 = time.time()
        while not self.poll():
            if timeout is not None and time.time() - t0 > timeout:
                return False
            time.sleep(0.05)
        return True

    @property
    def still_running(self) -> bool:
        """True while the computation really runs (a cancelled thread may still be busy)."""
        if self._proc is not None:
            return self._proc.poll() is None
        return self._thread.is_alive()

    def cancel(self) -> None:
        self.cancelled = True
        self._stop_flag.set()
        if self._proc is None or self._proc.poll() is not None:
            return
        pid = self._proc.pid
        if sys.platform.startswith("win"):
            # kill the worker and its children (the CBC solver) -- the whole tree
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                               timeout=10)
            except Exception:  # noqa: BLE001
                self._proc.kill()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            return
        import signal
        # the worker leads its own process group (start_new_session): the group also contains
        # the programs it started, such as the CBC solver; never signal our own group
        try:
            group = os.getpgid(pid)
        except OSError:
            group = None
        if group is not None and group == os.getpgrp():
            group = None
        try:
            if group is None:
                raise ProcessLookupError
            os.killpg(group, signal.SIGTERM)                 # worker + solver: stop now
        except OSError:
            self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        if group is not None:
            # a program started by the worker may survive SIGTERM (it may handle the signal,
            # as solvers often do, or still be starting): SIGKILL the rest of the group too.
            # The group id cannot be reused while a member of the group is alive.
            try:
                os.killpg(group, signal.SIGKILL)
            except OSError:
                pass
