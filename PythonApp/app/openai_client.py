import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError(
        "A variável de ambiente OPENAI_API_KEY não foi configurada."
    )


client = OpenAI(
    api_key=OPENAI_API_KEY,
)


OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-4",
)