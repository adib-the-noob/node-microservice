"""Building messages, reading delivery status from the journal, making DKIM keys."""

import base64
import re
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from fastapi import HTTPException

from . import config
from .schemas import MailIn
from .utils import run


def build_message(req: MailIn) -> EmailMessage:
    """The MIME message. Bcc is left out: it goes on the envelope only."""
    msg = EmailMessage()
    msg["From"] = Address(req.from_name, addr_spec=req.sender)
    msg["To"] = ", ".join(req.to)
    if req.cc:
        msg["Cc"] = ", ".join(req.cc)
    if req.reply_to:
        msg["Reply-To"] = req.reply_to
    msg["Subject"] = req.subject
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid(domain=req.sender.split("@")[1])
    for name, value in req.headers.items():
        msg[name] = value
    if req.text:
        msg.set_content(req.text)
    if req.html:
        if req.text:
            msg.add_alternative(req.html, subtype="html")
        else:
            msg.set_content(req.html, subtype="html")
    try:
        for a in req.attachments:
            maintype, subtype = a.content_type.split("/", 1)
            msg.add_attachment(base64.b64decode(a.content_base64, validate=True),
                               maintype=maintype, subtype=subtype, filename=a.filename)
    except ValueError as exc:
        raise HTTPException(422, f"bad attachment: {exc}")
    return msg


def journal(pattern: str, idents: list[str], since_hours: int) -> list[str]:
    tags = [x for i in idents for x in ("-t", i)]
    out = run(config.JOURNALCTL, "--no-pager", "-o", "cat", "--since", f"-{since_hours}h", "-g", pattern, *tags,
              ok=(0, 1))  # 1 = nothing matched
    return [ln for ln in out.splitlines() if ln and not ln.startswith("-- ")]


def delivery_status(message_id: str, since_hours: int) -> dict | None:
    """postfix/cleanup logs "<QID>: message-id=<...>"; the lines for that QID give the outcome."""
    lines = journal(f"message-id=<{re.escape(message_id)}>", ["postfix/cleanup"], since_hours)
    qids = [m[1] for ln in lines if (m := re.match(r"([0-9A-Za-z]+): message-id=", ln))]
    if not qids:
        return None
    qid = qids[-1]
    log = journal(f"^{qid}: ", ["postfix/pickup", "postfix/cleanup", "postfix/qmgr", "postfix/smtp",
                                "postfix/bounce", "postfix/error", "postfix/local", "opendkim"], since_hours)

    recipients, dkim = {}, {"signed": False}
    for ln in log:
        if m := re.search(r"\bto=<([^>]*)>.*?\bdsn=([\d.]+), status=(\w+)", ln):
            recipients[m[1]] = {"recipient": m[1], "dsn": m[2], "status": m[3]}  # later lines win
        elif m := re.search(r"DKIM-Signature field added \(s=([^,]+), d=([^)]+)\)", ln):
            dkim = {"signed": True, "selector": m[1], "domain": m[2]}

    statuses = {r["status"] for r in recipients.values()}
    status = "queued" if not statuses else statuses.pop() if len(statuses) == 1 else "partial"
    return {"queue_id": qid, "status": status, "dkim": dkim, "recipients": list(recipients.values()), "log": log}


def make_dkim_key() -> tuple[str, str]:
    """A new 2048-bit RSA key pair as (private PEM, public PEM)."""
    private_pem = _pem(run(config.OPENSSL, "genrsa", "2048"))
    public_pem = _pem(run(config.OPENSSL, "rsa", "-pubout", stdin=private_pem.encode()))
    return private_pem, public_pem


def _pem(text: str) -> str:
    """The PEM block from openssl's output (stderr may hold progress dots)."""
    m = re.search(r"-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----", text, re.DOTALL)
    if not m:
        raise HTTPException(502, f"openssl printed no key: {text}")
    return m[0] + "\n"
