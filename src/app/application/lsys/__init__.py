"""L-system expectation grammar: alphabet, digest-pinned profile loader and bounded growth.

Design: docs/domain/LSYS_DOMAIN_VOCABULARY.md. Grammar proposes, evidence disposes, gates decide.
"""
from .alphabet import LINKS, OBJECTS, RESOURCES, TERMINAL, VERBS, is_resource, link_for  # noqa: F401
from .contracts import (  # noqa: F401
    CONTRACTS, MAX_DEPTH, MAX_NODES, SCHEMA_VERSION, Derivation, Expectation, GrammarProfile, GrowthCount,
    PossibleNode, Production, ProductionLink, Unexpanded, grow, ladder_moves, load_profile, profile_digest,
)
