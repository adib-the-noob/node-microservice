# Mail sidecar (REST → Postfix / OpenDKIM CLI)

A small HTTP service that runs **on the mail VM** next to Postfix and OpenDKIM.
Every REST call is turned into one of the VM's own command-line tools: no
shell, an argument list only, and every input checked first.

| Endpoint | What it does |
|---|---|
| `POST /mail` | `sendmail -i -f <from> <rcpt…>` (MIME on stdin), then INSERT into `sent_mail` |
| `GET /mail/{message_id}` | `journalctl -t postfix/* -t opendkim -g …` |
| `GET /queue` | `postqueue -j` |
| `POST /queue/flush` | `postqueue -f` |
| `POST /queue/{id}/flush` | `postqueue -i ID` |
| `POST /queue/{id}/hold\|release\|requeue` | `postsuper -h\|-H\|-r ID` |
| `DELETE /queue/{id}` | `postsuper -d ID` |
| `POST /dkim/domains` | `openssl genrsa 2048`, then INSERT into `dkim_keys` + `dkim_signing` |
| `GET /dkim/domains/{domain}/dns` | `dig +short TXT s1._domainkey.DOMAIN` |
| `GET /healthz` | `systemctl is-active postfix opendkim` + `SELECT 1` on the DB |

Interactive docs: `http://<host>:8025/docs`.

## How DKIM signing happens

`sendmail` hands the message to Postfix's `pickup`. Your `main.cf` sets
`non_smtpd_milters = $smtpd_milters`, so the message goes through OpenDKIM.
OpenDKIM signs it with the key whose `dkim_signing.author` row matches the
**From:** address. If the From: domain has no row, the mail goes out
**unsigned**. `GET /mail/{id}` reports `dkim.signed` so you can see this.
Set `ALLOWED_FROM_DOMAINS` to stop that from happening.

## Usage

```bash
API=http://127.0.0.1:8025

# send
curl -s -X POST $API/mail -H 'Content-Type: application/json' -d '{
  "from": "noreply@example.com", "from_name": "Example",
  "to": ["user@gmail.com"], "cc": [], "bcc": [],
  "subject": "Hello", "text": "Plain body", "html": "<p>HTML body</p>",
  "headers": {"List-Unsubscribe": "<mailto:unsub@example.com>"},
  "attachments": [{"filename": "a.txt", "content_type": "text/plain", "content_base64": "aGk="}]
}'
# -> 202 {"status":"queued","message_id":"1730...@example.com","recipients":1}

# delivery + DKIM status (a few seconds later)
curl -s "$API/mail/1730...@example.com"
# -> {"queue_id":"4F9D3C2A1B","status":"sent","dkim":{"signed":true,"selector":"s1","domain":"example.com"},"recipients":[...],"log":[...]}

# onboard a new sending domain, then publish the returned TXT record
curl -s -X POST $API/dkim/domains -d '{"domain":"example.org","selector":"s1"}' -H 'Content-Type: application/json'
curl -s $API/dkim/domains/example.org/dns

# queue
curl -s $API/queue
curl -s -X DELETE $API/queue/4F9D3C2A1B
```

The `status` field is `queued`, `partial`, or the Postfix status shared by all recipients (`sent`, `deferred`, `bounced`, …). A 2048-bit
DKIM `dns_value` is longer than 255 characters, so most DNS providers want it
split into several quoted strings.

## Run (on the mail VM, after the provisioning playbook has run)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh   # once, so root can find uv
cp .env.example .env && nano .env                      # DB credentials
sudo ./run.sh
curl -s http://127.0.0.1:8025/healthz
```

It runs as root because `postsuper` and reading the journal need it.
Settings live in `.env` (see `.env.example`); binary paths are constants at
`app/config.py`.

**There is no authentication**: anyone who can reach the port can send mail,
delete queued mail and add DKIM keys. If the gateway calls it over the network,
set `HOST` to the private IP and firewall the port to the gateway only, e.g.
`ufw allow from <gateway_ip> to any port 8025 proto tcp`.

## Database

Every node uses the central MySQL DB that OpenDKIM reads (SQLAlchemy + PyMySQL, always TLS).
The DB user needs INSERT on `dkim_keys`, `dkim_signing` and `sent_mail`, and
CREATE for the first start, so use `dkim_admin`, not `opendkim_ro`.

- `dkim_keys`, `dkim_signing`: already exist. `POST /dkim/domains` adds one key
  and the signing rows `@D`, `D`, `*@D`. A key that already exists returns 409.
- `sent_mail`: created at startup if missing. There is one row per message sent through the API:

  | column | type |
  |---|---|
  | `message_id` | VARCHAR(255) PK |
  | `node` | VARCHAR(255): hostname of the node that sent it |
  | `sender` | VARCHAR(255) |
  | `recipients` | TEXT: comma separated, includes bcc |
  | `subject` | VARCHAR(998) |
  | `created_at` | TIMESTAMP |

  Delivery status is still read from each node's journal (`GET /mail/{id}` on the `node`).

## Code layout

| File | What's in it |
|---|---|
| `app/main.py` | the FastAPI app; creates `sent_mail` at startup |
| `app/routes.py` | all HTTP routes |
| `app/schemas.py` | request/response bodies and their validation |
| `app/models.py` | SQLAlchemy tables: `dkim_keys`, `dkim_signing`, `sent_mail` |
| `app/db.py` | engine, session, `get_db` dependency |
| `app/mail.py` | building the MIME message, journal status lookup, DKIM key generation |
| `app/utils.py` | `run()` for commands, `check()` and regexes for inputs |
| `app/config.py` | settings from env, binary paths |

## Develop

```bash
uv sync
uv run pytest            # fake sendmail/postqueue/... scripts, SQLite instead of MySQL
./run.sh                 # needs a reachable DB (startup creates sent_mail)
```
