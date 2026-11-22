"""Trusted standalone launch gate; never parses source or imports application code."""
import os
import resource
import sys


def main():
    group, gate, bwrap, *args = sys.argv[1:]
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    with open(group + "/cgroup.procs", "w", encoding="ascii") as stream:
        stream.write(str(os.getpid()))
    os.write(1, b"R")
    permitted = os.read(int(gate), 1) == b"G"
    os.close(int(gate))
    if not permitted:
        raise SystemExit(125)
    os.execve(bwrap, [bwrap, *args], dict(os.environ))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        os._exit(125)
