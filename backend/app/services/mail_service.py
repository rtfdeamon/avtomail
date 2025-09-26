from __future__ import annotations

import imaplib
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, parseaddr, parsedate_to_datetime
from typing import Iterable, Sequence

from app.core.config import Settings, get_settings
from app.core.logging import logger


@dataclass(slots=True)
class EmailAttachment:
    filename: str
    content_type: str | None
    content_id: str | None
    payload: bytes
    is_inline: bool = False


@dataclass(slots=True)
class InboundEmail:
    imap_uid: bytes
    message_id: str
    subject: str | None
    from_address: str
    from_name: str | None
    to_addresses: list[str]
    cc_addresses: list[str]
    date: datetime | None
    body_plain: str | None
    body_html: str | None
    in_reply_to: str | None
    references: list[str]
    attachments: list[EmailAttachment]
    raw: bytes


@dataclass(slots=True)
class OutboundAttachment:
    filename: str
    content_type: str | None
    payload: bytes


@dataclass(slots=True)
class OutboundEmail:
    to_addresses: Sequence[str]
    subject: str
    body_plain: str
    body_html: str | None = None
    in_reply_to: str | None = None
    references: Sequence[str] | None = None
    reply_to: Sequence[str] | None = None


class MailServiceConnectionError(RuntimeError):
    """Raised when IMAP connection cannot be established."""


