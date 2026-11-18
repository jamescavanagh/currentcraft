"""Run after installation: python examples/domain_bootstrap.py. Synthetic data only."""
import json
from pathlib import Path
from app.application.enterprise.services import capture_snapshot, restore_snapshot, request_transition
from app.infrastructure.enterprise.wiring import build_fixture
from app.infrastructure.persistence.memory import MemoryStore


def main():
    snapshot = build_fixture(Path(__file__).resolve().parents[1] / "references")
    store = MemoryStore()
    saved = capture_snapshot(store, snapshot)
    restored = restore_snapshot(store, snapshot.snapshot_id)
    if restored != snapshot:
        raise RuntimeError("snapshot round-trip differs")
    blocked = None
    try:
        request_transition(restored, restored.executions[0].execution.execution_id, "Executable")
    except PermissionError as exc:
        blocked = str(exc)
    if blocked is None:
        raise RuntimeError("undefined transition unexpectedly allowed")
    with store() as uow:
        events = uow.outbox.pending()
    print(json.dumps({"purpose": snapshot.purpose, "records": len(snapshot.records),
        "executions": len(snapshot.executions), "stored_version": saved.version,
        "round_trip": "passed", "outbox_events": len(events),
        "event_status": events[0].envelope["epistemic_status"], "transition": blocked},
        indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
