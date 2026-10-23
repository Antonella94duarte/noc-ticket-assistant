"""Load the synthetic network snapshot (sites, devices, links, circuits, alarms).

The network tables are reference data for the agents, so loading replaces their whole content
in one transaction; the `tickets` table is never touched.

    python -m app.db.seed
"""

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, insert, update
from sqlalchemy.orm import Session

from app.db.models import Alarm, Circuit, Device, Link, Site

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "network" / "seed.json"


def _utc(value: str | None) -> datetime | None:
    # Python 3.10's fromisoformat doesn't accept the "Z" suffix.
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _timestamps(row: dict) -> dict:
    return {**row, "raised_at": _utc(row["raised_at"]), "cleared_at": _utc(row["cleared_at"])}


def load_network_seed(db: Session, path: Path = SEED_PATH) -> dict[str, int]:
    """Replace the network tables with the snapshot in `path`. Returns row counts per table."""
    data = json.loads(path.read_text(encoding="utf-8"))

    # Children first because of the foreign keys.
    for model in (Alarm, Circuit, Link, Device, Site):
        db.execute(delete(model))

    # Bulk inserts in foreign-key order: one statement per table.
    db.execute(insert(Site), data["sites"])
    # Devices reference each other as redundancy peers: insert them without the peer first.
    db.execute(insert(Device), [{**row, "redundancy_peer": None} for row in data["devices"]])
    for row in data["devices"]:
        if row["redundancy_peer"]:
            db.execute(
                update(Device)
                .where(Device.hostname == row["hostname"])
                .values(redundancy_peer=row["redundancy_peer"])
            )
    db.execute(insert(Link), data["links"])
    db.execute(insert(Circuit), data["circuits"])
    db.execute(insert(Alarm), [_timestamps(row) for row in data["alarms"]])
    return {name: len(data[name]) for name in ("sites", "devices", "links", "circuits", "alarms")}


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        counts = load_network_seed(db)
        db.commit()
    print("Loaded network seed:", ", ".join(f"{n} {name}" for name, n in counts.items()))


if __name__ == "__main__":
    main()