class MailService:
    """IMAP/SMTP integration responsible for ingesting and sending emails."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_unseen(self) -> list[InboundEmail]:
        if not self._has_imap_credentials:
            logger.warning("IMAP credentials not configured; skipping fetch")
            return []

        with self._imap_connection() as imap:
            status, _ = imap.select(self.settings.imap_folder)
            if status != "OK":
                logger.error("Unable to select IMAP folder %s", self.settings.imap_folder)
                return []

            status, data = imap.search(None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                return []

            messages: list[InboundEmail] = []
            for message_id in data[0].split():
                status, payload = imap.fetch(message_id, "(RFC822)")
                if status != "OK" or not payload:
                    logger.warning("Failed to fetch message %s", message_id)
                    continue
                raw = payload[0][1]
                email_message = message_from_bytes(raw)
                parsed = self._parse_message(email_message, raw, message_id)
                messages.append(parsed)
                imap.store(message_id, "+FLAGS", "(\\Seen)")
            return messages

    def move_to_processed(self, message_uid: bytes, target_folder: str = "Processed") -> None:
        if not self._has_imap_credentials:
            return
        with self._imap_connection() as imap:
            status, _ = imap.select(self.settings.imap_folder)
            if status != "OK":
                return
            result = imap.copy(message_uid, target_folder)
            if result[0] == "OK":
                imap.store(message_uid, "+FLAGS", "(\\Deleted)")
                imap.expunge()

    def send_email(self, email: OutboundEmail) -> None:
        if not self._has_smtp_credentials:
            logger.warning("SMTP credentials not configured; cannot send email")
            return

        message = self._build_email_message(email)
        self._send_via_smtp(message)
        self._append_to_sent(message)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_email_message(self, email: OutboundEmail) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = email.subject
        message["From"] = formataddr((None, self.settings.smtp_from_address))
        message["To"] = ", ".join(email.to_addresses)
        if email.reply_to:
            message["Reply-To"] = ", ".join(email.reply_to)
        if email.in_reply_to:
            message["In-Reply-To"] = email.in_reply_to
        if email.references:
            message["References"] = " ".join(email.references)

        message.set_content(email.body_plain, subtype="plain", charset="utf-8")
        if email.body_html:
            message.add_alternative(email.body_html, subtype="html", charset="utf-8")
        if email.attachments:
            for attachment in email.attachments:
                content_type = attachment.content_type or "application/octet-stream"
                if "/" in content_type:
                    maintype, subtype = content_type.split("/", 1)
                else:
                    maintype, subtype = content_type, "octet-stream"
                message.add_attachment(
                    attachment.payload,
                    maintype=maintype,
                    subtype=subtype,
                    filename=attachment.filename,
                )
        return message

    def _send_via_smtp(self, message: EmailMessage) -> None:
        use_tls = self.settings.smtp_use_tls
        host = self.settings.smtp_host
        port = self.settings.smtp_port
        username = self.settings.smtp_username
        password = self.settings.smtp_password

        server: smtplib.SMTP | smtplib.SMTP_SSL
        if use_tls:
            server = smtplib.SMTP(host, port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port)

        try:
            if username and password:
                server.login(username, password)
            server.send_message(message)
            logger.info("Email sent to %s", message["To"])
        finally:
            server.quit()

    def _append_to_sent(self, message: EmailMessage) -> None:
        if not self._has_imap_credentials:
            return
        sent_folder = "Sent"
        with self._imap_connection() as imap:
            timestamp = datetime.now(timezone.utc)
            imap.append(sent_folder, "", imaplib.Time2Internaldate(timestamp.timetuple()), message.as_bytes())

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    def _parse_message(self, email_message, raw: bytes, imap_uid: bytes) -> InboundEmail:
        subject = self._decode_header(email_message.get("Subject"))
        from_header = email_message.get("From", "")
        name, addr = parseaddr(from_header)
        to_addresses = self._split_addresses(email_message.get_all("To", []))
        cc_addresses = self._split_addresses(email_message.get_all("Cc", []))
        in_reply_to = email_message.get("In-Reply-To")
        references_header = email_message.get_all("References", [])
        references = self._flatten_reference_header(references_header)
        date = parsedate_to_datetime(email_message.get("Date")) if email_message.get("Date") else None

        body_plain, body_html, attachments = self._extract_content(email_message)

        return InboundEmail(
            imap_uid=imap_uid,
            message_id=email_message.get("Message-ID", ""),
            subject=subject,
            from_address=addr,
            from_name=name or None,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            date=date,
            body_plain=body_plain,
            body_html=body_html,
            in_reply_to=in_reply_to,
            references=references,
            raw=raw,
        )

    def _extract_content(self, email_message) -> tuple[str | None, str | None, list[EmailAttachment]]:
        plain_parts: list[str] = []
        html_parts: list[str] = []
        attachments: list[EmailAttachment] = []
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                content_disposition = (part.get('Content-Disposition') or '').lower()
                filename = self._decode_header(part.get_filename())
                maintype = part.get_content_maintype()
                is_attachment = bool(filename) or 'attachment' in content_disposition
                if not is_attachment and maintype == 'text':
                    text = self._decode_text_part(part)
                    if part.get_content_subtype() == 'html':
                        html_parts.append(text)
                    else:
                        plain_parts.append(text)
                    continue
                payload = part.get_payload(decode=True) or b''
                attachments.append(
                    EmailAttachment(
                        filename=filename or 'attachment',
                        content_type=part.get_content_type(),
                        content_id=part.get('Content-ID'),
                        payload=payload,
                        is_inline='inline' in content_disposition,
                    )
                )
        else:
            payload = email_message.get_payload(decode=True) or b''
            text = self._decode_text_payload(payload, email_message.get_content_charset())
            if email_message.get_content_type() == 'text/html':
                html_parts.append(text)
            else:
                plain_parts.append(text)

        plain_body = '\n'.join(plain_parts) if plain_parts else None
        html_body = '\n'.join(html_parts) if html_parts else None
        return plain_body, html_body, attachments

    @staticmethod
    def _decode_text_part(part) -> str:
        payload = part.get_payload(decode=True) or b''
        charset = part.get_content_charset() or 'utf-8'
        try:
            return payload.decode(charset, errors='ignore')
        except (LookupError, AttributeError):
            return payload.decode('utf-8', errors='ignore')

    @staticmethod
    def _decode_text_payload(payload: bytes, charset: str | None) -> str:
        charset = charset or 'utf-8'
        try:
            return payload.decode(charset, errors='ignore')
        except (LookupError, AttributeError):
            return payload.decode('utf-8', errors='ignore')

    @staticmethod
    def _decode_header(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return str(make_header(decode_header(value)))
        except Exception:  # pragma: no cover - defensive
            return value

    @staticmethod
    def _split_addresses(values: Iterable[str]) -> list[str]:
        addresses: list[str] = []
        for value in values:
            name, addr = parseaddr(value)
            if addr:
                addresses.append(addr)
        return addresses

    @staticmethod
    def _flatten_reference_header(values: Iterable[str]) -> list[str]:
        references: list[str] = []
        for value in values:
            references.extend([token for token in value.split() if token])
        return references

    # ------------------------------------------------------------------
    # Connection utilities
    # ------------------------------------------------------------------
    @property
    def _has_imap_credentials(self) -> bool:
        return bool(self.settings.imap_username and self.settings.imap_password)

    @property
    def _has_smtp_credentials(self) -> bool:
        return bool(self.settings.smtp_username and self.settings.smtp_password)

    def _imap_connection(self):
        class _ImapContext:
            def __init__(self, outer: "MailService") -> None:
                self.outer = outer
                self.conn: imaplib.IMAP4_SSL | None = None

            def __enter__(self) -> imaplib.IMAP4_SSL:
                try:
                    self.conn = imaplib.IMAP4_SSL(
                        self.outer.settings.imap_host,
                        self.outer.settings.imap_port,
                    )
                    self.conn.login(self.outer.settings.imap_username, self.outer.settings.imap_password)
                except OSError as exc:
                    logger.warning("IMAP connection failed: %s", exc)
                    raise MailServiceConnectionError(str(exc)) from exc
                except imaplib.IMAP4.error as exc:
                    logger.warning("IMAP authentication failed: %s", exc)
                    raise MailServiceConnectionError(str(exc)) from exc
                return self.conn

            def __exit__(self, exc_type, exc_val, exc_tb) -> None:
                if self.conn is not None:
                    try:
                        self.conn.logout()
                    except Exception:  # pragma: no cover - best-effort cleanup
                        pass

        return _ImapContext(self)
