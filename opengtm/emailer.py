"""
emailer.py - SMTP email sending for opengtm lead lists.

Supports sending personalized emails to a list of lead dicts using environment
variables or explicit config objects.

Configuration via environment variables:
  SMTP_HOST       - SMTP server hostname (e.g., smtp.gmail.com)
  SMTP_PORT       - SMTP port (default: 587)
  SMTP_USERNAME   - Login username
  SMTP_PASSWORD   - Login password or app-specific password
  SMTP_FROM       - Sender email address
  SMTP_USE_TLS    - Use TLS? (default: true)
  SMTP_USE_SSL    - Use SSL? (default: false)
  SMTP_TIMEOUT    - Connection timeout in seconds (default: 30)
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable, Optional


DEFAULT_EMAIL_TEMPLATE = """Hi {first_name},

I wanted to reach out because I saw {company} is working in {industry} and I thought there may be an opportunity to help with your GTM motion.

I'd love to connect and share a quick idea.

Best,
{sender_name}
"""


def _env(name: str, default: str = "") -> str:
    """Get environment variable."""
    return os.environ.get(name, default).strip()


def _coerce_text(value: Any) -> str:
    """Convert any value to string, handle None gracefully."""
    if value is None:
        return ""
    return str(value).strip()


def _flatten_lead(lead: dict[str, Any]) -> dict[str, str]:
    """Flatten nested lead dict for template rendering."""
    flat: dict[str, str] = {}
    for key, value in lead.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}.{sub_key}"] = _coerce_text(sub_value)
        else:
            flat[key] = _coerce_text(value)

    # Add common aliases
    if "name" not in flat and "first_name" in flat:
        flat["name"] = flat["first_name"]
    if "company" not in flat and "company_name" in flat:
        flat["company"] = flat["company_name"]
    if "industry" not in flat and "sector" in flat:
        flat["industry"] = flat["sector"]
    return flat


def _resolve_email(lead: dict[str, Any]) -> str:
    """Extract email from lead dict, checking common field names."""
    for key in ("email", "email_address", "contact_email", "recipient_email", "to_email"):
        value = lead.get(key)
        if value:
            return _coerce_text(value)

    for key in ("contact", "person"):
        nested = lead.get(key)
        if isinstance(nested, dict):
            for nested_key in ("email", "email_address"):
                value = nested.get(nested_key)
                if value:
                    return _coerce_text(value)
    return ""


def _render_template(template: str, lead: dict[str, Any], sender_name: str = "opengtm") -> str:
    """Render template with lead data, safe fallback to empty strings."""
    flat = _flatten_lead(lead)
    flat.setdefault("sender_name", sender_name)
    flat.setdefault("name", flat.get("contact_name") or flat.get("first_name") or flat.get("company") or "there")
    flat.setdefault("first_name", flat.get("contact_name") or flat.get("name") or "there")
    flat.setdefault("company", flat.get("company_name") or flat.get("company") or "your company")
    flat.setdefault("industry", flat.get("industry") or "your market")
    flat.setdefault("domain", flat.get("domain") or "")

    class SafeDict(dict):
        def __missing__(self, key):
            return ""

    return template.format_map(SafeDict(flat))


@dataclass
class EmailConfig:
    """SMTP configuration for sending emails."""

    host: str
    port: int
    username: str
    password: str
    from_email: str
    use_tls: bool = True
    use_ssl: bool = False
    timeout: int = 30

    @classmethod
    def from_env(cls) -> "EmailConfig":
        """Load SMTP config from environment variables."""
        host = _env("SMTP_HOST")
        if not host:
            raise ValueError(
                "SMTP_HOST is not set. Add SMTP_HOST, SMTP_PORT, SMTP_USERNAME, "
                "SMTP_PASSWORD, and SMTP_FROM to your .env file."
            )

        port_text = _env("SMTP_PORT", "587")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError(f"Invalid SMTP_PORT value: {port_text!r}") from exc

        username = _env("SMTP_USERNAME")
        password = _env("SMTP_PASSWORD")
        from_email = _env("SMTP_FROM")
        if not from_email and username:
            from_email = username
        if not from_email:
            raise ValueError("SMTP_FROM is not set. Add it to your .env file.")

        use_tls = _env("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}
        use_ssl = _env("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes", "on"}
        timeout = 30
        timeout_text = _env("SMTP_TIMEOUT")
        if timeout_text:
            try:
                timeout = int(timeout_text)
            except ValueError:
                timeout = 30

        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            from_email=from_email,
            use_tls=use_tls,
            use_ssl=use_ssl,
            timeout=timeout,
        )


def build_message(
    config: EmailConfig,
    lead: dict[str, Any],
    subject_template: str,
    body_template: str,
) -> EmailMessage:
    """Build an EmailMessage for a single lead."""
    to_email = _resolve_email(lead)
    if not to_email:
        raise ValueError(f"Lead missing email address: {lead!r}")

    subject = _render_template(subject_template, lead, sender_name=config.from_email)
    body = _render_template(body_template, lead, sender_name=config.from_email)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.from_email
    msg["To"] = to_email
    msg.set_content(body)
    return msg


def send_single_email(
    lead: dict[str, Any],
    subject_template: str,
    body_template: str,
    config: Optional[EmailConfig] = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Send one email to a lead.

    Returns a dict with status metadata:
      - status: sent / failed / skipped / dry_run
      - email: recipient address
      - company: company name
      - subject: rendered subject (for dry_run)
      - error: error message (if failed)
    """
    if config is None:
        config = EmailConfig.from_env()

    to_email = _resolve_email(lead)
    if not to_email:
        return {
            "status": "skipped",
            "reason": "missing_email",
            "company": lead.get("company") or lead.get("company_name") or "",
            "email": "",
        }

    if dry_run:
        subject = _render_template(subject_template, lead, sender_name=config.from_email)
        if verbose:
            print(f"[email] DRY RUN -> {to_email} | {lead.get('company', 'Unknown company')}", flush=True)
        return {
            "status": "dry_run",
            "email": to_email,
            "company": lead.get("company") or lead.get("company_name") or "",
            "subject": subject,
        }

    try:
        msg = build_message(config, lead, subject_template, body_template)

        if config.use_ssl:
            with smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout) as server:
                if config.username and config.password:
                    server.login(config.username, config.password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(config.host, config.port, timeout=config.timeout) as server:
                if config.use_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                if config.username and config.password:
                    server.login(config.username, config.password)
                server.send_message(msg)

        if verbose:
            print(f"[email] Sent -> {to_email}", flush=True)

        return {
            "status": "sent",
            "email": to_email,
            "company": lead.get("company") or lead.get("company_name") or "",
            "subject": msg["Subject"],
        }
    except Exception as exc:  # noqa: BLE001
        if verbose:
            print(f"[email] FAILED -> {to_email}: {exc}", flush=True)
        return {
            "status": "failed",
            "email": to_email,
            "company": lead.get("company") or lead.get("company_name") or "",
            "error": str(exc),
        }


def send_bulk_emails(
    leads: Iterable[dict[str, Any]],
    subject_template: str,
    body_template: str,
    config: Optional[EmailConfig] = None,
    dry_run: bool = False,
    verbose: bool = True,
    delay_between_sends: float = 0.0,
) -> dict[str, Any]:
    """
    Send personalized emails to many leads.

    Args:
        leads: Iterable of lead dicts
        subject_template: Subject line template with {field} placeholders
        body_template: Email body template with {field} placeholders
        config: EmailConfig (or load from env)
        dry_run: Print what would be sent, don't actually send
        verbose: Print progress
        delay_between_sends: Seconds to wait between sending each email

    Returns:
        Dict with total, sent, failed, skipped counts + detailed results list
    """
    lead_list = list(leads)
    results: list[dict[str, Any]] = []
    sent = 0
    failed = 0
    skipped = 0

    for i, lead in enumerate(lead_list):
        record = send_single_email(
            lead=lead,
            subject_template=subject_template,
            body_template=body_template,
            config=config,
            dry_run=dry_run,
            verbose=verbose,
        )
        results.append(record)

        if record.get("status") == "sent":
            sent += 1
        elif record.get("status") == "failed":
            failed += 1
        else:
            skipped += 1

        # Add delay between sends (except after last one)
        if delay_between_sends > 0 and i < len(lead_list) - 1:
            time.sleep(delay_between_sends)

    summary = {
        "total": len(lead_list),
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }

    if verbose:
        print(
            f"[email] Summary: {sent} sent, {failed} failed, {skipped} skipped",
            flush=True,
        )

    return summary


def load_template(path: Optional[str]) -> str:
    """Load email template from file, or return default."""
    if not path:
        return DEFAULT_EMAIL_TEMPLATE
    template_path = Path(path)
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {path}")
    return template_path.read_text(encoding="utf-8")


def main() -> None:
    """Simple CLI for sending emails."""
    import argparse

    parser = argparse.ArgumentParser(description="Send personalized emails to a list of leads.")
    parser.add_argument("--input", required=True, help="JSON file with lead objects")
    parser.add_argument("--subject", required=True, help="Email subject template (e.g., 'Hi {first_name}')")
    parser.add_argument("--template", help="Text template file. Defaults to a simple outreach template.")
    parser.add_argument("--dry-run", action="store_true", help="Do not actually send emails")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait between sends (default: 0)")
    parser.add_argument("--output", "-o", default="/tmp/opengtm-email-results.json", help="Results JSON path")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        leads = json.load(f)

    if not isinstance(leads, list):
        raise ValueError("The JSON input must be a list of lead objects.")

    body_template = load_template(args.template)
    config = EmailConfig.from_env()
    result = send_bulk_emails(
        leads=leads,
        subject_template=args.subject,
        body_template=body_template,
        config=config,
        dry_run=args.dry_run,
        verbose=True,
        delay_between_sends=args.delay,
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nResults -> {args.output}", flush=True)


if __name__ == "__main__":
    main()
