import os
import smtplib

from email.message import EmailMessage

from dotenv import load_dotenv


load_dotenv()


SMTP_HOST = os.getenv(
    "SMTP_HOST",
    "smtp.gmail.com",
)

SMTP_PORT = int(
    os.getenv(
        "SMTP_PORT",
        "587",
    )
)

SMTP_USERNAME = os.getenv(
    "SMTP_USERNAME"
)

SMTP_PASSWORD = os.getenv(
    "SMTP_PASSWORD"
)

SMTP_FROM_EMAIL = os.getenv(
    "SMTP_FROM_EMAIL"
)

VIDEO_REVIEW_EMAIL = os.getenv(
    "VIDEO_REVIEW_EMAIL",
    "techstep.app@gmail.com",
)


def send_video_review_email(
    *,
    title: str,
    uploader_email: str,
    review_url: str,
):
    message = EmailMessage()

    message["Subject"] = (
        f"Novo vídeo aguardando revisão: {title}"
    )

    message["From"] = SMTP_FROM_EMAIL
    message["To"] = VIDEO_REVIEW_EMAIL

    message.set_content(
        f"""
Novo vídeo enviado para o TechStep.

Título:
{title}

Enviado por:
{uploader_email}

Revisar:
{review_url}
"""
    )

    message.add_alternative(
        f"""
        <html>
            <body>
                <h2>Novo vídeo aguardando revisão</h2>

                <p>
                    <strong>Título:</strong>
                    {title}
                </p>

                <p>
                    <strong>Enviado por:</strong>
                    {uploader_email}
                </p>

                <p>
                    <a href="{review_url}">
                        Abrir página de revisão
                    </a>
                </p>
            </body>
        </html>
        """,
        subtype="html",
    )

    with smtplib.SMTP(
        SMTP_HOST,
        SMTP_PORT,
    ) as server:
        server.starttls()

        server.login(
            SMTP_USERNAME,
            SMTP_PASSWORD,
        )

        server.send_message(
            message
        )


def send_upload_review_email(
    *,
    title: str,
    uploader_email: str,
    review_url: str,
    thumbnail_review_url: str | None = None,
):
    """Envia vídeo (e, se houver, thumbnail customizada) num único
    e-mail — no upload, os dois ficam pendentes ao mesmo tempo, e
    mandar duas mensagens separadas (duas conexões SMTP quase
    simultâneas) demonstrou perder uma delas silenciosamente (sem
    exceção no servidor, mas sem chegar na caixa de entrada)."""

    message = EmailMessage()

    message["Subject"] = (
        f"Novo vídeo aguardando revisão: {title}"
    )

    message["From"] = SMTP_FROM_EMAIL
    message["To"] = VIDEO_REVIEW_EMAIL

    thumbnail_text = (
        f"""

Uma thumbnail customizada também foi enviada e precisa de revisão separada:
{thumbnail_review_url}
"""
        if thumbnail_review_url
        else ""
    )

    message.set_content(
        f"""
Novo vídeo enviado para o TechStep.

Título:
{title}

Enviado por:
{uploader_email}

Revisar vídeo:
{review_url}
{thumbnail_text}"""
    )

    thumbnail_html = (
        f"""
                <p>
                    Uma thumbnail customizada também foi enviada e
                    precisa de revisão separada:
                </p>

                <p>
                    <a href="{thumbnail_review_url}">
                        Revisar thumbnail
                    </a>
                </p>
        """
        if thumbnail_review_url
        else ""
    )

    message.add_alternative(
        f"""
        <html>
            <body>
                <h2>Novo vídeo aguardando revisão</h2>

                <p>
                    <strong>Título:</strong>
                    {title}
                </p>

                <p>
                    <strong>Enviado por:</strong>
                    {uploader_email}
                </p>

                <p>
                    <a href="{review_url}">
                        Revisar vídeo
                    </a>
                </p>
                {thumbnail_html}
            </body>
        </html>
        """,
        subtype="html",
    )

    with smtplib.SMTP(
        SMTP_HOST,
        SMTP_PORT,
    ) as server:
        server.starttls()

        server.login(
            SMTP_USERNAME,
            SMTP_PASSWORD,
        )

        server.send_message(
            message
        )


def send_thumbnail_review_email(
    *,
    title: str,
    uploader_email: str,
    review_url: str,
):
    message = EmailMessage()

    message["Subject"] = (
        f"Nova thumbnail aguardando revisão: {title}"
    )

    message["From"] = SMTP_FROM_EMAIL
    message["To"] = VIDEO_REVIEW_EMAIL

    message.set_content(
        f"""
Nova thumbnail de vídeo enviada para o TechStep.

Vídeo:
{title}

Enviado por:
{uploader_email}

Revisar:
{review_url}
"""
    )

    message.add_alternative(
        f"""
        <html>
            <body>
                <h2>Nova thumbnail aguardando revisão</h2>

                <p>
                    <strong>Vídeo:</strong>
                    {title}
                </p>

                <p>
                    <strong>Enviado por:</strong>
                    {uploader_email}
                </p>

                <p>
                    <a href="{review_url}">
                        Abrir página de revisão
                    </a>
                </p>
            </body>
        </html>
        """,
        subtype="html",
    )

    with smtplib.SMTP(
        SMTP_HOST,
        SMTP_PORT,
    ) as server:
        server.starttls()

        server.login(
            SMTP_USERNAME,
            SMTP_PASSWORD,
        )

        server.send_message(
            message
        )