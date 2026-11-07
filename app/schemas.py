"""Request and response bodies. Validation errors become 422 responses."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .utils import DOMAIN, EMAIL, HEADER_NAME, SELECTOR

RESERVED_HEADERS = {"from", "to", "cc", "bcc", "reply-to", "subject", "date", "message-id", "mime-version",
                    "content-type", "content-transfer-encoding", "content-disposition", "dkim-signature",
                    "return-path", "received", "sender"}


def email(value: str) -> str:
    if not EMAIL.fullmatch(value):
        raise ValueError(f"invalid email address: {value!r}")
    return value


def one_line(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError("must not contain line breaks")
    return value


# ---- nodes -----------------------------------------------------------------

class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ipv4: str
    hostname: str
    port: int
    environment: str  # "production" or "local"
    created_at: datetime | None
    last_started_at: datetime | None


# ---- mail ------------------------------------------------------------------

class Attachment(BaseModel):
    filename: str
    content_type: str = Field("application/octet-stream", pattern=r"^[\w.+-]+/[\w.+-]+$")
    content_base64: str

    _filename = field_validator("filename")(one_line)


class MailIn(BaseModel):
    sender: str = Field(alias="from")
    from_name: str = ""
    to: list[str] = Field(min_length=1)
    cc: list[str] = []
    bcc: list[str] = []
    reply_to: str | None = None
    subject: str
    text: str | None = None
    html: str | None = None
    headers: dict[str, str] = {}
    attachments: list[Attachment] = []

    @field_validator("sender", "reply_to")
    @classmethod
    def _address(cls, v: str | None) -> str | None:
        return email(v) if v else v

    @field_validator("to", "cc", "bcc")
    @classmethod
    def _addresses(cls, v: list[str]) -> list[str]:
        return [email(a) for a in v]

    _one_line = field_validator("subject", "from_name")(one_line)

    @field_validator("headers")
    @classmethod
    def _headers(cls, v: dict[str, str]) -> dict[str, str]:
        for name, value in v.items():
            if not HEADER_NAME.fullmatch(name) or name.lower() in RESERVED_HEADERS:
                raise ValueError(f"header {name!r} cannot be overridden")
            one_line(value)
        return v

    @model_validator(mode="after")
    def _body(self) -> "MailIn":
        if not self.text and not self.html:
            raise ValueError("provide at least one of 'text' or 'html'")
        return self

    @property
    def recipients(self) -> list[str]:
        """Everyone on the envelope, deduplicated (bcc included)."""
        return list(dict.fromkeys(self.to + self.cc + self.bcc))


class MailQueued(BaseModel):
    status: str = "queued"
    message_id: str
    recipients: int


# ---- domains ---------------------------------------------------------------

class DomainIn(BaseModel):
    domain: str
    selector: str = "s1"

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        v = v.strip().lower()
        if not DOMAIN.fullmatch(v):
            raise ValueError(f"invalid domain: {v!r}")
        return v

    @field_validator("selector")
    @classmethod
    def _selector(cls, v: str) -> str:
        if not SELECTOR.fullmatch(v):
            raise ValueError(f"invalid selector: {v!r}")
        return v


class DnsRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    name: str  # host, relative to the domain ("@", "_dmarc", "s1._domainkey")
    fqdn: str
    value: str


class DomainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    selector: str
    created_at: datetime | None
    records: list[DnsRecordOut]


class DnsCheck(BaseModel):
    type: str
    fqdn: str
    expected: str
    found: list[str]  # TXT values currently in DNS
    published: bool
