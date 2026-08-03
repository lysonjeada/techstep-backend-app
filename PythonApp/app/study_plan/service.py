import asyncio
import json
import re

from typing import Any, Dict, List

def build_study_plan_prompt(
    job_title: str,
    seniority: str,
    description: str = "",
    resume_text: str = "",
) -> str:
    context_parts = [
        "Cargo desejado: {}".format(job_title),
        "Senioridade: {}".format(seniority),
    ]

    if description:
        context_parts.append(
            "Descrição da vaga:\n{}".format(
                description
            )
        )

    if resume_text:
        context_parts.append(
            "Currículo da pessoa candidata:\n{}".format(
                resume_text
            )
        )

    context = "\n\n".join(context_parts)

    return """
Crie um plano de estudos personalizado para preparação
para a vaga abaixo.

{context}

O plano deve:

- Ter entre 5 e 8 tópicos.
- Adaptar a dificuldade à senioridade.
- Priorizar habilidades exigidas na descrição da vaga.
- Identificar possíveis lacunas do currículo, quando houver currículo.
- Não inventar informações sobre o currículo.
- Incluir fundamentos, prática e arquitetura quando aplicável.
- Informar uma estimativa realista de horas.
- Sugerir uma atividade prática para cada tópico.

Retorne somente um objeto JSON válido, sem markdown,
sem introduções e sem blocos de código.

Formato obrigatório:

{{
    "title": "Plano de estudos para Cargo",
    "summary": "Resumo curto da estratégia do plano",
    "estimated_total_hours": 20,
    "topics": [
        {{
            "title": "Nome do tópico",
            "description": "Por que esse tópico é importante",
            "priority": "high",
            "estimated_hours": 4,
            "subtopics": [
                "Subtópico 1",
                "Subtópico 2"
            ],
            "practice": "Atividade prática sugerida"
        }}
    ]
}}

O campo priority deve conter somente:
high, medium ou low.
""".format(
        context=context
    ).strip()


async def create_study_plan(
    client,
    model: str,
    job_title: str,
    seniority: str,
    description: str = "",
    resume_text: str = "",
) -> Dict[str, Any]:
    prompt = build_study_plan_prompt(
        job_title=job_title,
        seniority=seniority,
        description=description,
        resume_text=resume_text,
    )

    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um especialista em carreira, "
                    "entrevistas técnicas e criação de "
                    "planos de estudo personalizados. "
                    "Responda somente com JSON válido."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.4,
    )

    if not response.choices:
        raise ValueError(
            "A OpenAI não retornou uma resposta."
        )

    content = (
        response.choices[0].message.content
        or ""
    )

    print(
        "📚 Plano recebido da OpenAI:",
        content,
        flush=True,
    )

    plan = extract_json(content)

    return normalize_study_plan(plan)


def extract_json(
    content: str,
) -> Dict[str, Any]:
    if not content or not content.strip():
        raise ValueError(
            "A OpenAI retornou uma resposta vazia."
        )

    normalized = content.strip()

    normalized = normalized.replace(
        "```json",
        "",
    )

    normalized = normalized.replace(
        "```",
        "",
    )

    start_index = normalized.find("{")
    end_index = normalized.rfind("}")

    if start_index == -1 or end_index == -1:
        raise ValueError(
            "A OpenAI não retornou um JSON válido."
        )

    json_content = normalized[
        start_index:end_index + 1
    ]

    try:
        return json.loads(json_content)

    except json.JSONDecodeError as error:
        print(
            "❌ JSON inválido:",
            json_content,
            flush=True,
        )

        raise ValueError(
            "JSON inválido retornado pela OpenAI: {}".format(
                error.msg
            )
        )


def normalize_study_plan(
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    raw_topics = plan.get(
        "topics",
        [],
    )

    if not isinstance(raw_topics, list):
        raw_topics = []

    normalized_topics: List[Dict[str, Any]] = []

    for raw_topic in raw_topics:
        if not isinstance(raw_topic, dict):
            continue

        title = str(
            raw_topic.get(
                "title",
                "",
            )
        ).strip()

        if not title:
            continue

        description = str(
            raw_topic.get(
                "description",
                "",
            )
        ).strip()

        priority = normalize_priority(
            raw_topic.get(
                "priority",
                "medium",
            )
        )

        estimated_hours = safe_int(
            raw_topic.get(
                "estimated_hours",
                1,
            ),
            default=1,
        )

        estimated_hours = max(
            1,
            min(estimated_hours, 40),
        )

        subtopics = normalize_string_list(
            raw_topic.get(
                "subtopics",
                [],
            )
        )

        practice = str(
            raw_topic.get(
                "practice",
                "",
            )
        ).strip()

        normalized_topics.append(
            {
                "title": title,
                "description": description,
                "priority": priority,
                "estimated_hours": estimated_hours,
                "subtopics": subtopics,
                "practice": practice,
            }
        )

    if not normalized_topics:
        raise ValueError(
            "Nenhum tópico válido foi gerado."
        )

    calculated_hours = sum(
        topic["estimated_hours"]
        for topic in normalized_topics
    )

    total_hours = safe_int(
        plan.get(
            "estimated_total_hours",
            calculated_hours,
        ),
        default=calculated_hours,
    )

    total_hours = max(
        calculated_hours,
        total_hours,
    )

    title = str(
        plan.get(
            "title",
            "Plano de estudos",
        )
    ).strip()

    summary = str(
        plan.get(
            "summary",
            "Plano personalizado para a vaga.",
        )
    ).strip()

    return {
        "title": title or "Plano de estudos",
        "summary": (
            summary
            or "Plano personalizado para a vaga."
        ),
        "estimated_total_hours": total_hours,
        "topics": normalized_topics,
    }


def normalize_priority(
    value: Any,
) -> str:
    normalized = str(value).strip().lower()

    priority_map = {
        "high": "high",
        "alta": "high",
        "alto": "high",
        "medium": "medium",
        "média": "medium",
        "media": "medium",
        "médio": "medium",
        "medio": "medium",
        "low": "low",
        "baixa": "low",
        "baixo": "low",
    }

    return priority_map.get(
        normalized,
        "medium",
    )


def normalize_string_list(
    value: Any,
) -> List[str]:
    if not isinstance(value, list):
        return []

    normalized_values = []

    for item in value:
        normalized_item = str(item).strip()

        if normalized_item:
            normalized_values.append(
                normalized_item
            )

    return normalized_values


def safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(value)

    except (TypeError, ValueError):
        match = re.search(
            r"\d+",
            str(value),
        )

        if match:
            return int(match.group())

        return default