"""Evaluation harness (0.11.0): retrieval, edge and absence-state metrics over labeled judgments.

Design: docs/architecture/EVALUATION.md.
"""
from .contracts import *  # noqa: F401,F403
from .contracts import CONTRACTS, SCHEMA_VERSION  # noqa: F401
from .metrics import absence_metrics, edge_metrics, evaluate, mrr, ndcg_at_k, recall_at_k  # noqa: F401
