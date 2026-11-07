"""Tables in the central DB.

dkim_keys and dkim_signing are OpenDKIM's tables. Migration 0002 creates them on a
fresh DB; existing ones are never altered or dropped. The app's own tables are
domains, dns_records and sent_mail.
"""

from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DkimKey(Base):
    __tablename__ = "dkim_keys"

    __table_args__ = (UniqueConstraint("domain", "selector", name="uq_domain_selector"),)

    key_id: Mapped[str] = mapped_column(String(320), primary_key=True)  # s1._domainkey.unifyed.tech
    domain: Mapped[str] = mapped_column(String(253))  # unifyed.tech
    selector: Mapped[str] = mapped_column(String(63))  # s1
    private_key: Mapped[str] = mapped_column(Text)  # full PEM
    public_key: Mapped[str] = mapped_column(Text)  # PEM public key
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))


class DkimSigning(Base):
    """OpenDKIM signs mail whose From: matches `author` with key `key_id`."""
    __tablename__ = "dkim_signing"
    __table_args__ = (Index("idx_key_id", "key_id"),)

    author: Mapped[str] = mapped_column(String(255), primary_key=True)  # unifyed.tech, @unifyed.tech, *@unifyed.tech
    key_id: Mapped[str] = mapped_column(
        String(320), ForeignKey("dkim_keys.key_id", name="fk_signing_key", ondelete="CASCADE"))


class Domain(Base):
    """A sending domain added through POST /domains."""
    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    selector: Mapped[str] = mapped_column(String(63))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    records: Mapped[list["DnsRecord"]] = relationship(back_populates="domain", cascade="all, delete-orphan",
                                                      order_by="DnsRecord.id")


class DnsRecord(Base):
    """A DNS record the domain owner must publish (SPF, DMARC, DKIM)."""
    __tablename__ = "dns_records"
    __table_args__ = (UniqueConstraint("domain_id", "type", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(10))  # TXT
    name: Mapped[str] = mapped_column(String(255))  # host, relative to the domain: "@", "_dmarc", "s1._domainkey"
    value: Mapped[str] = mapped_column(Text)

    domain: Mapped[Domain] = relationship(back_populates="records")

    @property
    def fqdn(self) -> str:
        return self.domain.name if self.name == "@" else f"{self.name}.{self.domain.name}"


class Node(Base):
    """A mail VM running this app. Each node registers itself at startup, keyed by IPv4."""
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    ipv4: Mapped[str] = mapped_column(String(15), unique=True)
    hostname: Mapped[str] = mapped_column(String(255))
    port: Mapped[int]  # API port
    environment: Mapped[str] = mapped_column(String(20), server_default="production")  # APP_ENV
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    last_started_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))


class SentMail(Base):
    """One row per message sent through POST /mail."""
    __tablename__ = "sent_mail"

    message_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    node: Mapped[str] = mapped_column(String(255))  # hostname of the node that sent it
    sender: Mapped[str] = mapped_column(String(255))
    recipients: Mapped[str] = mapped_column(Text)  # comma separated, includes bcc
    subject: Mapped[str] = mapped_column(String(998))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))


# OpenDKIM's tables: migrations never create, alter or drop them.
PRIME_TABLES = {"dkim_keys", "dkim_signing"}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Alembic filter: skip the prime tables, and tables in the DB that aren't modelled here."""
    table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
    if table in PRIME_TABLES:
        return False
    if type_ == "table" and reflected and compare_to is None:
        return False  # never drop a table we don't know
    return True
