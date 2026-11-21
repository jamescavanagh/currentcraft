"""Stable source identities shared by CLI, HTTP and workbook ingestion.

Design: docs/architecture/HTTP_IDENTITY.md. Existing persisted ids must not drift.
"""
import hashlib

from .contracts import IntakeBinding


def source_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


def document_id(platform: str, source_id: str) -> str:
    return f"{platform}:xlsx:project_document:{source_key(platform, source_id)}"


def subject_reference_id(subject_kind: str, namespace: str, reference: str) -> str:
    binding = IntakeBinding(subject_kind=subject_kind, subject_namespace=namespace,
                            subject_ref=reference, document_type="reference")
    return f"ref:{binding.subject_kind}:{source_key(binding.subject_namespace, binding.subject_ref)}"
