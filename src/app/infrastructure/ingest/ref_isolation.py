"""Fail-closed Linux supervisor for one source-literal RDF extraction at a time."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass

SOURCE_BYTES = 2 * 1024 * 1024
RESULT_BYTES = 16 * 1024 * 1024
WALL_SECONDS = 10
CPU_USEC = 6_000_000
MEMORY_BYTES = 256 * 1024 * 1024
_ACTIVE = threading.BoundedSemaphore(1)


class IsolationFailure(RuntimeError):
    """Public-safe fixed code only; never wrap raw subprocess or filesystem errors."""
    CODES = frozenset({"isolation_unavailable", "invalid_source", "busy", "cpu_limit",
                       "wall_timeout", "memory_limit", "output_limit", "worker_failed",
                       "invalid_result", "cleanup_failed"})

    def __init__(self, code):
        self.code = code if code in self.CODES else "worker_failed"
        super().__init__(self.code)


def _trusted_path(path, directory):
    if not isinstance(path, Path) or not path.is_absolute():
        raise IsolationFailure("isolation_unavailable")
    resolved = path.resolve(strict=True)
    if resolved != path or not (path.is_dir() if directory else path.is_file()):
        raise IsolationFailure("isolation_unavailable")
    for ancestor in (path, *path.parents):
        info = ancestor.stat()
        if info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022:
            raise IsolationFailure("isolation_unavailable")
    return resolved


@dataclass(frozen=True)
class LinuxIsolation:
    """Administrator-provisioned secret-free runtime and cgroup v2 delegation."""
    cgroup_root: Path
    runtime_root: Path
    bubblewrap: Path = Path("/usr/bin/bwrap")

    def check(self):
        valid = False
        try:
            if sys.platform != "linux" or not hasattr(os, "memfd_create"):
                raise IsolationFailure("isolation_unavailable")
            root = _trusted_path(self.cgroup_root, True)
            runtime = _trusted_path(self.runtime_root, True)
            launcher = _trusted_path(self.bubblewrap, False)
            if runtime in {Path("/"), Path("/usr"), Path("/opt"), Path("/home"), Path("/tmp")} or runtime.name == "private":
                raise IsolationFailure("isolation_unavailable")
            # Verify a real cgroup2 mount, not a lookalike ordinary directory.
            mounts = []
            for line in Path("/proc/self/mountinfo").read_text().splitlines():
                before, after = line.split(" - ", 1)
                if after.split()[0] == "cgroup2":
                    mounts.append(Path(before.split()[4].replace("\\040", " ")))
            if not any(root.is_relative_to(mount) for mount in mounts):
                raise IsolationFailure("isolation_unavailable")
            enabled = set((root / "cgroup.subtree_control").read_text().split())
            if not {"cpu", "memory", "pids"}.issubset(enabled) or not os.access(root, os.W_OK):
                raise IsolationFailure("isolation_unavailable")
            required = (runtime / "usr/bin/python3", runtime / "input.json",
                        runtime / "opt/currentcraft/src/app/infrastructure/ingest/ref_worker.py")
            if not os.access(launcher, os.X_OK) or not all(p.is_file() for p in required):
                raise IsolationFailure("isolation_unavailable")
            valid = True
        except (OSError, ValueError, IsolationFailure):
            pass
        if not valid:
            raise IsolationFailure("isolation_unavailable")

    def extract(self, source, name, handle, digest, profile):
        if not _ACTIVE.acquire(blocking=False):
            raise IsolationFailure("busy")
        try:
            self.check()
            if Path(name).suffix.lower() not in {".rdf", ".owl"}:
                raise IsolationFailure("invalid_source")
            if not source or len(source) > SOURCE_BYTES or hashlib.sha256(source).hexdigest() != digest:
                raise IsolationFailure("invalid_source")
            envelope = {"schema": "currentcraft-ref-job/v1", "source": base64.b64encode(source).decode("ascii"),
                        "name": name, "handle": handle, "sha256": digest, "profile": profile.model_dump(mode="json")}
            request = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(request) > 4 * 1024 * 1024:
                raise IsolationFailure("invalid_source")
            raw = self._run(request)
            return _verify(raw, source, name, handle, digest, profile)
        finally:
            _ACTIVE.release()

    def _run(self, request, *, probe=None):
        import fcntl  # Linux-only; import never precedes fail-closed platform checks.
        group = self.cgroup_root / ("ref-" + uuid.uuid4().hex)
        process = None
        fds = []
        selector = selectors.DefaultSelector()
        result = bytearray()
        started = time.monotonic()
        outcome = "isolation_unavailable"
        success = False
        created = False
        try:
            group.mkdir(mode=0o700)
            created = True
            limits = {"memory.max": str(MEMORY_BYTES), "memory.swap.max": "0", "memory.oom.group": "1",
                      "cpu.max": "100000 100000", "pids.max": "8"}
            for key, value in limits.items():
                (group / key).write_text(value, encoding="ascii")
                if (group / key).read_text().strip() != value:
                    raise IsolationFailure("isolation_unavailable")
            if not (group / "cgroup.kill").is_file():
                raise IsolationFailure("isolation_unavailable")
            (group / "cgroup.kill").write_text("1", encoding="ascii")
            baseline_oom = _counters(group / "memory.events").get("oom_kill", 0)
            request_fd = os.memfd_create("ref-request", os.MFD_ALLOW_SEALING)
            fds.append(request_fd)
            view = memoryview(request)
            while view:
                view = view[os.write(request_fd, view):]
            os.lseek(request_fd, 0, os.SEEK_SET)
            fcntl.fcntl(request_fd, fcntl.F_ADD_SEALS,
                        fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
            gate_r, gate_w = os.pipe()
            fds.extend((gate_r, gate_w))
            command = self._command(group, request_fd, gate_r, probe=probe)
            environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                           "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                           "PYTHONDONTWRITEBYTECODE": "1"}
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, close_fds=True,
                                       pass_fds=(request_fd, gate_r), env=environment, start_new_session=True)
            os.close(gate_r)
            fds.remove(gate_r)
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            ready = False
            eof = False
            while not eof or process.poll() is None:
                if time.monotonic() - started >= WALL_SECONDS:
                    raise IsolationFailure("wall_timeout")
                if _counters(group / "cpu.stat").get("usage_usec", 0) >= CPU_USEC:
                    raise IsolationFailure("cpu_limit")
                for key, _ in selector.select(timeout=0.05):
                    chunk = os.read(key.fileobj.fileno(), 65_536)
                    if not chunk:
                        eof = True
                        selector.unregister(key.fileobj)
                        continue
                    if not ready:
                        if chunk[:1] != b"R":
                            raise IsolationFailure("worker_failed")
                        members = (group / "cgroup.procs").read_text().split()
                        if str(process.pid) not in members:
                            raise IsolationFailure("isolation_unavailable")
                        os.write(gate_w, b"G")
                        os.close(gate_w)
                        fds.remove(gate_w)
                        chunk = chunk[1:]
                        ready = True
                    if len(result) + len(chunk) > RESULT_BYTES:
                        raise IsolationFailure("output_limit")
                    result.extend(chunk)
            code = process.wait(timeout=1)
            if _counters(group / "memory.events").get("oom_kill", 0) > baseline_oom:
                raise IsolationFailure("memory_limit")
            if not ready or code:
                raise IsolationFailure(_exit_code(code))
            success = True
        except IsolationFailure as failure:
            outcome = failure.code
        except (OSError, ValueError, subprocess.SubprocessError):
            outcome = "isolation_unavailable"
        finally:
            selector.close()
            for fd in fds:
                os.close(fd)
            clean = True
            if created:
                try:
                    (group / "cgroup.kill").write_text("1", encoding="ascii")
                except OSError:
                    clean = False
            if process is not None:
                try:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    clean = False
                if process.stdout:
                    process.stdout.close()
            if created:
                try:
                    deadline = time.monotonic() + 2
                    while _counters(group / "cgroup.events").get("populated", 0):
                        if time.monotonic() >= deadline:
                            raise OSError("cleanup")
                        time.sleep(0.01)
                    group.rmdir()
                except OSError:
                    clean = False
            if not clean:
                raise IsolationFailure("cleanup_failed") from None
        if not success:
            raise IsolationFailure(outcome)
        return bytes(result)

    def _command(self, group, request_fd, gate_r, *, probe=None):
        # Explicit namespaces: --unshare-all contains "-try" fallbacks and is forbidden here.
        command = [sys.executable, "-I", "-S", str(Path(__file__).with_name("ref_bootstrap.py")),
                str(group), str(gate_r), str(self.bubblewrap),
                "--die-with-parent", "--new-session", "--unshare-user", "--disable-userns",
                "--unshare-pid", "--unshare-ipc", "--unshare-net", "--unshare-uts", "--unshare-cgroup",
                "--cap-drop", "ALL", "--clearenv", "--ro-bind", str(self.runtime_root), "/",
                "--ro-bind-data", str(request_fd), "/input.json", "--chdir", "/",
                "--setenv", "OPENBLAS_NUM_THREADS", "1", "--setenv", "OMP_NUM_THREADS", "1",
                "/usr/bin/python3", "-I", "-B",
                "/opt/currentcraft/src/app/infrastructure/ingest/ref_worker.py"]
        if probe is not None:
            if probe not in {"cpu", "wall", "memory", "output", "restrictions"}:
                raise IsolationFailure("invalid_source")
            command.extend(("--probe", probe))
        return command


def _counters(path):
    return {line.split()[0]: int(line.split()[1]) for line in path.read_text().splitlines()}


def _exit_code(code):
    if code in {-signal.SIGXCPU, 128 + signal.SIGXCPU}:
        return "cpu_limit"
    return {65: "invalid_source", 66: "output_limit", 125: "isolation_unavailable"}.get(code, "worker_failed")


def _verify(raw, source, name, handle, digest, profile):
    from app.application.ingest.reference_documents import ReferenceDocumentBundle
    from app.infrastructure.ingest.reference_documents import _closed_object, _make_tree, RDF_POLICY
    valid = False
    bundle = None
    try:
        if len(raw) > RESULT_BYTES:
            raise ValueError("result")
        data = json.loads(raw, object_pairs_hook=_closed_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
        bundle = ReferenceDocumentBundle.model_validate(data)
        literal = source.decode("utf-8-sig", errors="strict")
        if (bundle.document_id, bundle.source_name, bundle.source_sha256, bundle.profile_sha256,
            bundle.source_format, bundle.extractor_name, bundle.extractor_version) != (
                handle, name, digest, profile.digest(), "owl", "rdfxml-source", RDF_POLICY):
            raise ValueError("binding")
        if len(bundle.pages) != 1 or bundle.pages[0].text != literal or len(literal) > min(profile.max_extracted_chars, 2_000_000):
            raise ValueError("source")
        if bundle.payload_sha256 != bundle.payload_digest():
            raise ValueError("digest")
        if (bundle.coverage, bundle.coverage_reason) != (profile.coverage, profile.coverage_reason):
            raise ValueError("coverage")
        expected = _make_tree(handle, digest, name, (literal,), profile.model_copy(update={"heading_pattern": None}))
        if bundle.nodes != expected:
            raise ValueError("identity")
        valid = True
    except (ValueError, TypeError, UnicodeError, KeyError, RecursionError):
        pass
    if not valid:
        raise IsolationFailure("invalid_result")
    return bundle
