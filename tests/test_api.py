import base64
import email
import json
from email import policy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import config
from app.db import get_db
from app.main import app
from app.models import Base, DkimKey, DkimSigning, Domain, SentMail


def _script(path: Path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    bins = tmp_path / "bin"
    bins.mkdir()
    bins_ = dict(
        SENDMAIL=_script(bins / "sendmail",
                             f'printf "%s\\n" "$@" > {out}/argv\ncat > {out}/stdin\n'),
        POSTQUEUE=_script(bins / "postqueue", f'''
printf "%s\\n" "$@" > {out}/pq_argv
if [ "$1" = "-j" ]; then
  echo '{{"queue_name":"deferred","queue_id":"4F9D3C2A1B","sender":"a@example.com","recipients":[{{"address":"b@x.org","delay_reason":"timeout"}}]}}'
fi
'''),
        POSTSUPER=_script(bins / "postsuper",
                              f'printf "%s\\n" "$@" > {out}/ps_argv\necho "postsuper: Deleted: 1 message" >&2\n'),
        DIG=_script(bins / "dig", '''
case "$3" in
  _dmarc.*) echo '"v=DMARC1; p=none; adkim=r; aspf=r"' ;;
  *._domainkey.*) ;;  # DKIM key not published yet
  *) echo '"v=spf1 include:spf.metrovps.art " "~all"' ;;  # long records come split
esac
'''),
        JOURNALCTL=_script(bins / "journalctl", '''
case "$*" in
  *message-id=*) echo "4F9D3C2A1B: message-id=<abc.123@example.com>" ;;
  *4F9D3C2A1B*)
    echo "4F9D3C2A1B: uid=1000 from=<a@example.com>"
    echo "4F9D3C2A1B: DKIM-Signature field added (s=s1, d=example.com)"
    echo "4F9D3C2A1B: to=<b@x.org>, relay=mx.x.org[1.2.3.4]:25, delay=1, dsn=4.4.1, status=deferred (timeout)"
    echo "4F9D3C2A1B: to=<b@x.org>, relay=mx.x.org[1.2.3.4]:25, delay=9, dsn=2.0.0, status=sent (250 ok)"
    echo "4F9D3C2A1B: removed" ;;
  *) exit 1 ;;
esac
'''),
    )
    for name, path in bins_.items():
        monkeypatch.setattr(config, name, path)

    # in-memory SQLite stands in for the central MariaDB DB
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(DkimKey(key_id="s1._domainkey.dup.com", domain="dup.com", selector="s1", private_key="x", public_key="x"))
    db.commit()

    def session():
        with Session(engine) as s:
            yield s
    app.dependency_overrides[get_db] = session
    yield TestClient(app), out, db
    app.dependency_overrides.clear()


def test_send_mail_pipes_mime_to_sendmail(env):
    client, out, db = env
    r = client.post("/mail", json={
        "from": "news@example.com", "from_name": "News",
        "to": ["b@x.org"], "cc": ["c@x.org"], "bcc": ["secret@x.org"],
        "subject": "Héllo", "text": "plain", "html": "<b>rich</b>",
        "headers": {"X-Campaign": "42"},
        "attachments": [{"filename": "a.txt", "content_type": "text/plain",
                         "content_base64": base64.b64encode(b"hi").decode()}],
    })
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["message_id"].endswith("@example.com") and body["recipients"] == 3

    argv = (out / "argv").read_text().split()
    assert argv == ["-i", "-f", "news@example.com", "b@x.org", "c@x.org", "secret@x.org"]

    msg = email.message_from_bytes((out / "stdin").read_bytes(), policy=policy.default)
    assert msg["From"] == "News <news@example.com>"
    assert msg["Subject"] == "Héllo"
    assert msg["X-Campaign"] == "42"
    assert msg["Bcc"] is None  # envelope only
    assert msg["Message-ID"].strip("<>") == body["message_id"]
    assert [p.get_filename() for p in msg.iter_attachments()] == ["a.txt"]
    row = db.get(SentMail, body["message_id"])
    assert (row.sender, row.recipients, row.subject) == ("news@example.com", "b@x.org,c@x.org,secret@x.org", "Héllo")


@pytest.mark.parametrize("patch, fragment", [
    ({"to": ["-oQ/tmp@x.org"]}, "invalid email"),
    ({"subject": "a\r\nBcc: evil@x.org"}, "line breaks"),
    ({"headers": {"From": "spoof@x.org"}}, "cannot be overridden"),
    ({"text": None}, "at least one"),
])
def test_send_mail_rejects_bad_input(env, patch, fragment):
    client, out, db = env
    payload = {"from": "a@example.com", "to": ["b@x.org"], "subject": "s", "text": "t", **patch}
    r = client.post("/mail", json=payload)
    assert r.status_code == 422
    assert fragment in r.text
    assert not (out / "argv").exists()


def test_mail_status_from_journal(env):
    client, _, _ = env
    r = client.get("/mail/abc.123@example.com")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["queue_id"] == "4F9D3C2A1B"
    assert b["status"] == "sent"
    assert b["dkim"] == {"signed": True, "selector": "s1", "domain": "example.com"}
    assert b["recipients"][0]["dsn"] == "2.0.0"


def test_queue_list_and_actions(env):
    client, out, db = env
    r = client.get("/queue")
    assert len(r.json()) == 1

    r = client.delete("/queue/4F9D3C2A1B")
    assert r.status_code == 200 and "Deleted" in r.json()["output"]
    assert (out / "ps_argv").read_text().split() == ["-d", "4F9D3C2A1B"]

    client.post("/queue/4F9D3C2A1B/flush")
    assert (out / "pq_argv").read_text().split() == ["-i", "4F9D3C2A1B"]

    assert client.delete("/queue/ALL").status_code == 422
    assert client.delete("/queue/..%2Fx").status_code in (404, 405, 422)


def test_add_domain_and_check_dns(env):
    client, out, db = env
    r = client.post("/domains", json={"domain": "New.com", "selector": "s2"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "new.com"

    # OpenDKIM's tables got the key and the signing rows
    key = db.get(DkimKey, "s2._domainkey.new.com")
    assert (key.domain, key.selector) == ("new.com", "s2")
    assert key.private_key.startswith("-----BEGIN PRIVATE KEY-----")
    authors = db.scalars(select(DkimSigning.author).where(DkimSigning.key_id == key.key_id)).all()
    assert sorted(authors) == ["*@new.com", "@new.com", "new.com"]

    # domains / dns_records got the three records to publish
    dkim_value = "v=DKIM1; k=rsa; p=" + "".join(key.public_key.splitlines()[1:-1])
    assert [(x["type"], x["name"], x["fqdn"], x["value"]) for x in body["records"]] == [
        ("TXT", "@", "new.com", "v=spf1 include:spf.metrovps.art ~all"),
        ("TXT", "_dmarc", "_dmarc.new.com", "v=DMARC1; p=none; adkim=r; aspf=r"),
        ("TXT", "s2._domainkey", "s2._domainkey.new.com", dkim_value),
    ]
    assert db.scalar(select(Domain).where(Domain.name == "new.com")) is not None
    assert client.get("/domains").json()[0]["name"] == "new.com"
    assert client.get("/domains/NEW.com").json() == body

    # same domain again, or a key that already exists in dkim_keys -> 409, nothing half-written
    assert client.post("/domains", json={"domain": "new.com", "selector": "s2"}).status_code == 409
    assert client.post("/domains", json={"domain": "dup.com"}).status_code == 409
    assert db.scalar(select(Domain).where(Domain.name == "dup.com")) is None

    # bad input never reaches the DB
    r = client.post("/domains", json={"domain": "x.com'); DROP TABLE dkim_keys;--"})
    assert r.status_code == 422

    checks = {c["fqdn"]: c["published"] for c in client.get("/domains/new.com/dns").json()}
    assert checks == {"new.com": True, "_dmarc.new.com": True, "s2._domainkey.new.com": False}
    assert client.get("/domains/nope.com/dns").status_code == 404


def test_node_registers_itself_by_ipv4(env, tmp_path, monkeypatch):
    client, _, db = env
    from app import node

    def ip_route(src):
        monkeypatch.setattr(config, "IP", _script(tmp_path / "ip", f'echo "1.1.1.1 via 10.0.0.1 dev eth0 src {src} uid 0"\n'))

    monkeypatch.setattr(node.socket, "gethostname", lambda: "mail-1")
    ip_route("10.0.0.7")
    node.register(db)
    node.register(db)  # restart: same row, updated
    assert [(n["ipv4"], n["hostname"], n["environment"]) for n in client.get("/nodes").json()] == [
        ("10.0.0.7", "mail-1", "production")]

    # a developer PC
    monkeypatch.setattr(config, "APP_ENV", "local")
    ip_route("192.168.1.20")
    node.register(db)
    assert [n["ipv4"] for n in client.get("/nodes?environment=local").json()] == ["192.168.1.20"]
    assert [n["ipv4"] for n in client.get("/nodes?environment=production").json()] == ["10.0.0.7"]

    ip_route("not-an-ip")
    with pytest.raises(RuntimeError, match="could not find this node's IPv4"):
        node.register(db)
