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
| `POST /domains` | `openssl genrsa 2048`, then INSERT into `dkim_keys` + `dkim_signing` + `domains` + `dns_records` |
| `GET /domains` | list domains with their DNS records |
| `GET /domains/{domain}` | one domain with its DNS records |
| `GET /domains/{domain}/dns` | `dig +short TXT <fqdn>` for each record: is it published? |
| `GET /nodes` | all registered nodes (`nodes` table) |
| `GET /healthz` | `systemctl is-active postfix opendkim` + `SELECT 1` on the DB |

Interactive docs: `http://<host>:8025/docs`.

## How DKIM signing happens

`sendmail` hands the message to Postfix's `pickup`. Your `main.cf` sets
`non_smtpd_milters = $smtpd_milters`, so the message goes through OpenDKIM.
OpenDKIM signs it with the key whose `dkim_signing.author` row matches the
**From:** address. If the From: domain has no row, the mail goes out
**unsigned**. `GET /mail/{id}` reports `dkim.signed` so you can see this.

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
curl -s -X POST $API/domains -d '{"domain":"example.org","selector":"s1"}' -H 'Content-Type: application/json'
# -> 201 {"name":"example.org","selector":"s1","created_at":"...","records":[
#      {"type":"TXT","name":"@","fqdn":"example.org","value":"v=spf1 include:spf.metrovps.art ~all"},
#      {"type":"TXT","name":"_dmarc","fqdn":"_dmarc.example.org","value":"v=DMARC1; p=none; adkim=r; aspf=r"},
#      {"type":"TXT","name":"s1._domainkey","fqdn":"s1._domainkey.example.org","value":"v=DKIM1; k=rsa; p=MIIB..."}]}
curl -s $API/domains/example.org/dns   # published: true/false per record

# queue
curl -s $API/queue
curl -s -X DELETE $API/queue/4F9D3C2A1B
```

The `status` field is `queued`, `partial`, or the Postfix status shared by all recipients (`sent`, `deferred`, `bounced`, …). A 2048-bit
DKIM `dns_value` is longer than 255 characters, so most DNS providers want it
split into several quoted strings.

## Run (on the mail VM, after the provisioning playbook has run)

```bash
cp .env.example .env && nano .env      # DB credentials
docker compose up -d --build
curl -s http://127.0.0.1:8025/healthz
docker compose logs -f                 # logs
```

The container drives the **host's** Postfix and OpenDKIM. Every command
(`sendmail`, `postqueue`, `postsuper`, `journalctl`, `systemctl`, `dig`,
`openssl`) runs in the host's namespaces via `nsenter -t 1`. That's why
`docker-compose.yml` uses `pid: host`, `uts: host` and `privileged: true`. The container is
effectively root on the VM, the same as running the app as root directly.

The API is published on `0.0.0.0:${PORT}` (default 8025). Docker's port rules
go **around ufw**, so the port is open to anyone the cloud provider's firewall lets
through.

Without Docker: `sudo ./run.sh` (needs `uv` on the host).

Settings live in `.env` (see `.env.example`); binary paths are constants in
`app/config.py`.

**There is no authentication**: anyone who can reach the port can send mail,
delete queued mail and add DKIM keys. Limit port 8025 in the cloud provider's
firewall / security group to the IPs that need it (e.g. the gateway). To publish
on one interface only, use `"<private-ip>:8025:8025"` in `docker-compose.yml`.

## Database

Every node uses the central MariaDB DB that OpenDKIM reads (SQLAlchemy + PyMySQL).
The app and alembic both connect with `DATABASE_URL` from `.env`, e.g.
`mariadb+pymysql://dkim_admin:PASSWORD@host:3306/opendkim`. URL-encode special characters
in the password (`@` → `%40`, `:` → `%3A`, `/` → `%2F`).
The DB user needs INSERT on `dkim_keys`, `dkim_signing`, `domains`, `dns_records`
and `sent_mail`, SELECT on `domains` / `dns_records`, and CREATE/ALTER for migrations, so use `dkim_admin`, not `opendkim_ro`.

