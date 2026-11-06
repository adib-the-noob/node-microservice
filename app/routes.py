"""HTTP routes."""

import json
import logging
import re
import socket
from email.policy import SMTP

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .mail import build_message, delivery_status, make_dkim_key
from .models import DkimKey, DkimSigning, SentMail
from .schemas import DkimRecord, DnsCheck, DomainIn, MailIn, MailQueued
from .utils import DOMAIN, MESSAGE_ID, QUEUE_ID, SELECTOR, check, run

log = logging.getLogger("uvicorn.error")
router = APIRouter()

POSTSUPER_FLAGS = {"hold": "-h", "release": "-H", "requeue": "-r", "delete": "-d"}


# ---- health ----------------------------------------------------------------

@router.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    states = run(config.SYSTEMCTL, "is-active", "postfix", "opendkim", ok=(0, 3)).split()
    if states != ["active", "active"]:
        raise HTTPException(503, f"postfix, opendkim: {states}")
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(503, f"database: {exc}")
    return {"status": "ok"}


# ---- mail ------------------------------------------------------------------

@router.post("/mail", status_code=202, response_model=MailQueued)
def send_mail(req: MailIn, db: Session = Depends(get_db)):
    """Pipe the message to `sendmail`. Postfix pickup runs it through OpenDKIM,
    which signs it with the key matching the From: domain."""
    domain = req.sender.split("@")[1]
    if config.ALLOWED_FROM_DOMAINS and domain not in config.ALLOWED_FROM_DOMAINS:
        raise HTTPException(422, f"sending as @{domain} is not allowed")

    msg = build_message(req)
    # -i: a lone "." line is not end-of-input.
    run(config.SENDMAIL, "-i", "-f", req.sender, *req.recipients, stdin=msg.as_bytes(policy=SMTP.clone(linesep="\n")))
    message_id = msg["Message-ID"].strip("<>")

    try:
        db.add(SentMail(message_id=message_id, node=socket.gethostname(), sender=req.sender,
                        recipients=",".join(req.recipients), subject=req.subject))
        db.commit()
    except SQLAlchemyError:  # the mail is already queued, so don't fail the request
        db.rollback()
        log.exception("could not log %s to sent_mail", message_id)
    return MailQueued(message_id=message_id, recipients=len(req.recipients))


@router.get("/mail/{message_id}")
def mail_status(message_id: str, since_hours: int = 168):
    """Delivery + DKIM status, read from this node's journal."""
    result = delivery_status(check(MESSAGE_ID, message_id.strip("<>"), "Message-ID"), since_hours)
    if result is None:
        raise HTTPException(404, "no log entries for that Message-ID (yet)")
    return result


# ---- queue -----------------------------------------------------------------

@router.get("/queue")
def queue_list():
    """`postqueue -j`: one JSON object per queued message."""
    return [json.loads(line) for line in run(config.POSTQUEUE, "-j").splitlines() if line.strip()]


@router.post("/queue/flush")
def queue_flush():
    return {"output": run(config.POSTQUEUE, "-f")}


@router.post("/queue/{queue_id}/flush")
def queue_flush_one(queue_id: str):
    return {"output": run(config.POSTQUEUE, "-i", check(QUEUE_ID, queue_id, "queue id"))}


@router.post("/queue/{queue_id}/{action}")
def queue_action(queue_id: str, action: str):
    if action not in POSTSUPER_FLAGS:
        raise HTTPException(404, "unknown action")
    return {"output": run(config.POSTSUPER, POSTSUPER_FLAGS[action], check(QUEUE_ID, queue_id, "queue id"))}


@router.delete("/queue/{queue_id}")
def queue_delete(queue_id: str):
    return queue_action(queue_id, "delete")


# ---- DKIM ------------------------------------------------------------------

@router.post("/dkim/domains", status_code=201, response_model=DkimRecord)
def dkim_add(req: DomainIn, db: Session = Depends(get_db)):
    """Make a key, store it in the central DB, return the DNS record to publish."""
    key_id = f"{req.selector}._domainkey.{req.domain}"
    private_pem, public_pem = make_dkim_key()
    db.add(DkimKey(key_id=key_id, domain=req.domain, selector=req.selector,
                   private_key=private_pem, public_key=public_pem))
    db.add_all(DkimSigning(author=a, key_id=key_id) for a in (f"@{req.domain}", req.domain, f"*@{req.domain}"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"{key_id} already exists")
    p = "".join(public_pem.splitlines()[1:-1])
    return DkimRecord(dns_name=key_id, dns_value=f"v=DKIM1; k=rsa; p={p}")


@router.get("/dkim/domains/{domain}/dns", response_model=DnsCheck)
def dkim_dns(domain: str, selector: str = "s1"):
    """Is the public key published? (`dig +short TXT SELECTOR._domainkey.DOMAIN`)"""
    name = f"{check(SELECTOR, selector, 'selector')}._domainkey.{check(DOMAIN, domain.lower(), 'domain')}"
    for line in run(config.DIG, "+short", "TXT", name).splitlines():
        record = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', line))  # long records come split: "a" "b"
        if "v=DKIM1" in record:
            return DnsCheck(dns_name=name, published=True, record=record)
    return DnsCheck(dns_name=name, published=False, record=None)
