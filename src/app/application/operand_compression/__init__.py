"""Optional checked geometry, separate from six-domain feature analysis."""
from .contracts import CONTRACTS, OperandCompressionRequest, OperandCompressionResult, SCHEMA_VERSION
from .services import OperandCompressionService

__all__ = ["CONTRACTS", "OperandCompressionRequest", "OperandCompressionResult", "OperandCompressionService", "SCHEMA_VERSION"]
