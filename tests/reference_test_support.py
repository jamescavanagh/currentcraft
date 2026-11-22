"""Explicit trusted primitive composition for existing synthetic extraction/store tests.

These tests do not certify hostile-input isolation. Production entry-point denial
and the opt-in real Linux gate live in test_reference_isolation.
"""
from app.infrastructure.ingest.reference_documents import build_bundle, write_bundle, load_bundle, hydrate_bundle


def trusted_ingest_and_hydrate(root, source_relative, source_handle, output_relative,
                               expected_source_sha256, profile, uow_factory, recorded_at):
    bundle = build_bundle(root, source_relative, source_handle, expected_source_sha256, profile)
    digest = write_bundle(root, output_relative, bundle)
    loaded = load_bundle(root, output_relative, digest, recorded_at)
    return bundle, hydrate_bundle(loaded, uow_factory, recorded_at)
