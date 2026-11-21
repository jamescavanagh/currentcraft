"""Parser-version and disk-isolation regressions for the intake CI repair."""

import asyncio
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import Headers

from app.interfaces.http.routes import intake
from tests import test_http_intake as fixtures


class ParserLimitTests(unittest.TestCase):
    def test_framework_wrapped_native_header_limit_is_413(self):
        class Request:
            headers = Headers({"content-type": "multipart/form-data; boundary=synthetic"})
        for message, status in [("Maximum header size exceeded", 413),
                                ("Maximum header count exceeded", 413),
                                ("synthetic invalid input", 422)]:
            async def fail(parser):
                try:
                    raise MultipartParseError(message)
                except MultipartParseError as cause:
                    raise intake.MultiPartException("Invalid multipart data.") from cause
            with self.subTest(message=message), patch.object(intake.BoundedParser, "parse", new=fail):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(intake._form(Request()))
                self.assertEqual(raised.exception.status_code, status)

    def test_parser_native_header_limits_are_safe_413_and_close_spools(self):
        fixture = fixtures.HttpIntakeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        class Request:
            headers = Headers({"content-type": "multipart/form-data; boundary=synthetic"})

        cases = [("Maximum header size exceeded", 413),
                 ("Maximum header count exceeded", 413),
                 (fixtures.SOURCE + " /private/path " + fixtures.TOKEN, 422)]
        for message, status in cases:
            created = []
            async def fail(parser):
                handle = tempfile.SpooledTemporaryFile()
                created.append(handle)
                parser._files_to_close_on_error.append(handle)
                raise MultipartParseError(message)
            with self.subTest(status=status), patch.object(intake.BoundedParser, "parse", new=fail):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(intake._form(Request()))
                self.assertEqual(raised.exception.status_code, status)
                self.assertTrue(all(f.closed for f in created))
                response = fixture.post()
                self.assertEqual(response.status_code, status)
                for secret in (fixtures.SOURCE, fixtures.TOKEN, "/private/path", message):
                    self.assertNotIn(secret, response.text)

    def test_wiring_repository_test_never_initializes_default_disk_storage(self):
        from tests.test_http_documents import ReadWiringTests
        from app.interfaces.http import wiring
        with patch.object(wiring, "DirectoryBlobStore", side_effect=AssertionError("unexpected disk access")), \
                patch.object(wiring, "SqliteIntakeReceipts", side_effect=AssertionError("unexpected disk access")):
            result = unittest.TestResult()
            ReadWiringTests("test_composition_root_supplies_existing_repository_factory").run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
