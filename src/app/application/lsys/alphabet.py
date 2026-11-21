"""The public grammar alphabet: domain object kinds, verbs and the typed links growth may expect.

Design: docs/domain/LSYS_DOMAIN_VOCABULARY.md. Symbols name ``app.domain`` classes only. Resources
(every ``Resource`` subclass and the base itself) are never symbols; they bind to executions through
``CapabilityBinding``. A link names an existing typed field; no hierarchy is inferred.
"""
from __future__ import annotations

from typing import Literal

from app.domain.commercial.commercial_order import Order
from app.domain.document.document import Document
from app.domain.employee.employee_entity import Employee
from app.domain.estimation.need import Need
from app.domain.estimation.scope import Scope
from app.domain.geography.location import Location
from app.domain.logistics.shipment import Shipment, ShipmentLine
from app.domain.materials.bom import BOM
from app.domain.materials.bom_line import BOMLine
from app.domain.parties.client import Client
from app.domain.parties.party import Party
from app.domain.parties.vendor import Vendor
from app.domain.product.asset_instance import AssetInstance
from app.domain.product.product_definition import ProductDefinition
from app.domain.project.project_entity import Project
from app.domain.project.project_phase import Phase
from app.domain.project.subsystem import Subsystem
from app.domain.project.wbs import WBS
from app.domain.task.task_entity import Task
from app.domain.workforce.agent import Agent
from app.domain.workforce.contributor import Contributor
from app.domain.workforce.resource import Resource

TERMINAL = "o"
"""Any non-resource object id in an ``ObjectIncidence``; never rewritten."""

OBJECTS: dict[str, type] = {cls.__name__: cls for cls in (
    Project, Phase, WBS, Task, Subsystem, Location, AssetInstance, ProductDefinition, BOM, BOMLine,
    Shipment, ShipmentLine, Document, Order, Party, Client, Vendor, Need, Scope)}
"""Domain object kinds a profile may name. Drawing, TimeCard and other scaffolds are not symbols yet."""

GrammarVerb = Literal["produces", "consumes", "reads", "revises", "holds", "transfers", "checks", "impedance_match"]
VERBS: tuple[str, ...] = GrammarVerb.__args__
"""The seven process effects plus the candidate ``impedance_match``. Gate decisions are not verbs."""

# (parent symbol, child symbol) -> "Holder.field": the typed field that records the link.
LINKS: dict[tuple[str, str], str] = {
    ("Project", "Phase"): "Phase.project_id",
    ("Project", "WBS"): "WBS.project_id",
    ("Project", "Task"): "Task.project_id",
    ("Project", "Subsystem"): "Subsystem.project_id",
    ("Project", "Location"): "Location.project_id",
    ("Project", "AssetInstance"): "AssetInstance.project_id",
    ("Project", "BOM"): "BOM.project_id",
    ("Project", "Shipment"): "Shipment.project_id",
    ("Project", "Document"): "Document.project_id",
    ("Project", "Order"): "Order.project_id",
    ("Project", "Need"): "Need.project_id",
    ("Project", "Scope"): "Scope.project_id",
    ("Location", "Subsystem"): "Subsystem.location_id",
    ("Location", "Task"): "Task.location_id",
    ("Subsystem", "Task"): "Task.subsystem_id",
    ("Phase", "Task"): "Task.phase_id",
    ("WBS", "Task"): "Task.wbs_id",
    ("BOM", "BOMLine"): "BOMLine.bom_id",
    ("ProductDefinition", "AssetInstance"): "AssetInstance.product_definition_id",
    ("ProductDefinition", "BOMLine"): "BOMLine.product_definition_id",
    ("Shipment", "ShipmentLine"): "ShipmentLine.shipment_id",
    ("Need", "Document"): "Need.document_ids",
    ("Document", "Scope"): "Scope.document_id",
    ("Document", "Order"): "Order.document_ids",
}


def _subclasses(cls: type) -> set[type]:
    out: set[type] = set()
    for sub in cls.__subclasses__():
        out |= {sub} | _subclasses(sub)
    return out


# Importing the resource modules above registers them; the set is discovered, never hand-kept.
_ = (Employee, Contributor, Agent)
RESOURCES: frozenset[str] = frozenset({"Resource"} | {c.__name__ for c in _subclasses(Resource)})


def fold(symbol: str) -> str:
    """Matching form: trimmed and case-folded, so spelling variants of a resource are still caught."""
    return symbol.strip().casefold()


_FOLDED_RESOURCES = frozenset(fold(r) for r in RESOURCES)


def is_resource(symbol: str) -> bool:
    """True when the symbol names a resource in any spelling variant."""
    return fold(symbol) in _FOLDED_RESOURCES


def link_for(parent: str, child: str) -> str | None:
    """The typed field recording parent -> child, or None when no such link exists (a gap)."""
    if child == TERMINAL:
        return None
    return LINKS.get((parent, child))
