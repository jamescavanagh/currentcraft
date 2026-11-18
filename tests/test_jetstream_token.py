"""Unit tests for token authentication in connect_jetstream without a live broker."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.infrastructure.messaging.jetstream import connect_jetstream


class TestJetStreamToken(unittest.IsolatedAsyncioTestCase):
    def _make_fake_nats_module(self) -> tuple[types.ModuleType, AsyncMock]:
        fake_nc = MagicMock()
        fake_nc.jetstream.return_value = MagicMock()
        connect_mock = AsyncMock(return_value=fake_nc)

        fake_nats = types.ModuleType("nats")
        fake_nats.connect = connect_mock  # type: ignore[attr-defined]
        return fake_nats, connect_mock

    async def test_forwards_token_to_nats_connect(self) -> None:
        fake_nats, connect_mock = self._make_fake_nats_module()
        with patch.dict(sys.modules, {"nats": fake_nats}):
            await connect_jetstream(
                servers=("nats://127.0.0.1:4222",),
                token="ephemeral-test-nats-token",
            )
            connect_mock.assert_awaited_once()
            _, kwargs = connect_mock.call_args
            self.assertEqual(kwargs.get("token"), "ephemeral-test-nats-token")
            self.assertNotIn("user_credentials", kwargs)

    async def test_unchanged_token_free_behavior(self) -> None:
        fake_nats, connect_mock = self._make_fake_nats_module()
        with patch.dict(sys.modules, {"nats": fake_nats}):
            await connect_jetstream(servers=("nats://127.0.0.1:4222",))
            connect_mock.assert_awaited_once()
            _, kwargs = connect_mock.call_args
            self.assertNotIn("token", kwargs)
            self.assertNotIn("user_credentials", kwargs)

    async def test_preserves_tls_and_credentials_when_token_omitted(self) -> None:
        fake_nats, connect_mock = self._make_fake_nats_module()
        sentinel_tls = object()
        with patch.dict(sys.modules, {"nats": fake_nats}):
            await connect_jetstream(
                servers=("nats://127.0.0.1:4222", "nats://127.0.0.1:4223"),
                credentials="/tmp/fake.creds",
                tls=sentinel_tls,
            )
            connect_mock.assert_awaited_once()
            _, kwargs = connect_mock.call_args
            self.assertNotIn("token", kwargs)
            self.assertEqual(kwargs.get("user_credentials"), "/tmp/fake.creds")
            self.assertIs(kwargs.get("tls"), sentinel_tls)
            self.assertEqual(
                 list(kwargs.get("servers", ())),
                ["nats://127.0.0.1:4222", "nats://127.0.0.1:4223"],
            )

    async def test_rejects_simultaneous_token_and_credentials(self) -> None:
        fake_nats, connect_mock = self._make_fake_nats_module()
        with patch.dict(sys.modules, {"nats": fake_nats}):
            with self.assertRaises(ValueError) as ctx:
                await connect_jetstream(
                    servers=("nats://127.0.0.1:4222",),
                    credentials="/tmp/secret.creds",
                    token="secret-token-value",
                )
            self.assertNotIn("secret-token-value", str(ctx.exception))
            self.assertNotIn("/tmp/secret.creds", str(ctx.exception))
            connect_mock.assert_not_awaited()