- `dkim_keys` (`key_id` PK, `domain`, `selector`, `private_key`, `public_key`, `created_at`,
  unique `domain`+`selector`) and `dkim_signing` (`author` PK, `key_id` → `dkim_keys.key_id`
  ON DELETE CASCADE): OpenDKIM's tables. Migration `0002` creates them only on a fresh DB.
  Existing ones are never altered, and downgrade never drops them. `POST /domains` only
  adds one key and the signing rows `@D`, `D`, `*@D`.
- `domains` (`id`, `name` unique, `selector`, `created_at`): made by migrations.
  There is one row per domain added through `POST /domains`. A domain or key that already exists returns
  409, and nothing is written (one transaction).
- `dns_records` (`id`, `domain_id` → `domains.id`, `type`, `name`, `value`): made by migrations.
  These are the records each domain must publish. `name` is relative to the domain:

  | type | name | value |
  |---|---|---|
  | TXT | `@` | `v=spf1 include:spf.metrovps.art ~all` (`SPF_RECORD`) |
  | TXT | `_dmarc` | `v=DMARC1; p=none; adkim=r; aspf=r` (`DMARC_RECORD`) |
  | TXT | `s1._domainkey` | `v=DKIM1; k=rsa; p=…` |
- `nodes` (`id`, `ipv4` unique, `hostname`, `port`, `environment`, `created_at`, `last_started_at`): every node
  registers itself at startup. It inserts its row, or updates it if that IPv4 is already there. The IPv4 is
  the host's primary address (`ip -4 route get 1.1.1.1`). Behind NAT that's the private IP.
  Startup fails if no IPv4 is found.
  `environment` is `APP_ENV` from `.env`: `production` on mail servers (the default), `local` on a
  developer PC. Filter with `GET /nodes?environment=production`.
- `sent_mail`: made by migrations. There is one row per message sent through the API:

  | column | type |
  |---|---|
  | `message_id` | VARCHAR(255) PK |
  | `node` | VARCHAR(255): hostname of the node that sent it |
  | `sender` | VARCHAR(255) |
  | `recipients` | TEXT: comma separated, includes bcc |
  | `subject` | VARCHAR(998) |
  | `created_at` | TIMESTAMP |

  Delivery status is still read from each node's journal (`GET /mail/{id}` on the `node`).

## Migrations (Alembic)

`docker compose up` and `run.sh` run `alembic upgrade head` before starting the
app. Nodes take a MariaDB lock (`GET_LOCK`) first, so when several start at once
only one migrates at a time.

Migrations only create `dkim_keys` / `dkim_signing` when they're missing (`0002`).
They never alter or drop them, and autogenerate ignores them, as it does any table not in
`app/models.py` (see `include_object` in `app/models.py`). `0001` and `0002` create each
table only if it's missing, so existing DBs upgrade cleanly.

To change a table, edit `app/models.py`, then:

```bash
uv run alembic revision --autogenerate -m "add x"   # review the file in migrations/versions/
uv run alembic upgrade head                         # or just restart: it runs on startup
```

Other commands: `uv run alembic current`, `uv run alembic history`, `uv run alembic downgrade -1`.
Inside the container: `docker compose exec mail-sidecar alembic current`.

## Code layout

| File | What's in it |
|---|---|
| `app/main.py` | the FastAPI app |
| `alembic.ini`, `migrations/` | Alembic migrations for `domains`, `dns_records`, `sent_mail` |
| `app/routes.py` | all HTTP routes |
| `app/schemas.py` | request/response bodies and their validation |
| `app/models.py` | SQLAlchemy tables: `dkim_keys`, `dkim_signing`, `domains`, `dns_records`, `sent_mail` |
| `app/db.py` | engine, session, `get_db` dependency |
| `app/node.py` | self-registration in `nodes` at startup |
| `app/mail.py` | building the MIME message, journal status lookup, DKIM key generation |
| `app/utils.py` | `run()` for commands, `check()` and regexes for inputs |
| `app/config.py` | settings from env, binary paths |
| `Dockerfile`, `docker-compose.yml` | the container (runs commands on the host via `nsenter`) |

## Develop

```bash
uv sync
uv run pytest            # fake sendmail/postqueue/... scripts, SQLite instead of MariaDB;
                         # also checks the migrations match app/models.py
./run.sh                 # needs a reachable DB (runs migrations first)
```
