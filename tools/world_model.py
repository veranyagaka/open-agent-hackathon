"""Source-grounded, append-only World Model for StockWhy investigation profiles."""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _stable_id(*parts):
    digest = hashlib.sha256(_canonical_json(parts).encode("utf-8")).hexdigest()
    return f"wm_{digest[:24]}"


def build_snapshot(profile):
    """Normalize a profile into entities and provenance-bearing relationships."""
    facility_id = str(profile.get("facility_id", ""))
    commodity = str(profile.get("commodity", ""))
    month = str(profile.get("month", ""))
    facility_entity = _stable_id("facility", facility_id)
    commodity_entity = _stable_id("commodity", commodity)
    context_entity = _stable_id("investigation", facility_id, commodity, month)

    entities = {
        facility_entity: {
            "entity_id": facility_entity,
            "entity_type": "facility",
            "key": facility_id,
            "attributes": {"facility_id": facility_id},
            "provenance": [{"source": "investigation_request"}],
        },
        commodity_entity: {
            "entity_id": commodity_entity,
            "entity_type": "commodity",
            "key": commodity,
            "attributes": {"commodity": commodity},
            "provenance": [{"source": "investigation_request"}],
        },
        context_entity: {
            "entity_id": context_entity,
            "entity_type": "investigation",
            "key": f"{facility_id}/{commodity}/{month}",
            "attributes": {
                "facility_id": facility_id,
                "commodity": commodity,
                "month": month,
            },
            "provenance": [{"source": "investigation_request"}],
        },
    }
    relationships = []
    source_sets = (
        ("stock", ("stock_record", "stock_history")),
        ("orders", ("order_record", "prev_order_record", "all_orders")),
        ("payments", ("payments_history",)),
        ("facilities", ("facilities",)),
        ("web_notes", ("web_notes",)),
    )

    for source_table, profile_keys in source_sets:
        for profile_key in profile_keys:
            records = profile.get(profile_key, [])
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                record_id = record.get("id")
                identity = (
                    source_table,
                    str(record_id) if record_id is not None else _canonical_json(record),
                )
                entity_id = _stable_id("source_record", *identity)
                provenance = {
                    "source_table": source_table,
                    "source_record_id": (
                        str(record_id) if record_id is not None else None
                    ),
                    "citation_id": (
                        f"{source_table}#{record_id}"
                        if record_id is not None else None
                    ),
                    "profile_field": profile_key,
                }
                if entity_id not in entities:
                    entities[entity_id] = {
                        "entity_id": entity_id,
                        "entity_type": "source_record",
                        "key": provenance["citation_id"] or entity_id,
                        "attributes": record,
                        "provenance": [provenance],
                    }
                elif provenance not in entities[entity_id]["provenance"]:
                    entities[entity_id]["provenance"].append(provenance)

                targets = [context_entity]
                if str(record.get("facility_id", "")) == facility_id:
                    targets.append(facility_entity)
                if (
                    str(record.get("commodity") or "").lower() == commodity.lower()
                    or source_table == "web_notes"
                ):
                    targets.append(commodity_entity)
                for target in targets:
                    relationships.append({
                        "relationship_id": _stable_id(
                            "observed_in", entity_id, target, provenance
                        ),
                        "type": "observed_in",
                        "from_entity": entity_id,
                        "to_entity": target,
                        "provenance": provenance,
                    })

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "world_id": _stable_id("stockwhy_world", facility_id, commodity),
        "context": {
            "facility_id": facility_id,
            "commodity": commodity,
            "month": month,
        },
        "entities": sorted(entities.values(), key=lambda entity: entity["entity_id"]),
        "relationships": sorted(
            relationships, key=lambda relationship: relationship["relationship_id"]
        ),
    }
    snapshot["snapshot_id"] = _stable_id("snapshot", snapshot)
    return snapshot


class WorldModelStore:
    """SQLite event log with stable snapshot IDs and idempotent append."""

    def __init__(self, database_path=None):
        self.database_path = database_path or os.getenv(
            "STOCKWHY_WORLD_MODEL_DB", "logs/stockwhy_world_model.sqlite3"
        )
        self._memory_connection = (
            sqlite3.connect(":memory:")
            if self.database_path == ":memory:"
            else None
        )
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world_events (
                    event_id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS world_events_world_id "
                "ON world_events(world_id, created_at)"
            )

    def _connect(self):
        return self._memory_connection or sqlite3.connect(self.database_path)

    def append_snapshot(self, snapshot):
        if snapshot.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported World Model schema version.")
        if not snapshot.get("snapshot_id") or not snapshot.get("world_id"):
            raise ValueError("World Model snapshots require stable IDs.")
        if any(
            not entity.get("provenance")
            for entity in snapshot.get("entities", [])
        ):
            raise ValueError("World Model entities require provenance.")

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO world_events
                    (event_id, world_id, schema_version, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot["snapshot_id"],
                    snapshot["world_id"],
                    SCHEMA_VERSION,
                    "snapshot",
                    _canonical_json(snapshot),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return snapshot["snapshot_id"]

    def query_snapshots(self, world_id, limit=50):
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("World Model query limit must be a positive integer.")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM world_events
                WHERE world_id = ? AND event_type = 'snapshot'
                ORDER BY created_at DESC, event_id DESC
                LIMIT ?
                """,
                (world_id, limit),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]


def persist_snapshot(profile, database_path=None):
    snapshot = build_snapshot(profile)
    WorldModelStore(database_path).append_snapshot(snapshot)
    return snapshot
