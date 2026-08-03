import pymupdf

def extract_text_from_pdf(
    pdf_bytes: bytes,
) -> str:
    if not pdf_bytes:
        return ""

    text_parts: list[str] = []

    with pymupdf.open(
        stream=pdf_bytes,
        filetype="pdf",
    ) as document:
        for page in document:
            page_text = page.get_text("text")

            if page_text:
                text_parts.append(page_text)

    return "\n".join(text_parts)