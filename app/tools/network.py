"""Read-only network lookups that agents call as tools.

Plain functions over the database, independent of any agent framework: LangGraph and CrewAI wrap
the same functions, so comparisons between them are about orchestration, not about tools.

Everything returned is sent to the model, so results are compact on purpose: only the fields
that help a diagnosis, a cap on list sizes (with the total, so the model knows when a list was
cut), and a "found: false" answer with suggestions instead of an exception when a name is wrong.
"""

import re
from datetime import datetime

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Alarm, Circuit, Device, Link, Site

MAX_ALARMS = 50
MAX_CIRCUITS = 5
MAX_SUGGESTIONS = 5

# Most severe first; ties broken by the newest alarm.
_SEVERITY_RANK = case(
    {"critical": 1, "major": 2, "minor": 3, "warning": 4}, value=Alarm.severity, else_=5
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _alarm_dict(alarm: Alarm) -> dict:
    return {
        "id": alarm.id,
        "site": alarm.site_code,
        "device": alarm.device_hostname,
        "interface": alarm.interface,
        "type": alarm.alarm_type,
        "severity": alarm.severity,
        "message": alarm.message,
        "raised_at": _iso(alarm.raised_at),
    }


def _suggest(db: Session, column, text: str) -> list[str]:
    """Close matches for a name the model got slightly wrong ("rtr-norte-2", "Site Sur").

    Matches names containing every alphabetic part of the input, so a wrong number or
    separator still finds the right family of names.
    """
    words = [w for w in re.split(r"[^a-záéíóúñ]+", text.lower()) if len(w) >= 2]
    if not words:
        return []
    stmt = (
        select(column)
        .where(*(column.ilike(f"%{word}%") for word in words))
        .order_by(column)
        .limit(MAX_SUGGESTIONS)
    )
    return list(db.scalars(stmt))


def get_active_alarms(
    db: Session, site_code: str | None = None, device: str | None = None, limit: int = 20
) -> dict:
    """Active (not cleared) alarms, most severe first, optionally for one site and/or device."""
    limit = max(1, min(limit, MAX_ALARMS))
    stmt = select(Alarm, func.count().over().label("total")).where(Alarm.cleared_at.is_(None))
    if site_code:
        stmt = stmt.where(func.upper(Alarm.site_code) == site_code.strip().upper())
    if device:
        stmt = stmt.where(func.lower(Alarm.device_hostname) == device.strip().lower())
    stmt = stmt.order_by(_SEVERITY_RANK, Alarm.raised_at.desc()).limit(limit)

    rows = db.execute(stmt).all()
    total = rows[0].total if rows else 0
    return {
        "total_active": total,
        "returned": len(rows),
        "truncated": total > len(rows),
        "alarms": [_alarm_dict(row.Alarm) for row in rows],
    }


def get_device(db: Session, hostname: str) -> dict:
    """A device with its site, redundancy peer, links and count of active alarms."""
    device = db.scalars(
        select(Device).where(func.lower(Device.hostname) == hostname.strip().lower())
    ).one_or_none()
    if device is None:
        return {
            "found": False,
            "hostname": hostname,
            "suggestions": _suggest(db, Device.hostname, hostname),
        }

    site = db.get(Site, device.site_code)
    links = db.scalars(
        select(Link)
        .where(or_(Link.a_device == device.hostname, Link.b_device == device.hostname))
        .order_by(Link.id)
    ).all()
    active_alarms = db.scalar(
        select(func.count())
        .select_from(Alarm)
        .where(Alarm.device_hostname == device.hostname, Alarm.cleared_at.is_(None))
    )

    def link_view(link: Link) -> dict:
        # Always describe the link from this device's side.
        local_is_a = link.a_device == device.hostname
        return {
            "kind": link.kind,
            "local_interface": link.a_interface if local_is_a else link.b_interface,
            "remote_device": link.b_device if local_is_a else link.a_device,
            "remote_interface": link.b_interface if local_is_a else link.a_interface,
            "remote_description": link.b_description if local_is_a else None,
            "bundle": link.bundle,
            "status": link.status,
        }

    return {
        "found": True,
        "hostname": device.hostname,
        "role": device.role,
        "vendor": device.vendor,
        "model": device.model,
        "site": {"code": site.code, "name": site.name, "role": site.role},
        "redundancy_peer": device.redundancy_peer,
        "active_alarm_count": active_alarms,
        "links": [link_view(link) for link in links],
    }


def get_site(db: Session, site_code: str) -> dict:
    """A site with its devices and its active alarms counted by severity."""
    site = db.scalars(
        select(Site).where(func.upper(Site.code) == site_code.strip().upper())
    ).one_or_none()
    if site is None:
        return {
            "found": False,
            "site_code": site_code,
            "suggestions": _suggest(db, Site.code, site_code),
        }

    devices = db.execute(
        select(Device.hostname, Device.role)
        .where(Device.site_code == site.code)
        .order_by(Device.hostname)
    ).all()
    by_severity = db.execute(
        select(Alarm.severity, func.count())
        .where(Alarm.site_code == site.code, Alarm.cleared_at.is_(None))
        .group_by(Alarm.severity)
    ).all()
    return {
        "found": True,
        "code": site.code,
        "name": site.name,
        "role": site.role,
        "region": site.region,
        "customers_served": site.customers_served,
        "backup_power_hours": site.backup_power_hours,
        "devices": [{"hostname": d.hostname, "role": d.role} for d in devices],
        "active_alarms_by_severity": {severity: count for severity, count in by_severity},
    }


def find_circuits(db: Session, query: str) -> dict:
    """Customer circuits by circuit ID or (partial) customer name, with the alarms on each
    circuit's access port, so one call links a customer complaint to the network."""
    text = query.strip()
    circuits = db.scalars(
        select(Circuit)
        .where(
            or_(
                func.upper(Circuit.circuit_id) == text.upper(),
                Circuit.customer_name.ilike(f"%{text}%"),
            )
        )
        .order_by(Circuit.circuit_id)
        .limit(MAX_CIRCUITS)
    ).all()
    if not circuits:
        return {"found": False, "query": query, "circuits": []}

    # One query for the alarms of every matched access port.
    port_alarms = db.scalars(
        select(Alarm)
        .where(
            Alarm.cleared_at.is_(None),
            or_(
                *(
                    (Alarm.device_hostname == c.access_device)
                    & (Alarm.interface == c.access_interface)
                    for c in circuits
                )
            ),
        )
        .order_by(_SEVERITY_RANK, Alarm.raised_at.desc())
    ).all()

    def circuit_view(circuit: Circuit) -> dict:
        alarms = [
            _alarm_dict(a)
            for a in port_alarms
            if a.device_hostname == circuit.access_device
            and a.interface == circuit.access_interface
        ]
        return {
            "circuit_id": circuit.circuit_id,
            "customer": circuit.customer_name,
            "service": circuit.service,
            "site": circuit.site_code,
            "access_device": circuit.access_device,
            "access_interface": circuit.access_interface,
            "active_alarms_on_access_port": alarms,
        }

    return {"found": True, "query": query, "circuits": [circuit_view(c) for c in circuits]}
