"""Six-type consistency checks; not lifecycle, authority or publication services."""
from typing import Literal
from pydantic import Field

from app.application.common.contracts import _Frozen
from app.domain.operand.feature_graph import FeatureGraphRevision
from app.domain.operand.types import (CommercialOrderType, ConfigurationBinding, FeatureConfigurationType,
    ProjectType, SiteAcceptanceTestType, SubsystemType, WorkingDocumentType, record_ref)
from app.domain.shared.versioning import VersionRef
from .contracts import ConfigurationRequest, ConfigurationResult
from .services import validate_configuration


class SixTypePacket(_Frozen):
    """Explicit supplied snapshots; no implicit repository lookup or current-head claim."""
    schema_version: Literal["currentcraft-six-type-packet/v1"] = Field(default="currentcraft-six-type-packet/v1", description="Independent packet contract; canonical payloads remain unchanged.")
    project: ProjectType = Field(description="Exact project baseline snapshot.")
    document: WorkingDocumentType = Field(description="Exact evidence-bearing working-document snapshot.")
    order: CommercialOrderType = Field(description="Exact commercial-order snapshot, not fulfillment proof.")
    subsystem: SubsystemType = Field(description="Exact architecture/component snapshot.")
    test: SiteAcceptanceTestType = Field(description="Exact SAT execution/basis snapshot, not acceptance authority.")
    configuration: FeatureConfigurationType = Field(description="Exact configuration object/version being checked.")
    graph: FeatureGraphRevision = Field(description="Exact feature graph for the selected configuration.")


class SixTypeValidation(_Frozen):
    """Consistency receipt: compatible model, source truth and release remain separate."""
    schema_version: Literal["currentcraft-six-type-validation/v1"] = Field(default="currentcraft-six-type-validation/v1", description="Independent six-type consistency result family.")
    project: VersionRef = Field(description="Exact project snapshot checked.")
    configuration: ConfigurationBinding = Field(description="Exact configuration and model/selection pin checked.")
    checked_records: tuple[VersionRef, ...] = Field(description="Exact supplied record versions checked, not current-head certification.")
    consistency: Literal["consistent", "incomplete"] = Field(description="Incomplete means missing optional bindings; neither value is readiness or release.")
    gaps: tuple[str, ...] = Field(description="Deterministic missing/inferred binding codes without source identifiers or labels.")
    analysis: ConfigurationResult = Field(description="Existing restricted feature-model outcome; independent of packet consistency.")
    grants_authority: Literal[False] = Field(default=False, description="This read-only receipt never authorizes work or changes state.")


def validate_six_type_packet(packet: SixTypePacket) -> SixTypeValidation:
    """Fail known inconsistencies; report missing evidence without upgrading it."""
    records = (packet.project, packet.document, packet.order, packet.subsystem, packet.test, packet.configuration)
    if len({record.entity_id for record in records}) != len(records):
        raise ValueError("packet_identity_collision")
    project = record_ref(packet.project)
    binding = packet.configuration.binding()
    gaps = []
    for label in ("document", "order", "subsystem"):
        record = getattr(packet, label)
        if (record.project_id, record.project_revision) != (project.identity, project.version):
            raise ValueError(label + "_project_version_mismatch")
    for label in ("configuration", "test"):
        if getattr(packet, label).project != project:
            raise ValueError(label + "_project_version_mismatch")

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
    request = ConfigurationRequest(configuration_id=config.entity_id, graph_id=config.graph_id,
        graph_revision=config.graph_revision, graph_digest=config.graph_digest, selected=config.selected)
    analysis = validate_configuration(packet.graph, request)
    records = (packet.project, packet.document, packet.order, packet.subsystem, packet.test, config)
    return SixTypeValidation(project=project, configuration=binding,
        checked_records=tuple(record_ref(record) for record in records),
        consistency="incomplete" if gaps else "consistent", gaps=tuple(sorted(set(gaps))), analysis=analysis)


CONTRACTS = (SixTypePacket, SixTypeValidation)
