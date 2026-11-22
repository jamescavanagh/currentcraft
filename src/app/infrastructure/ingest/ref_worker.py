"""Sandbox-only worker. No raw exceptions, paths or source literals on error."""
import base64
import ctypes
import hashlib
import json
import os
import sys


def lockdown():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise RuntimeError("unavailable")
    lib = ctypes.CDLL("libseccomp.so.2")
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("unavailable")
    denied = ("clone", "clone3", "fork", "vfork", "execve", "execveat", "unshare",
              "setns", "mount", "umount2", "ptrace", "bpf", "keyctl",
              "open_by_handle_at", "perf_event_open", "userfaultfd",
              "process_vm_readv", "process_vm_writev", "socket", "socketpair",
              "connect", "bind", "listen", "accept", "accept4")
    try:
        for syscall in denied:
            number = lib.seccomp_syscall_resolve_name(syscall.encode("ascii"))
            if number < 0 or lib.seccomp_rule_add(context, 0x00050001, number, 0) != 0:  # EPERM
                raise RuntimeError("unavailable")
        if lib.seccomp_load(context) != 0:
            raise RuntimeError("unavailable")
    finally:
        lib.seccomp_release(context)


def main():
    lockdown()
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        return probe(sys.argv[2])
    # -I ignores PYTHONPATH; only the fixed, administrator-provisioned code root is used.
    sys.path.insert(0, "/opt/currentcraft/src")
    from app.application.ingest.reference_documents import ReferenceIngestProfile
    from app.infrastructure.ingest.reference_documents import _closed_object, build_bundle_from_bytes
    with open("/input.json", "rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("invalid")
    request = json.loads(raw, object_pairs_hook=_closed_object)
    if set(request) != {"schema", "source", "name", "handle", "sha256", "profile"}:
        raise ValueError("invalid")
    if request["schema"] != "currentcraft-ref-job/v1":
        raise ValueError("invalid")
    source = base64.b64decode(request["source"], validate=True)
    if len(source) > 2 * 1024 * 1024 or hashlib.sha256(source).hexdigest() != request["sha256"]:
        raise ValueError("invalid")
    profile = ReferenceIngestProfile.model_validate(request["profile"])
    bundle = build_bundle_from_bytes(source, request["name"], request["handle"], request["sha256"], profile)
    result = bundle.model_dump_json().encode("utf-8")
    if len(result) > 16 * 1024 * 1024:
        raise OverflowError("output")
    view = memoryview(result)
    while view:
        view = view[os.write(1, view):]


def probe(mode):
    """Fixed coordinator-selected live acceptance probes, never selected by source content."""
    if mode == "cpu":
        while True:
            pass
    if mode == "wall":
        import time
        time.sleep(60)
    if mode == "memory":
        _allocation = bytearray(512 * 1024 * 1024)
    if mode == "output":
        for _ in range(4096):
            os.write(1, b"x" * 65_536)
    if mode == "restrictions":
        import socket
        result = {}
        for key, action in (
            ("fork_denied", os.fork),
            ("network_denied", lambda: socket.socket()),
            ("unrelated_file_denied", lambda: open("/references/private/synthetic-secret", "rb")),
            ("write_denied", lambda: open("/synthetic-write", "wb")),
        ):
            try:
                value = action()
                if key == "fork_denied" and value == 0:
                    os._exit(2)
                if hasattr(value, "close"):
                    value.close()
                result[key] = False
            except OSError:
                result[key] = True
        os.write(1, json.dumps(result).encode("ascii"))
        return
    raise ValueError("invalid")


if __name__ == "__main__":
    try:
        main()
    except ValueError:
        os._exit(65)
    except OverflowError:
        os._exit(66)
    except BaseException:
        os._exit(125)
