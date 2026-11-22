"""Six-extension consistency checks; not lifecycle, authority or publication services."""
from datetime import datetime
from typing import Literal
from pydantic import Field

from app.application.common.contracts import _Frozen
from app.domain.operand.feature_graph import FeatureGraphRevision
from app.domain.operand.types import (CanonicalRef, CommercialOrderExtension, ConfigurationBinding,
    FeatureConfigurationExtension, ProjectExtension, SiteAcceptanceTestExtension, SubsystemExtension,
    WorkingDocumentExtension)
from app.domain.shared.versioning import VersionRef
from .contracts import ConfigurationRequest, ConfigurationResult
from .references import CanonicalReferencePort, OwnershipProfile, ResolutionReport, resolve_extensions
from .services import validate_configuration


class SixTypePacket(_Frozen):
    """Explicit supplied extension snapshots; canonical records are referenced, never embedded."""
    schema_version: Literal["currentcraft-six-type-packet/v2"] = Field(default="currentcraft-six-type-packet/v2", description="Packet of composed extensions; v1 subclass packets are not upgraded.")
    project: ProjectExtension = Field(description="Exact project extension snapshot.")
    document: WorkingDocumentExtension = Field(description="Exact working-document extension snapshot.")
    order: CommercialOrderExtension = Field(description="Exact commercial-order extension snapshot, not fulfillment proof.")
    subsystem: SubsystemExtension = Field(description="Exact subsystem extension snapshot.")
    test: SiteAcceptanceTestExtension = Field(description="Exact SAT extension snapshot, not acceptance authority.")
    configuration: FeatureConfigurationExtension = Field(description="Exact configuration extension being checked.")
    graph: FeatureGraphRevision = Field(description="Exact feature graph for the selected configuration.")

    def extensions(self):
        return (self.project, self.document, self.order, self.subsystem, self.test, self.configuration)


class SixTypeValidation(_Frozen):
    """Consistency receipt between extensions. Canonical existence and ownership are resolved separately."""
    schema_version: Literal["currentcraft-six-type-validation/v2"] = Field(default="currentcraft-six-type-validation/v2", description="Consistency result family for composed extensions.")
    project: CanonicalRef = Field(description="Exact canonical project every extension must reference.")
    configuration: ConfigurationBinding = Field(description="Exact configuration and model/selection pin checked.")
    checked_extensions: tuple[VersionRef, ...] = Field(description="Exact extension identities/versions checked, not current-head certification.")
    consistency: Literal["consistent", "incomplete"] = Field(description="Incomplete means missing optional bindings; neither value is readiness or release.")
    gaps: tuple[str, ...] = Field(description="Deterministic missing/inferred binding codes without source identifiers or labels.")
    analysis: ConfigurationResult = Field(description="Existing restricted feature-model outcome; independent of packet consistency.")
    grants_authority: Literal[False] = Field(default=False, description="This read-only receipt never authorizes work or changes state.")


def validate_six_type_packet(packet: SixTypePacket) -> SixTypeValidation:
    """Fail known inconsistencies between extensions; report missing evidence without upgrading it."""
    extensions = packet.extensions()
    ids = [e.extension_id for e in extensions]
    if len(set(ids)) != len(ids):
        raise ValueError("packet_identity_collision")
    canonical = {use.reference.identity for e in extensions for use in e.references()}
    if canonical & set(ids):
        raise ValueError("packet_identity_collision")
    project = packet.project.project
    for label, extension in zip(("document", "order", "subsystem", "test", "configuration"), extensions[1:]):
        if extension.project != project:
            raise ValueError(label + "_project_version_mismatch")
    binding = packet.configuration.binding()
    gaps = []

    def check_fact(fact, label):
        if fact.value is None:
            gaps.append(label + "_unknown")
        elif fact.value != binding:
            raise ValueError(label + "_configuration_mismatch")
        elif fact.epistemic_status != "observed":
            gaps.append(label + "_not_observed")

    check_fact(packet.project.configuration_baseline, "project_baseline")
    check_fact(packet.document.configuration, "document")
    check_fact(packet.order.requested_configuration, "order")
    check_fact(packet.subsystem.configuration, "subsystem")
    for line in packet.order.lines:
        check_fact(line.requested_configuration, "order_line")
    if packet.test.configuration != binding:
        raise ValueError("test_configuration_mismatch")
    if packet.test.observed_configuration.value is not None and packet.test.observed_configuration.value != binding:
        raise ValueError("test_observed_configuration_mismatch")
    if packet.document.captured_revision not in packet.test.basis:
        raise ValueError("test_document_revision_mismatch")
    if any(r.feature_id not in packet.configuration.selected for r in packet.subsystem.realizations):
        raise ValueError("realization_feature_not_selected")
    config = packet.configuration
    request = ConfigurationRequest(configuration_id=config.extension_id, graph_id=config.graph_id,
        graph_revision=config.graph_revision, graph_digest=config.graph_digest, selected=config.selected)
    analysis = validate_configuration(packet.graph, request)
    return SixTypeValidation(project=project, configuration=binding,
        checked_extensions=tuple(e.ref() for e in extensions),
        consistency="incomplete" if gaps else "consistent", gaps=tuple(sorted(set(gaps))), analysis=analysis)


def resolve_six_type_packet(packet: SixTypePacket, port: CanonicalReferencePort, profile: OwnershipProfile,
                            resolved_at: datetime) -> ResolutionReport:
    """Resolve every canonical reference in the packet through the explicit port and pinned standard."""
    return resolve_extensions(packet.extensions(), port, profile, resolved_at)


CONTRACTS = (SixTypePacket, SixTypeValidation)
