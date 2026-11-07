"""Self-registration: at startup each node upserts its row in `nodes`, keyed by IPv4."""

import ipaddress
import logging
import os
import re
import socket

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .models import Node
from .utils import run

log = logging.getLogger("uvicorn.error")


def detect_ipv4() -> str:
    """The source address the host uses for outbound traffic (`ip -4 route get 1.1.1.1`)."""
    m = re.search(r"\bsrc (\S+)", run(config.IP, "-4", "route", "get", "1.1.1.1"))
    ip = m[1] if m else ""
    try:
        return str(ipaddress.IPv4Address(ip))
    except ValueError:
        raise RuntimeError(f"could not find this node's IPv4 (got {ip!r})")


def register(db: Session) -> Node:
    ipv4 = detect_ipv4()
    node = db.scalar(select(Node).where(Node.ipv4 == ipv4))
    if node is None:
        node = Node(ipv4=ipv4)
        db.add(node)
    node.hostname = socket.gethostname()  # the VM's hostname (docker-compose uses uts: host)
    node.port = int(os.environ.get("PORT", "8025"))
    node.environment = config.APP_ENV
    node.last_started_at = func.now()
    db.commit()
    log.info("registered %s node %s (%s)", node.environment, node.ipv4, node.hostname)
    return node
