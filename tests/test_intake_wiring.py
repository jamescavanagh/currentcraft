"""Synthetic HTTP composition-root tests. No live PostgreSQL or broker claims."""

import asyncio
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.interfaces.http.settings import Settings, SettingsError
from app.interfaces.http import wiring


class IntakeWiringTests(unittest.TestCase):
    def test_typed_dependencies_share_existing_repository_factory(self):
        with TemporaryDirectory() as temp:
            settings = Settings("synthetic", ("nats://example.invalid",), "synthetic", "synthetic",
                                blob_root=temp)
            factory = Mock()
            broker = Mock()
            broker.close = AsyncMock()
            with patch.object(wiring, "build_postgres", return_value=factory) as build, \
                    patch.object(wiring, "connect_jetstream", new=AsyncMock(return_value=broker)):
                container = asyncio.run(wiring.build_container(settings))
                self.assertIs(container.uow_factory, factory)
                self.assertIs(container.intake_broker, broker)
                self.assertEqual(container.blobs.root, Path(temp).resolve())
                self.assertTrue((Path(temp) / "intake-receipts.sqlite3").is_file())
                self.assertFalse(build.call_args.kwargs["run_migrations"])
                asyncio.run(container.close())
                broker.close.assert_awaited_once()

    def test_storage_failure_is_safe_and_closes_broker(self):
        settings = Settings("synthetic", ("nats://example.invalid",), "synthetic", "synthetic")
        broker = Mock()
        broker.close = AsyncMock()
        with patch.object(wiring, "build_postgres", return_value=Mock()), \
                patch.object(wiring, "connect_jetstream", new=AsyncMock(return_value=broker)), \
                patch.object(wiring, "DirectoryBlobStore", side_effect=RuntimeError("/private/path synthetic-token")):
            with self.assertRaises(wiring.StartupWiringError) as raised:
                asyncio.run(wiring.build_container(settings))
        self.assertNotIn("/private/path", str(raised.exception))
        self.assertNotIn("synthetic-token", str(raised.exception))
        broker.close.assert_awaited_once()

    def test_new_settings_are_additive_and_empty_values_fail_closed(self):
        with TemporaryDirectory() as temp:
            secret = Path(temp) / "secret"
            secret.write_text("synthetic")
            env = dict(DATAMESH_API_TOKEN_FILE=str(secret), DATAMESH_NATS_TOKEN_FILE=str(secret),
                       DATAMESH_PG_DSN="synthetic")
            defaults = Settings.from_env(env)
            self.assertEqual(defaults.blob_root, "/srv/datamesh/blobs")
            self.assertEqual(defaults.intake_handler_id, "ingest-v1")
            for name in ("DATAMESH_BLOB_ROOT", "DATAMESH_INTAKE_RECEIPT_DB", "DATAMESH_INTAKE_HANDLER_ID"):
                for value in ("", "   "):
                    with self.subTest(name=name, value=value), self.assertRaises(SettingsError):
                        Settings.from_env({**env, name: value})
            configured = Settings.from_env({**env, "DATAMESH_BLOB_ROOT": temp,
                                            "DATAMESH_INTAKE_RECEIPT_DB": str(Path(temp) / "receipt.sqlite3"),
                                            "DATAMESH_INTAKE_HANDLER_ID": "synthetic-worker"})
            self.assertEqual(configured.blob_root, temp)
            self.assertEqual(configured.intake_handler_id, "synthetic-worker")
            self.assertNotIn(temp, repr(configured))
