"""Unit tests for Settings.from_env() configuration rules and secret safety."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest

from app.interfaces.http.settings import Settings, SettingsError

SENTINEL_API = "api-secret-value-112233"
SENTINEL_NATS = "nats-secret-value-445566"
SENTINEL_PG_RAW = "p:ss/w?rd#1%2&3=4"


class TestHttpSettings(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.api_file = self.tmp_path / "api_token"
        self.nats_file = self.tmp_path / "nats_token"
        self.pg_file = self.tmp_path / "pg_app"

        self.api_file.write_text(f"  {SENTINEL_API}\n", encoding="utf-8")
        self.nats_file.write_text(f"{SENTINEL_NATS}\n", encoding="utf-8")
        self.pg_file.write_text(f"{SENTINEL_PG_RAW}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _base_env(self) -> dict[str, str]:
        return {
            "DATAMESH_API_TOKEN_FILE": str(self.api_file),
            "DATAMESH_NATS_TOKEN_FILE": str(self.nats_file),
            "DATAMESH_PG_APP_FILE": str(self.pg_file),
        }

    def test_default_postgres_and_nats_construction_with_url_encoded_credentials(self) -> None:
        env = self._base_env()
        env["DATAMESH_PG_USER"] = "app:user/org"
        settings = Settings.from_env(env)

        self.assertEqual(settings.api_token, SENTINEL_API)
        self.assertEqual(settings.nats_token, SENTINEL_NATS)
        self.assertEqual(settings.nats_servers, ("nats://127.0.0.1:4222",))
        self.assertEqual(settings.dependency_timeout_seconds, 3.0)
        self.assertEqual(
            settings.pg_dsn,
            "postgresql://app%3Auser%2Forg:p%3Ass%2Fw%3Frd%231%252%263%3D4@127.0.0.1:5433/datamesh",
        )

    def test_settings_repr_and_str_exclude_secret_fields(self) -> None:
        settings = Settings.from_env(self._base_env())
        for text in (repr(settings), str(settings)):
            self.assertNotIn(SENTINEL_API, text)
            self.assertNotIn(SENTINEL_NATS, text)
            self.assertNotIn(SENTINEL_PG_RAW, text)
            self.assertNotIn("p%3Ass", text)
            self.assertNotIn("postgresql://", text)

    def test_explicit_pg_dsn_takes_precedence_without_requiring_pg_app_file(self) -> None:
        explicit_dsn = "postgresql://custom_user:custom_pass@10.20.30.40:5432/custom_db"
        env = {
            "DATAMESH_API_TOKEN_FILE": str(self.api_file),
            "DATAMESH_NATS_TOKEN_FILE": str(self.nats_file),
            "DATAMESH_PG_DSN": explicit_dsn,
        }
        settings = Settings.from_env(env)
        self.assertEqual(settings.pg_dsn, explicit_dsn)

    def test_explicitly_configured_unreadable_pg_app_file_fails_even_with_pg_dsn(self) -> None:
        missing_pg_file = self.tmp_path / "missing_pg_app"
        env = {
            "DATAMESH_API_TOKEN_FILE": str(self.api_file),
            "DATAMESH_NATS_TOKEN_FILE": str(self.nats_file),
            "DATAMESH_PG_DSN": "postgresql://u:p@127.0.0.1:5433/datamesh",
            "DATAMESH_PG_APP_FILE": str(missing_pg_file),
        }
        with self.assertRaises(SettingsError) as ctx:
            Settings.from_env(env)
        self.assertIn("DATAMESH_PG_APP_FILE", str(ctx.exception))
        self.assertNotIn(str(missing_pg_file), str(ctx.exception))

    def test_required_files_missing_unset_empty_or_directory_fail_safely(self) -> None:
        for var_name in (
            "DATAMESH_API_TOKEN_FILE",
            "DATAMESH_NATS_TOKEN_FILE",
            "DATAMESH_PG_APP_FILE",
        ):
            with self.subTest(var=var_name, case="unset"):
                env = self._base_env()
                del env[var_name]
                with self.assertRaises(SettingsError) as ctx:
                    Settings.from_env(env)
                self.assertIn(var_name, str(ctx.exception))

            with self.subTest(var=var_name, case="missing_file"):
                env = self._base_env()
                missing = self.tmp_path / f"missing_{var_name}"
                env[var_name] = str(missing)
                with self.assertRaises(SettingsError) as ctx:
                    Settings.from_env(env)
                self.assertIn(var_name, str(ctx.exception))
                self.assertNotIn(str(missing), str(ctx.exception))

            with self.subTest(var=var_name, case="empty_file"):
                env = self._base_env()
                empty = self.tmp_path / f"empty_{var_name}"
                empty.write_text("  \n\t\n", encoding="utf-8")
                env[var_name] = str(empty)
                with self.assertRaises(SettingsError) as ctx:
                    Settings.from_env(env)
                self.assertIn(var_name, str(ctx.exception))
                self.assertNotIn(str(empty), str(ctx.exception))

            with self.subTest(var=var_name, case="directory_path"):
                env = self._base_env()
                env[var_name] = str(self.tmp_path)
                with self.assertRaises(SettingsError) as ctx:
                    Settings.from_env(env)
                self.assertIn(var_name, str(ctx.exception))

    @unittest.skipIf(os.geteuid() == 0, "Root bypasses POSIX 0000 file permissions")
    def test_unreadable_chmod_file_fails_safely(self) -> None:
        locked = self.tmp_path / "locked_token"
        locked.write_text("secret\n", encoding="utf-8")
        locked.chmod(0)
        try:
            env = self._base_env()
            env["DATAMESH_API_TOKEN_FILE"] = str(locked)
            with self.assertRaises(SettingsError) as ctx:
                Settings.from_env(env)
            self.assertIn("DATAMESH_API_TOKEN_FILE", str(ctx.exception))
            self.assertNotIn("secret", str(ctx.exception))
            self.assertNotIn(str(locked), str(ctx.exception))
        finally:
            locked.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_rejects_empty_server_entries_and_invalid_ports_or_timeouts(self) -> None:
        bad_envs = [
            ("DATAMESH_NATS_SERVERS", ""),
            ("DATAMESH_NATS_SERVERS", "nats://127.0.0.1:4222,"),
            ("DATAMESH_NATS_SERVERS", ",nats://127.0.0.1:4222"),
            ("DATAMESH_NATS_SERVERS", "nats://a:4222, ,nats://b:4222"),
            ("DATAMESH_PG_PORT", "0"),
            ("DATAMESH_PG_PORT", "65536"),
            ("DATAMESH_PG_PORT", "not-a-port"),
            ("DATAMESH_DEPENDENCY_TIMEOUT_SECONDS", "0"),
            ("DATAMESH_DEPENDENCY_TIMEOUT_SECONDS", "-1.5"),
            ("DATAMESH_DEPENDENCY_TIMEOUT_SECONDS", "nan"),
            ("DATAMESH_DEPENDENCY_TIMEOUT_SECONDS", "inf"),
            ("DATAMESH_DEPENDENCY_TIMEOUT_SECONDS", "abc"),
        ]
        for key, bad_val in bad_envs:
            with self.subTest(key=key, val=bad_val):
                env = self._base_env()
                env[key] = bad_val
                with self.assertRaises(SettingsError) as ctx:
                    Settings.from_env(env)
                self.assertIn(key, str(ctx.exception))
                self.assertNotIn(SENTINEL_API, str(ctx.exception))
                self.assertNotIn(SENTINEL_PG_RAW, str(ctx.exception))
