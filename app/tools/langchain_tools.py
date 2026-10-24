"""The network tools (app/tools/network.py) wrapped for LangChain and LangGraph agents.

The model decides which tool to call from its name, docstring and argument descriptions, so
those are written for the model. Each call opens its own short database session, and results are
compact JSON to keep the tokens sent back to the model low.
"""

import json
from collections.abc import Callable
from contextlib import AbstractContextManager

from langchain_core.tools import BaseTool, tool
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.tools import network

SessionFactory = Callable[[], AbstractContextManager[Session]]


def _compact(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def build_network_tools(session_factory: SessionFactory = SessionLocal) -> list[BaseTool]:
    """LangChain tools bound to a database session factory (tests pass their own)."""

    @tool(parse_docstring=True)
    def get_active_alarms(
        site_code: str | None = None, device: str | None = None, limit: int = 20
    ) -> str:
        """Active (not cleared) network alarms, most severe first.

        Use it to see what the network itself reports for a site or device mentioned in a
        ticket, or with no filters for the whole network. Cleared alarms are not included.

        Args:
            site_code: Site code such as "SITE-SUR-02". Optional.
            device: Device hostname such as "rtr-sur-02". Optional.
            limit: Maximum number of alarms to return (1-50).
        """
        with session_factory() as db:
            return _compact(network.get_active_alarms(db, site_code, device, limit))

    @tool(parse_docstring=True)
    def get_device(hostname: str) -> str:
        """A device's role, site, redundancy peer, links (with the far end and status of each)
        and number of active alarms.

        Use it to understand what a device connects to and whether a failed link or device has
        a redundant path. If the hostname is wrong, the answer suggests close matches.

        Args:
            hostname: Device hostname such as "sw-este-04".
        """
        with session_factory() as db:
            return _compact(network.get_device(db, hostname))

    @tool(parse_docstring=True)
    def get_site(site_code: str) -> str:
        """A site's role, customers served, backup power autonomy, devices and active alarms
        counted by severity.

        Use it to judge the impact of an incident on a site. If the code is wrong, the answer
        suggests close matches.

        Args:
            site_code: Site code such as "SITE-ESTE-04".
        """
        with session_factory() as db:
            return _compact(network.get_site(db, site_code))

    @tool(parse_docstring=True)
    def find_circuits(query: str) -> str:
        """Customer circuits by circuit ID or customer name (partial names work), each with its
        access device, access port and the active alarms on that port.

        Use it first when a customer reports a problem: it links the customer to the part of
        the network that serves them.

        Args:
            query: Circuit ID such as "SUR-2210" or part of a customer name such as "Distribuidora".
        """
        with session_factory() as db:
            return _compact(network.find_circuits(db, query))

    return [get_active_alarms, get_device, get_site, find_circuits]
