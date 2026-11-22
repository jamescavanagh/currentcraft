"""Synthetic unit checks and opt-in real Linux security acceptance, clearly separated."""
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.application.ingest.reference_documents import ReferenceIngestProfile
from app.infrastructure.ingest import ref_isolation as iso
from app.infrastructure.ingest.reference_documents import (
    build_bundle_from_bytes, ingest_and_hydrate, _read_source_bytes,
)
from app.infrastructure.persistence.memory import MemoryStore

SOURCE = b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><n>synthetic</n></rdf:RDF>'
PROFILE = ReferenceIngestProfile(profile_id="synthetic-isolation", version="1")
HANDLE = "ref_synthetic_isolation"
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
LIVE = os.environ.get("DATAMESH_REQUIRE_REF_ISOLATION") == "1"


class IsolationUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "private"
        self.root.mkdir()
        (self.root / "source.owl").write_bytes(SOURCE)
        self.digest = hashlib.sha256(SOURCE).hexdigest()
        self.bundle = build_bundle_from_bytes(SOURCE, "source.owl", HANDLE, self.digest, PROFILE)
        self.config = iso.LinuxIsolation(Path("/synthetic/delegation"), Path("/synthetic/runtime"))
        self.uow = MemoryStore()

    def verify(self, data):
        return iso._verify(data, SOURCE, "source.owl", HANDLE, self.digest, PROFILE)

    def test_missing_config_fails_before_parsing_publication_or_graph_write(self):
        with patch("app.infrastructure.ingest.reference_documents._extract", side_effect=AssertionError("parsed")):
            with self.assertRaisesRegex(iso.IsolationFailure, "^isolation_unavailable$"):
                ingest_and_hydrate(self.root, "source.owl", HANDLE, "out/a.json",
                                   self.digest, PROFILE, self.uow, NOW)
        self.assertFalse((self.root / "out").exists())
        with self.uow() as uow:
            self.assertIsNone(uow.objects.get(HANDLE))

    def test_platform_fail_closed(self):
        with patch.object(iso.sys, "platform", "darwin"):
            with self.assertRaisesRegex(iso.IsolationFailure, "^isolation_unavailable$"):
                self.config.check()

    def test_regular_directory_is_not_cgroup_delegation(self):
        config = iso.LinuxIsolation(Path(self.tmp.name), Path(self.tmp.name))
        with self.assertRaisesRegex(iso.IsolationFailure, "^isolation_unavailable$"):
            config.check()

    def test_unusable_delegation_fails_before_source_is_read(self):
        with patch.object(iso.LinuxIsolation, "check", side_effect=iso.IsolationFailure("isolation_unavailable")), \
             patch("app.infrastructure.ingest.reference_documents._read_source_bytes",
                   side_effect=AssertionError("source read before prerequisite checks")):
            with self.assertRaisesRegex(iso.IsolationFailure, "^isolation_unavailable$"):
                ingest_and_hydrate(self.root, "source.owl", HANDLE, "out/a.json",
                                   self.digest, PROFILE, self.uow, NOW, isolation=self.config)

    def test_no_duck_typed_backend_can_bypass_checks(self):
        with self.assertRaisesRegex(iso.IsolationFailure, "^isolation_unavailable$"):
            ingest_and_hydrate(self.root, "source.owl", HANDLE, "out/a.json",
                               self.digest, PROFILE, self.uow, NOW, isolation=object())

    def test_safe_result_binding(self):
        actual = self.verify(self.bundle.model_dump_json().encode())
        self.assertEqual(actual, self.bundle)

    def test_hostile_result_is_rejected_without_source_exception_chain(self):
        for mutate in (
            lambda data: data.update(source_sha256="0" * 64),
            lambda data: data.update(document_id="ref_forged"),
            lambda data: data.update(profile_sha256="1" * 64),
            lambda data: data.update(source_name="other.owl"),
            lambda data: data["pages"][0].update(text="SYNTHETIC_PRIVATE_CANARY"),
            lambda data: data.update(extra="SYNTHETIC_PRIVATE_CANARY"),
        ):
            data = self.bundle.model_dump(mode="json")
            mutate(data)
            with self.assertRaisesRegex(iso.IsolationFailure, "^invalid_result$") as caught:
                self.verify(json.dumps(data).encode())
            self.assertIsNone(caught.exception.__cause__)
            self.assertIsNone(caught.exception.__context__)

    def test_self_consistent_but_forged_tree_rejected(self):
        forged = self.bundle.model_copy(update={
            "nodes": (self.bundle.nodes[0].model_copy(update={"title": "synthetic forged title"}), *self.bundle.nodes[1:])})
        forged = forged.model_copy(update={"payload_sha256": forged.payload_digest()})
        with self.assertRaisesRegex(iso.IsolationFailure, "^invalid_result$"):
            self.verify(forged.model_dump_json().encode())

    def test_bad_json_duplicate_keys_and_nested_result_fail_safely(self):
        for data in (b"{", b'{"schema_version":"x","schema_version":"y"}', b"[" * 2000 + b"]" * 2000):
            with self.assertRaisesRegex(iso.IsolationFailure, "^invalid_result$"):
                self.verify(data)

    def test_result_byte_ceiling(self):
        with patch.object(iso, "RESULT_BYTES", 5):
            with self.assertRaisesRegex(iso.IsolationFailure, "^invalid_result$"):
                self.verify(b"123456")

    def test_bounded_source_reader_and_symlink_rejection(self):
        self.assertEqual(_read_source_bytes(self.root, "source.owl", len(SOURCE)), SOURCE)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            _read_source_bytes(self.root, "source.owl", len(SOURCE) - 1)
        (self.root / "link.owl").symlink_to(self.root / "source.owl")
        with self.assertRaisesRegex(ValueError, "symlink"):
            _read_source_bytes(self.root, "link.owl", 1024)

    def test_command_requires_explicit_namespaces_without_try_or_shell(self):
        command = self.config._command(Path("/synthetic/group"), 7, 8)
        for flag in ("--unshare-user", "--disable-userns", "--unshare-pid", "--unshare-ipc",
                     "--unshare-net", "--unshare-uts", "--unshare-cgroup", "--die-with-parent",
                     "--new-session", "--clearenv", "--ro-bind-data", "-I", "-S"):
            self.assertIn(flag, command)
        self.assertFalse(any("-try" in part for part in command))
        self.assertNotIn("--unshare-all", command)
        self.assertNotIn("--share-net", command)
        self.assertNotIn("--probe", command)
        self.assertNotIn("/references/private", command)

    def test_probe_modes_are_fixed_not_source_selected(self):
        with self.assertRaisesRegex(iso.IsolationFailure, "^invalid_source$"):
            self.config._command(Path("/synthetic/group"), 7, 8, probe="arbitrary command")

    def test_exit_classification_does_not_guess_oom_from_sigkill(self):
        self.assertEqual(iso._exit_code(-signal.SIGKILL), "worker_failed")
        self.assertEqual(iso._exit_code(-signal.SIGXCPU), "cpu_limit")
        self.assertEqual(iso._exit_code(65), "invalid_source")
        self.assertEqual(iso._exit_code(66), "output_limit")
        self.assertEqual(iso._exit_code(125), "isolation_unavailable")

    def test_busy_has_no_fallback_and_releases_no_unowned_permit(self):
        self.assertTrue(iso._ACTIVE.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(iso.IsolationFailure, "^busy$"):
                self.config.extract(SOURCE, "source.owl", HANDLE, self.digest, PROFILE)
        finally:
            iso._ACTIVE.release()

    def test_subprocess_failure_never_publishes_or_commits(self):
        for reason in ("cpu_limit", "wall_timeout", "memory_limit", "output_limit",
                       "worker_failed", "cleanup_failed"):
            with self.subTest(reason=reason), \
                 patch.object(iso.LinuxIsolation, "check"), \
                 patch.object(iso.LinuxIsolation, "_run", side_effect=iso.IsolationFailure(reason)):
                with self.assertRaisesRegex(iso.IsolationFailure, "^" + reason + "$"):
                    ingest_and_hydrate(self.root, "source.owl", HANDLE, "out/a.json",
                                       self.digest, PROFILE, self.uow, NOW, isolation=self.config)
            self.assertFalse((self.root / "out").exists())
            with self.uow() as uow:
                self.assertIsNone(uow.objects.get(HANDLE))

    def test_pdf_is_not_silently_routed_to_trusted_parser(self):
        (self.root / "source.pdf").write_bytes(b"%PDF-synthetic")
        with patch.object(iso.LinuxIsolation, "check"):
            with self.assertRaisesRegex(iso.IsolationFailure, "^invalid_source$"):
                ingest_and_hydrate(self.root, "source.pdf", HANDLE, "out/a.json",
                                   self.digest, PROFILE, self.uow, NOW, isolation=self.config)

    def test_parent_verifies_then_publishes_and_hydrates_mocked_candidate(self):
        # Composition test only: mocking the supervisor is not isolation acceptance.
        with patch.object(iso.LinuxIsolation, "check"), \
             patch.object(iso.LinuxIsolation, "_run", return_value=self.bundle.model_dump_json().encode()):
            bundle, result = ingest_and_hydrate(self.root, "source.owl", HANDLE, "out/a.json",
                                               self.digest, PROFILE, self.uow, NOW, isolation=self.config)
        self.assertEqual(bundle, self.bundle)
        self.assertFalse(result.replayed)
        self.assertTrue((self.root / "out/a.json").is_file())
        with self.uow() as uow:
            self.assertEqual(uow.objects.get(HANDLE).fields["source_sha256"], self.digest)

    @unittest.skipUnless(sys.platform == "linux" and hasattr(os, "memfd_create"), "Linux memfd harness")
    def test_real_pipe_supervision_with_explicit_fake_cgroup_counters(self):
        """Real child/gate/pipes/reaping; fake kernel files are NOT containment proof."""
        parent = Path(self.tmp.name) / "fake-cgroup"
        parent.mkdir()
        config = iso.LinuxIsolation(parent, Path("/synthetic/runtime"))
        original_mkdir, original_rmdir = Path.mkdir, Path.rmdir
        controls = ("memory.max", "memory.swap.max", "memory.oom.group", "cpu.max", "pids.max",
                    "cgroup.kill", "cgroup.procs", "memory.events", "cpu.stat", "cgroup.events")
        def mkdir(path, *args, **kwargs):
            original_mkdir(path, *args, **kwargs)
            if path.parent == parent:
                for name in controls:
                    (path / name).write_text("")
                (path / "memory.events").write_text("oom_kill 0\n")
                (path / "cpu.stat").write_text("usage_usec 0\n")
                (path / "cgroup.events").write_text("populated 0\n")
        def rmdir(path):
            if path.parent == parent:
                for name in controls:
                    (path / name).unlink()
            original_rmdir(path)
        child = (
            "import os,sys,time;from pathlib import Path;"
            "g=Path(sys.argv[1]);gate=int(sys.argv[2]);mode=sys.argv[3];"
            "(g/'cgroup.procs').write_text(str(os.getpid()));"
            "os.write(1,b'R');"
            "assert os.read(gate,1)==b'G';os.close(gate);"
            "exec({"
            "'ok':\"os.write(1,b'candidate')\","
            "'wall':\"time.sleep(10)\","
            "'cpu':\"(g/'cpu.stat').write_text('usage_usec 6000000\\\\n');time.sleep(10)\","
            "'oom':\"(g/'memory.events').write_text('oom_kill 1\\\\n');os.kill(os.getpid(),9)\","
            "'output':\"os.write(1,b'x'*1024)\""
            "}[mode])"
        )
        for mode, expected in (("ok", None), ("wall", "wall_timeout"), ("cpu", "cpu_limit"),
                               ("oom", "memory_limit"), ("output", "output_limit")):
            def command(_self, group, request_fd, gate_r, *, probe=None):
                return [sys.executable, "-I", "-S", "-c", child, str(group), str(gate_r), mode]
            with self.subTest(mode=mode), patch.object(Path, "mkdir", mkdir), patch.object(Path, "rmdir", rmdir), \
                 patch.object(iso.LinuxIsolation, "_command", command), \
                 patch.object(iso, "WALL_SECONDS", 0.5), patch.object(iso, "RESULT_BYTES", 256):
                if expected is None:
                    self.assertEqual(config._run(b"{}"), b"candidate")
                else:
                    with self.assertRaisesRegex(iso.IsolationFailure, "^" + expected + "$"):
                        config._run(b"{}")
            self.assertEqual(list(parent.iterdir()), [], "supervisor must clean its fake job directory")


@unittest.skipUnless(LIVE, "set DATAMESH_REQUIRE_REF_ISOLATION=1 on a configured Linux runner")
class LiveLinuxIsolation(unittest.TestCase):
    """When enabled, missing prerequisites are failures, never convenience skips."""
    def setUp(self):
        for name in ("DATAMESH_REF_CGROUP_ROOT", "DATAMESH_REF_RUNTIME_ROOT"):
            self.assertTrue(os.environ.get(name), "required Linux runner setting absent: " + name)
        self.config = iso.LinuxIsolation(Path(os.environ["DATAMESH_REF_CGROUP_ROOT"]),
                                         Path(os.environ["DATAMESH_REF_RUNTIME_ROOT"]))
        self.config.check()

    def tearDown(self):
        if hasattr(self, "config"):
            self.assertEqual(list(self.config.cgroup_root.glob("ref-*")), [],
                             "dedicated live-test delegation must have no residual extraction cgroups")

    def test_real_source_roundtrip(self):
        bundle = self.config.extract(SOURCE, "source.owl", HANDLE, hashlib.sha256(SOURCE).hexdigest(), PROFILE)
        self.assertEqual(bundle.pages[0].text, SOURCE.decode())

    def test_real_budgets(self):
        for probe, expected in (("cpu", "cpu_limit"), ("wall", "wall_timeout"),
                                ("memory", "memory_limit"), ("output", "output_limit")):
            with self.subTest(probe=probe):
                with self.assertRaisesRegex(iso.IsolationFailure, "^" + expected + "$"):
                    self.config._run(b"{}", probe=probe)
        # Failure cleanup must not poison the next job.
        self.test_real_source_roundtrip()

    def test_real_denied_capabilities(self):
        result = json.loads(self.config._run(b"{}", probe="restrictions"))
        self.assertEqual(result, {"fork_denied": True, "network_denied": True,
                                  "unrelated_file_denied": True, "write_denied": True})


if __name__ == "__main__":
    unittest.main()
