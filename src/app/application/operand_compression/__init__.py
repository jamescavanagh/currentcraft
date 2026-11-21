"""Candidate cross-domain operand compression, reusing the gauge application contracts."""
from .contracts import OperandCompressionRequest, OperandCompressionResult, SCHEMA_VERSION
from .services import OperandCompressionService

__all__ = ["OperandCompressionRequest", "OperandCompressionResult", "OperandCompressionService", "SCHEMA_VERSION"]
