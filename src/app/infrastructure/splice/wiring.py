"""Composition root for the splice slice."""

from __future__ import annotations

from app.application.splice.services import SpliceService

from .kernels import NumpySpliceKernel


def build_splice() -> SpliceService:
    return SpliceService(NumpySpliceKernel())
