import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr


def send_verification_email(
    recipient_email: str,
    recipient_name: str,
    code: str,
) -> None:
    smtp_host = os.getenv(
        "SMTP_HOST"
    )

    smtp_port = int(
        os.getenv(
            "SMTP_PORT",
            "587",
        )
    )

    smtp_username = os.getenv(
        "SMTP_USERNAME"
    )

    smtp_password = os.getenv(
        "SMTP_PASSWORD"
    )

    from_email = os.getenv(
        "SMTP_FROM_EMAIL",
        smtp_username or "",
    )

    from_name = os.getenv(
        "SMTP_FROM_NAME",
        "TechStep",
    )

    required_values = {
        "SMTP_HOST": smtp_host,
        "SMTP_USERNAME": smtp_username,
        "SMTP_PASSWORD": smtp_password,
        "SMTP_FROM_EMAIL": from_email,
    }

    missing = [
        key
        for key, value
        in required_values.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Configurações SMTP ausentes: "
            + ", ".join(missing)
        )

    message = EmailMessage()

    message["Subject"] = (
        "Seu código de verificação da TechStep"
    )

    message["From"] = formataddr(
        (
            from_name,
            from_email,
        )
    )

    message["To"] = recipient_email

    message.set_content(
        f"""
Olá, {recipient_name}!

Seu código de verificação da TechStep é:

{code}

Este código expira em 10 minutos.

Caso você não tenha solicitado este cadastro,
ignore esta mensagem.

TechStep
        """.strip()
    )

    message.add_alternative(
        f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
</head>
<body style="
    font-family: Arial, sans-serif;
    background: #f4f5f8;
    padding: 32px;
">
    <div style="
        max-width: 520px;
        margin: auto;
        background: white;
        border-radius: 16px;
        padding: 32px;
    ">
        <h1 style="
            color: #2733a2;
            margin-top: 0;
        ">
            Confirme seu e-mail
        </h1>

        <p>
            Olá, {recipient_name}!
        </p>

        <p>
            Use o código abaixo para concluir
            seu cadastro na TechStep:
        </p>

        <div style="
            font-size: 34px;
            font-weight: bold;
            letter-spacing: 10px;
            text-align: center;
            color: #2733a2;
            padding: 24px 0;
        ">
            {code}
        </div>

        <p>
            O código expira em 10 minutos.
        </p>

        <p style="
            color: #777;
            font-size: 13px;
        ">
            Caso você não tenha solicitado
            este cadastro, ignore esta mensagem.
        </p>
    </div>
</body>
</html>
        """.strip(),
        subtype="html",
    )

    with smtplib.SMTP(
        smtp_host,
        smtp_port,
        timeout=20,
    ) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()

        server.login(
            smtp_username,
            smtp_password,
        )

        server.send_message(message)