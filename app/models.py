"""Tables in the central DB.

dkim_keys and dkim_signing already exist (OpenDKIM reads them) and are never
altered. This app creates domains, dns_records and sent_mail.
"""

from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DkimKey(Base):
    __tablename__ = "dkim_keys"

    key_id: Mapped[str] = mapped_column(String(255), primary_key=True)  # SELECTOR._domainkey.DOMAIN
    domain: Mapped[str] = mapped_column(String(255))
    selector: Mapped[str] = mapped_column(String(63))
    private_key: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT, "mysql"))
    public_key: Mapped[str] = mapped_column(Text)


class DkimSigning(Base):
    """OpenDKIM signs mail whose From: matches `author` with key `key_id`."""
    __tablename__ = "dkim_signing"

    author: Mapped[str] = mapped_column(String(255), primary_key=True)
    key_id: Mapped[str] = mapped_column(String(255))


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
