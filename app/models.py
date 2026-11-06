"""Tables in the central DB.

dkim_keys and dkim_signing already exist (OpenDKIM reads them); only sent_mail
is created by this app.
"""

from datetime import datetime

from sqlalchemy import TIMESTAMP, String, Text, text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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


class SentMail(Base):
    """One row per message sent through POST /mail."""
    __tablename__ = "sent_mail"

    message_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    node: Mapped[str] = mapped_column(String(255))  # hostname of the node that sent it
    sender: Mapped[str] = mapped_column(String(255))
    recipients: Mapped[str] = mapped_column(Text)  # comma separated, includes bcc
    subject: Mapped[str] = mapped_column(String(998))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
