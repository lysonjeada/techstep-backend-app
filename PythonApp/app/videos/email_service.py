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