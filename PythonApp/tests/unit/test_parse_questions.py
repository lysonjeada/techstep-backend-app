import pytest

from app.interview_simulation.router import (
    parse_questions as parse_simulation_questions,
)
from app.llm_generation.router import parse_questions as parse_interview_questions

pytestmark = pytest.mark.unit


# --- app.llm_generation.router.parse_questions (limit of 7) ---


def test_parse_questions_strips_numbered_dot_format():
    content = "1. Qual sua experiência com Python?\n2. Descreva um desafio."

    result = parse_interview_questions(content)

    assert result == [
        "Qual sua experiência com Python?",
        "Descreva um desafio.",
    ]


def test_parse_questions_strips_numbered_parenthesis_format():
    content = "1) Pergunta um\n2) Pergunta dois"

    result = parse_interview_questions(content)

    assert result == ["Pergunta um", "Pergunta dois"]


@pytest.mark.parametrize("bullet", ["-", "*", "•"])
def test_parse_questions_strips_bullet_formats(bullet):
    content = f"{bullet} Pergunta com marcador"

    result = parse_interview_questions(content)

    assert result == ["Pergunta com marcador"]


def test_parse_questions_keeps_plain_lines_without_markers():
    content = "Pergunta sem marcador nenhum"

    result = parse_interview_questions(content)

    assert result == ["Pergunta sem marcador nenhum"]


def test_parse_questions_skips_empty_lines():
    content = "1. Primeira\n\n\n2. Segunda"

    result = parse_interview_questions(content)

    assert result == ["Primeira", "Segunda"]


def test_parse_questions_is_limited_to_seven():
    content = "\n".join(f"{i}. Pergunta {i}" for i in range(1, 11))

    result = parse_interview_questions(content)

    assert len(result) == 7
    assert result == [f"Pergunta {i}" for i in range(1, 8)]


def test_parse_questions_returns_empty_list_for_blank_content():
    assert parse_interview_questions("") == []
    assert parse_interview_questions("\n\n   \n") == []


# --- app.interview_simulation.router.parse_questions (no internal limit) ---


def test_simulation_parse_questions_strips_bullet_markers():
    content = "- Pergunta A\n* Pergunta B\n• Pergunta C"

    result = parse_simulation_questions(content)

    assert result == ["Pergunta A", "Pergunta B", "Pergunta C"]


def test_simulation_parse_questions_does_not_truncate_to_seven():
    content = "\n".join(f"{i}. Pergunta {i}" for i in range(1, 11))

    result = parse_simulation_questions(content)

    assert len(result) == 10
