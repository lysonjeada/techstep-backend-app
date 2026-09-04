import os

# Custo em créditos por feature de IA. Centralizado aqui para nunca
# espalhar "-1"/"cost=1" pelos routers — mudar o custo de uma feature é
# uma edição neste dict, não uma caça por vários arquivos.
AI_FEATURE_COSTS: dict[str, int] = {
    "generate_questions": 1,
    "resume_feedback": 1,
    "resume_feedback_submit": 1,
    "simulation_questions": 1,
    "simulation_transcribe": 1,
    "simulation_evaluate": 1,
    "study_plan": 1,
}

# Limite gratuito por usuário, por janela de tempo, antes de precisar de
# créditos comprados. Os defaults abaixo preservam o comportamento
# gratuito atual (RATE_LIMIT_OPENAI_MAX/RATE_LIMIT_OPENAI_WINDOW_SECONDS
# = 20 requisições/hora, hoje por IP) — só passam a ser contados por
# usuário em vez de por IP. Não é uma redução do limite gratuito
# existente; são env vars próprias para poder ajustar sem afetar os
# outros escopos de rate limit (login, registro, upload de vídeo etc).
AI_CREDIT_FREE_LIMIT = int(
    os.getenv("AI_CREDIT_FREE_LIMIT_PER_WINDOW", "20")
)

AI_CREDIT_FREE_WINDOW_SECONDS = int(
    os.getenv("AI_CREDIT_FREE_WINDOW_SECONDS", "3600")
)

# Fonte central de verdade: product_id (Apple) -> créditos concedidos.
# O backend NUNCA confia em uma quantidade de créditos enviada pelo
# cliente — sempre resolve pelo product_id verificado na transação
# assinada pela Apple. Os mesmos valores existem no iOS em
# AICreditProduct.swift; não há como compartilhar código entre Swift e
# Python, então qualquer mudança aqui precisa ser replicada lá também.
AI_CREDIT_PRODUCTS: dict[str, int] = {
    "lys.com.career-app.credits.10": 10,
    "lys.com.career-app.credits.30": 30,
    "lys.com.career-app.credits.100": 100,
}

# Mesma ideia para compras Android via Google Play Billing. Os IDs abaixo
# são PLACEHOLDERS — o app Android ainda não tem produtos cadastrados no
# Play Console. Troque pelos IDs reais assim que forem criados lá (e
# replique a troca em AICreditProduct no app Android).
AI_CREDIT_PRODUCTS_GOOGLE: dict[str, int] = {
    "credits_10": 10,
    "credits_30": 30,
    "credits_100": 100,
}
