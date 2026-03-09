import os
import smtplib
import ssl
from email.message import EmailMessage


def send_email(to_email: str, subject: str, body: str) -> None:
    """
    Very simple email sender using SMTP.

    Configuration is taken from environment variables:
      - SMTP_HOST
      - SMTP_PORT
      - SMTP_USER (optional)
      - SMTP_PASSWORD (optional)
      - SMTP_USE_TLS ("1" to enable)
      - FROM_EMAIL (sender address)

    If configuration is missing or sending fails, the error is printed
    and the application continues without failing the request.
    """
    to_email = (to_email or "").strip()
    if not to_email:
        return

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "25"))
    from_email = os.getenv("FROM_EMAIL")
    use_tls = os.getenv("SMTP_USE_TLS", "0") == "1"
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_host or not from_email:
        # Email not configured; skip sending.
        print("Email not configured; skipping email to", to_email)
        return

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        # Use longer timeout and explicit SSL context for STARTTLS.
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if use_tls:
                server.starttls(context=context)
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
    except Exception as exc:
        # For this prototype just log the error instead of failing the request.
        print("Failed to send email to", to_email, "error:", exc)

