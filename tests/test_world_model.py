import pytest

from tools.world_model import WorldModelStore, build_snapshot


def _profile():
    return {
        "facility_id": "FAC-001",
        "commodity": "oxytocin",
        "month": "2026-03",
        "stock_record": [{
            "id": "12",
            "facility_id": "FAC-001",
            "commodity": "oxytocin",
            "month": "2026-03",
            "closing": 0,
        }],
        "stock_history": [{
            "id": "12",
            "facility_id": "FAC-001",
            "commodity": "oxytocin",
            "month": "2026-03",
            "closing": 0,
        }],
        "order_record": [{
            "id": "17",
            "facility_id": "FAC-001",
            "commodity": "oxytocin",
            "month": "2026-02",
            "qty_requested": 10,
        }],
        "prev_order_record": [],
        "all_orders": [],
        "payments_history": [],
        "facilities": [{
            "facility_id": "FAC-001",
            "lat": -1.2,
            "lon": 36.8,
        }],
        "web_notes": [],
    }


def test_world_model_has_stable_ids_and_source_provenance():
    snapshot = build_snapshot(_profile())
    repeated = build_snapshot(_profile())

    assert snapshot["snapshot_id"] == repeated["snapshot_id"]
    assert snapshot["world_id"] == repeated["world_id"]
    stock_records = [
        entity for entity in snapshot["entities"]
        if entity.get("entity_type") == "source_record"
        and entity.get("key") == "stock#12"
    ]
    assert len(stock_records) == 1
    assert stock_records[0]["attributes"]["closing"] == 0
    assert {
        provenance["source_table"]
        for provenance in stock_records[0]["provenance"]
    } == {"stock"}
    assert any(
        relationship["from_entity"] == stock_records[0]["entity_id"]
        for relationship in snapshot["relationships"]
    )


def test_world_model_persistence_is_append_only_and_idempotent(tmp_path):
    snapshot = build_snapshot(_profile())
    database_path = tmp_path / "world-model.sqlite3"
    store = WorldModelStore(database_path)

    assert store.append_snapshot(snapshot) == snapshot["snapshot_id"]
    assert store.append_snapshot(snapshot) == snapshot["snapshot_id"]

    persisted = WorldModelStore(database_path).query_snapshots(snapshot["world_id"])
    assert len(persisted) == 1
    assert persisted[0] == snapshot


def test_world_model_rejects_entities_without_provenance():
    snapshot = build_snapshot(_profile())
    snapshot["entities"][0]["provenance"] = []
    store = WorldModelStore(":memory:")

    with pytest.raises(ValueError, match="require provenance"):
        store.append_snapshot(snapshot)
