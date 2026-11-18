"""Unit tests for the FastAPI HTTP shell endpoints, error safety, and lifespan."""

from __future__ import annotations

import asyncio
import unittest
from fastapi.testclient import TestClient

from app.interfaces.http.app import create_app
from app.interfaces.http.container import Container
from app.interfaces.http.settings import Settings

SENTINEL_API_TOKEN = "sentinel-api-secret-998877"
SENTINEL_NATS_TOKEN = "sentinel-nats-secret-665544"
SENTINEL_DSN = "postgresql://127.0.0.1:5433/datamesh_sentinel_db"
SENTINEL_PATH = "/tmp/secret/sentinel_token_file"


def _make_settings(
    api_token: str = SENTINEL_API_TOKEN,
    timeout: float = 0.05,
) -> Settings:
    return Settings(
        pg_dsn=SENTINEL_DSN,
        nats_servers=("nats://127.0.0.1:4222",),
        nats_token=SENTINEL_NATS_TOKEN,
        api_token=api_token,
        dependency_timeout_seconds=timeout,
    )


class TestHttpApi(unittest.TestCase):
    def _assert_no_leaks(self, text: str) -> None:
        for forbidden in (
            SENTINEL_API_TOKEN,
            SENTINEL_NATS_TOKEN,
            SENTINEL_DSN,
            "sentinel-pg-pass",
            "datamesh_sentinel_db",
            SENTINEL_PATH,
        ):
            self.assertNotIn(forbidden, text)

    def test_openapi_generation_never_invokes_container_factory(self) -> None:
        called = False

        async def _factory() -> Container:
            nonlocal called
            called = True
            raise AssertionError("Container factory must not be called for OpenAPI")

        app = create_app(container_factory=_factory)
        schema = app.openapi()
        self.assertFalse(called)
        self.assertIn("/healthz", schema["paths"])
        self.assertIn("/readyz", schema["paths"])
        self.assertIn("/v1/auth/check", schema["paths"])
        self.assertIn(
            "503",
            schema["paths"]["/readyz"]["get"]["responses"],
        )

    def test_healthz_is_200_and_calls_no_dependency_callbacks(self) -> None:
        db_called = False
        broker_called = False
        closed = False

        async def db_ready() -> bool:
            nonlocal db_called
            db_called = True
            return False

        async def broker_ready() -> bool:
            nonlocal broker_called
            broker_called = True
            return False

        async def close() -> None:
            nonlocal closed
            closed = True

        async def factory() -> Container:
            return Container(
                settings=_make_settings(),
                database_ready=db_ready,
                broker_ready=broker_ready,
                close=close,
            )

        with TestClient(create_app(factory)) as client:
            resp = client.get("/healthz")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"status": "ok"})
            self.assertFalse(db_called)
            self.assertFalse(broker_called)

        self.assertTrue(closed)

    def test_readyz_is_200_when_both_checks_pass(self) -> None:
        closed = False

        async def ok() -> bool:
            return True

        async def close() -> None:
            nonlocal closed
            closed = True

        async def factory() -> Container:
            return Container(_make_settings(), ok, ok, close)

        with TestClient(create_app(factory)) as client:
            resp = client.get("/readyz")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                resp.json(),
                {"status": "ready", "postgres": True, "nats": True},
            )
            self._assert_no_leaks(resp.text)

        self.assertTrue(closed)

    def test_readyz_is_503_when_either_dependency_fails_raises_or_times_out(self) -> None:
        async def ok() -> bool:
            return True

        async def fail() -> bool:
            return False

        async def explode() -> bool:
            raise RuntimeError(f"driver error {SENTINEL_DSN} {SENTINEL_PATH}")

        async def slow() -> bool:
            await asyncio.sleep(0.5)
            return True

        async def noop() -> None:
            return None

        cases = [
            (fail, ok, False, True),
            (ok, fail, True, False),
            (fail, fail, False, False),
            (explode, ok, False, True),
            (ok, explode, True, False),
            (slow, ok, False, True),
            (ok, slow, True, False),
        ]
        for db_cb, brk_cb, exp_pg, exp_nats in cases:
            with self.subTest(db=db_cb.__name__, broker=brk_cb.__name__):
                async def factory(d=db_cb, b=brk_cb) -> Container:
                    return Container(_make_settings(timeout=0.02), d, b, noop)

                with TestClient(create_app(factory)) as client:
                    resp = client.get("/readyz")
                    self.assertEqual(resp.status_code, 503)
                    self.assertEqual(
                        resp.json(),
                        {
                            "status": "not_ready",
                            "postgres": exp_pg,
                            "nats": exp_nats,
                        },
                    )
                    self._assert_no_leaks(resp.text)

    def test_auth_check_returns_401_for_absent_or_wrong_and_200_for_valid(self) -> None:
        async def ok() -> bool:
            return True

        async def noop() -> None:
            return None

        async def factory() -> Container:
            return Container(_make_settings(), ok, ok, noop)

        with TestClient(create_app(factory)) as client:
            missing = client.get("/v1/auth/check")
            self.assertEqual(missing.status_code, 401)
            self.assertEqual(missing.headers.get("WWW-Authenticate"), "Bearer")
            self.assertEqual(
                missing.json(),
                {"error": "unauthorized", "detail": "Invalid authentication."},
            )
            self._assert_no_leaks(missing.text)

            non_bearer = client.get(
                "/v1/auth/check",
                headers={"Authorization": f"Basic {SENTINEL_API_TOKEN}"},
            )
            self.assertEqual(non_bearer.status_code, 401)
            self.assertEqual(non_bearer.headers.get("WWW-Authenticate"), "Bearer")
            self._assert_no_leaks(non_bearer.text)

            wrong = client.get(
                "/v1/auth/check",
                headers={"Authorization": "Bearer wrong-candidate-secret"},
            )
            self.assertEqual(wrong.status_code, 401)
            self.assertEqual(wrong.headers.get("WWW-Authenticate"), "Bearer")
            self.assertNotIn("wrong-candidate-secret", wrong.text)
            self._assert_no_leaks(wrong.text)

            valid = client.get(
                "/v1/auth/check",
                headers={"Authorization": f"Bearer {SENTINEL_API_TOKEN}"},
            )
            self.assertEqual(valid.status_code, 200)
            self.assertEqual(valid.json(), {"authenticated": True})
            self._assert_no_leaks(valid.text)

    def test_missing_configured_token_returns_503_in_injected_container(self) -> None:
        async def ok() -> bool:
            return True

        async def noop() -> None:
            return None

        async def factory() -> Container:
            return Container(_make_settings(api_token=""), ok, ok, noop)

        with TestClient(create_app(factory)) as client:
            resp = client.get(
                "/v1/auth/check",
                headers={"Authorization": f"Bearer {SENTINEL_API_TOKEN}"},
            )
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(
                resp.json(),
                {
                    "error": "service_unavailable",
                    "detail": "Service is currently unavailable.",
                },
            )
            self._assert_no_leaks(resp.text)

    def test_validation_and_unexpected_errors_never_leak_secrets_or_inputs(self) -> None:
        async def ok() -> bool:
            return True

        async def noop() -> None:
            return None

        async def factory() -> Container:
            return Container(_make_settings(), ok, ok, noop)

        app = create_app(factory)

        @app.get("/_test/validate")
        def _validate(limit: int) -> dict[str, int]:
            return {"limit": limit}

        @app.get("/_test/crash")
        def _crash() -> None:
            raise RuntimeError(
                f"fatal {SENTINEL_DSN} {SENTINEL_API_TOKEN} {SENTINEL_PATH}"
            )

        with TestClient(app, raise_server_exceptions=False) as client:
            bad_val = client.get(
                "/_test/validate",
                params={"limit": f"not-an-int-{SENTINEL_API_TOKEN}"},
            )
            self.assertEqual(bad_val.status_code, 422)
            self.assertEqual(bad_val.json()["error"], "validation_error")
            self._assert_no_leaks(bad_val.text)

            crash = client.get("/_test/crash")
            self.assertEqual(crash.status_code, 500)
            self.assertEqual(
                crash.json(),
                {
                    "error": "internal_error",
                    "detail": "An unexpected internal error occurred.",
                },
            )
            self._assert_no_leaks(crash.text)
