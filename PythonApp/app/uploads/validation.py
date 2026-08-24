"""Validação de upload compartilhada por todos os endpoints que
recebem arquivo do cliente (currículo em PDF, áudio de entrevista,
vídeo de apresentação).

Regras que todo upload precisa seguir:

1. Tamanho máximo é sempre aplicado com leitura em streaming — nunca
   confiamos em Content-Length (o cliente pode omitir ou mentir) nem
   carregamos o corpo inteiro na memória antes de checar o tamanho.
2. O tipo real do arquivo é verificado pelos primeiros bytes (magic
   bytes/assinatura de formato), nunca só pelo Content-Type que o
   cliente envia — esse header é só um chute do cliente, não uma
   garantia.
3. Nomes de arquivo salvos em disco são sempre gerados pelo servidor
   (UUID + extensão vinda de uma tabela fixa, nunca do filename ou
   Content-Type crus do cliente) — isso elimina qualquer superfície de
   path traversal via nome de arquivo.
"""

import os

from fastapi import HTTPException, UploadFile, status


CHUNK_SIZE = 1024 * 1024

MAX_PDF_SIZE_BYTES = (
    int(os.getenv("MAX_PDF_UPLOAD_SIZE_MB", "10")) * 1024 * 1024
)

MAX_AUDIO_SIZE_BYTES = (
    int(os.getenv("MAX_AUDIO_UPLOAD_SIZE_MB", "25")) * 1024 * 1024
)


async def read_upload_with_limit(
    file: UploadFile,
    max_bytes: int,
    *,
    detail: str,
) -> bytes:
    """Lê `file` em chunks, abortando com 413 assim que o total
    ultrapassa `max_bytes` — sem nunca materializar mais que
    `max_bytes` (+ um chunk) na memória, ao contrário de um
    `await file.read()` sem limite."""

    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(CHUNK_SIZE)

        if not chunk:
            break

        total += len(chunk)

        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=detail,
            )

        chunks.append(chunk)

    return b"".join(chunks)


# --- assinaturas de formato (magic bytes) ---


def looks_like_pdf(content: bytes) -> bool:
    return content[:5] == b"%PDF-"


def looks_like_iso_bmff(content: bytes) -> bool:
    """MP4/MOV/M4V/M4A (áudio ou vídeo): todos são contêineres
    ISO Base Media File Format, identificados pela box "ftyp" no
    offset 4."""

    return len(content) >= 8 and content[4:8] == b"ftyp"


def looks_like_webm(content: bytes) -> bool:
    return content[:4] == b"\x1a\x45\xdf\xa3"


def is_allowed_video_content(content: bytes) -> bool:
    return looks_like_iso_bmff(content) or looks_like_webm(content)


def is_allowed_audio_content(content: bytes) -> bool:
    return looks_like_iso_bmff(content)
