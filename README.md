# TechStep Backend API

Backend em **FastAPI** para apoiar pessoas em processos seletivos e preparação de carreira. A API centraliza cadastro e autenticação de usuários, acompanhamento de entrevistas, geração de perguntas técnicas com IA, feedback de currículo, simulação de entrevistas, planos de estudo, dashboard de progresso e consulta de vagas publicadas em repositórios do GitHub.

> A aplicação principal está dentro do diretório `PythonApp/`. Execute os comandos deste README a partir desse diretório, salvo quando indicado o contrário.

## Sumário

- [Funcionalidades](#funcionalidades)
- [Stack técnica](#stack-técnica)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Pré-requisitos](#pré-requisitos)
- [Instalação local](#instalação-local)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Executando a API](#executando-a-api)
- [Banco de dados e migrações](#banco-de-dados-e-migrações)
- [Docker, Redis e Celery](#docker-redis-e-celery)
- [Endpoints principais](#endpoints-principais)
- [Observações e limitações conhecidas](#observações-e-limitações-conhecidas)
- [Segurança](#segurança)

## Funcionalidades

- Cadastro e login de usuários.
- Verificação de e-mail por código.
- Autenticação com token JWT.
- CRUD de entrevistas e processos seletivos.
- Listagem de próximas entrevistas.
- Geração de perguntas técnicas com IA.
- Upload e análise de currículo em PDF.
- Feedback de currículo de forma síncrona ou assíncrona via Celery.
- Simulação de entrevistas com:
  - geração de perguntas;
  - transcrição de áudio;
  - avaliação das respostas;
  - salvamento de perguntas geradas.
- Geração de plano de estudos personalizado.
- Dashboard de progresso com métricas por período.
- Consulta de vagas abertas em issues de repositórios públicos do GitHub.

## Stack técnica

- **Python 3.11**
- **FastAPI**
- **Uvicorn**
- **SQLAlchemy**
- **PostgreSQL** com `psycopg2-binary`
- **Alembic** para migrações
- **Celery** para processamento assíncrono
- **Redis** como broker/backend do Celery
- **OpenAI SDK** para recursos de IA
- **python-dotenv** para variáveis de ambiente
- **python-multipart** para upload de arquivos
- **python-jose**, **PyJWT**, **passlib** e **pwdlib** para autenticação e segurança
- **pypdf/fitz** para leitura de PDFs
- **requests** para integração com a API do GitHub

> O arquivo `requirements.txt` atualmente não fixa versões exatas para a maior parte das dependências. Em ambientes de produção, é recomendável fixar versões para builds mais previsíveis.

## Estrutura do projeto

```text
techstep-backend-app/
├── PythonApp/
│   ├── app/
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── auth/
│   │   ├── interviews/
│   │   ├── llm_generation/
│   │   ├── interview_simulation/
│   │   ├── study_plan/
│   │   ├── dashboard/
│   │   ├── jobs_service/
│   │   └── worker/
│   ├── alembic/
│   │   └── versions/
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── Dockerfile
│   └── docker-compose.yml
├── docker-compose.yml
└── README.md
```

### Principais módulos

- `PythonApp/app/main.py`: entrada principal da aplicação FastAPI modular.
- `PythonApp/app/database.py`: configuração do SQLAlchemy, engine, sessão e dependência `get_db()`.
- `PythonApp/app/models.py`: modelos principais de banco, como `User` e `Interview`.
- `PythonApp/app/schemas.py`: schemas Pydantic compartilhados.
- `PythonApp/app/auth/`: cadastro, login, JWT, hash de senha, verificação de e-mail e envio SMTP.
- `PythonApp/app/interviews/`: endpoints de entrevistas/processos seletivos.
- `PythonApp/app/llm_generation/`: geração de perguntas, extração de PDF e feedback de currículo.
- `PythonApp/app/interview_simulation/`: simulação de entrevista, transcrição, avaliação e perguntas salvas.
- `PythonApp/app/study_plan/`: geração de plano de estudos com IA.
- `PythonApp/app/dashboard/`: métricas e evolução de progresso.
- `PythonApp/app/jobs_service/`: consulta de vagas em issues de repositórios do GitHub.
- `PythonApp/app/worker/`: configuração Celery e tasks assíncronas.
- `PythonApp/alembic/versions/`: histórico de migrações do banco.

## Pré-requisitos

- Python 3.11 ou superior.
- PostgreSQL acessível localmente ou via URL remota.
- Redis, necessário para filas Celery.
- Chave da OpenAI para recursos de IA.
- Configuração SMTP para envio de códigos de verificação de e-mail.
- Docker e Docker Compose, opcionalmente, para Redis/Celery.

## Instalação local

A partir da raiz do repositório:

```bash
cd PythonApp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

No Windows, a ativação do ambiente virtual pode ser feita com:

```bash
.venv\Scripts\activate
```

## Variáveis de ambiente

Crie um arquivo `.env` dentro de `PythonApp/`:

```bash
cd PythonApp
touch .env
```

Exemplo de variáveis esperadas:

```env
DATABASE_URL=postgresql://usuario:senha@localhost:5432/nome_do_banco

OPENAI_API_KEY=sua_chave_openai
OPENAI_MODEL=gpt-4
OPENAI_INTERVIEW_MODEL=gpt-4

JWT_SECRET_KEY=uma_chave_segura_para_jwt
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

SMTP_HOST=smtp.exemplo.com
SMTP_PORT=587
SMTP_USERNAME=usuario_smtp
SMTP_PASSWORD=senha_smtp
SMTP_FROM_EMAIL=no-reply@exemplo.com
SMTP_FROM_NAME=TechStep

EMAIL_VERIFICATION_PEPPER=valor_aleatorio_seguro
EMAIL_VERIFICATION_EXPIRATION_MINUTES=10
EMAIL_VERIFICATION_RESEND_SECONDS=60
EMAIL_VERIFICATION_MAX_ATTEMPTS=5

CELERY_BROKER_URL=redis://localhost:6379
CELERY_RESULT_BACKEND=redis://localhost:6379

GITHUB_TOKEN=token_github_opcional
```

### Descrição das variáveis

| Variável | Descrição |
| --- | --- |
| `DATABASE_URL` | URL de conexão com o PostgreSQL. |
| `OPENAI_API_KEY` | Chave da OpenAI usada nos recursos de IA. |
| `OPENAI_MODEL` | Modelo padrão usado por serviços como plano de estudos. |
| `OPENAI_INTERVIEW_MODEL` | Modelo usado em geração/simulação de entrevistas. |
| `JWT_SECRET_KEY` | Chave secreta para assinatura de tokens JWT. |
| `JWT_ALGORITHM` | Algoritmo de assinatura JWT. Padrão: `HS256`. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Tempo de expiração do token de acesso. |
| `SMTP_HOST` | Host do servidor SMTP. |
| `SMTP_PORT` | Porta do servidor SMTP. Padrão comum: `587`. |
| `SMTP_USERNAME` | Usuário SMTP. |
| `SMTP_PASSWORD` | Senha SMTP. |
| `SMTP_FROM_EMAIL` | E-mail remetente das mensagens de verificação. |
| `SMTP_FROM_NAME` | Nome exibido como remetente. |
| `EMAIL_VERIFICATION_PEPPER` | Valor secreto usado no hash dos códigos de verificação. |
| `EMAIL_VERIFICATION_EXPIRATION_MINUTES` | Tempo de expiração do código de verificação. |
| `EMAIL_VERIFICATION_RESEND_SECONDS` | Intervalo mínimo para reenviar código. |
| `EMAIL_VERIFICATION_MAX_ATTEMPTS` | Número máximo de tentativas de validação do código. |
| `CELERY_BROKER_URL` | URL do broker Celery. |
| `CELERY_RESULT_BACKEND` | Backend de resultados do Celery. |
| `GITHUB_TOKEN` | Token opcional para consultar a API do GitHub com maior limite de requisições. |

> Nunca versione o arquivo `.env`. Tokens, senhas, URLs com credenciais e chaves secretas devem ser mantidos fora do Git.

## Executando a API

A aplicação modular principal está em `PythonApp/app/main.py`. Para rodar localmente:

```bash
cd PythonApp
uvicorn app.main:app --reload
```

A API ficará disponível em:

- `http://localhost:8000`
- `http://localhost:8000/docs` — documenta��ão Swagger/OpenAPI.
- `http://localhost:8000/redoc` — documentação ReDoc.

## Banco de dados e migrações

O projeto usa PostgreSQL com SQLAlchemy e possui migrações Alembic.

Para aplicar as migrações existentes:

```bash
cd PythonApp
alembic upgrade head
```

Para criar uma nova migração automaticamente:

```bash
cd PythonApp
alembic revision --autogenerate -m "descricao_da_migration"
alembic upgrade head
```

> Observação: `PythonApp/app/main.py` também executa `Base.metadata.create_all(bind=database.engine)`, o que cria tabelas automaticamente a partir dos models. Como o projeto também usa Alembic, o fluxo recomendado para ambientes compartilhados e produção é padronizar o uso de migrações.

## Docker, Redis e Celery

O arquivo `PythonApp/docker-compose.yml` define os serviços:

- `redis`
- `celery_worker`

Para subir os serviços configurados:

```bash
cd PythonApp
docker compose up
```

Para executar o worker Celery manualmente:

```bash
cd PythonApp
celery -A app.worker.celery_app -I app.worker.tasks worker --loglevel=info
```

Se o Celery estiver rodando localmente fora do Docker, as URLs Redis geralmente usam `localhost`:

```env
CELERY_BROKER_URL=redis://localhost:6379
CELERY_RESULT_BACKEND=redis://localhost:6379
```

Se o worker estiver rodando dentro do Docker Compose, pode ser necessário apontar para o hostname do serviço:

```env
CELERY_BROKER_URL=redis://redis:6379
CELERY_RESULT_BACKEND=redis://redis:6379
```

> O `docker-compose.yml` dentro de `PythonApp/` não sobe a API FastAPI nem um serviço PostgreSQL; ele cobre apenas Redis e Celery worker.

## Endpoints principais

Os detalhes completos de payloads, schemas e respostas ficam disponíveis em `/docs` após iniciar a API. Abaixo está um resumo dos principais endpoints.

### Autenticação e usuários

Prefixo: `/users`

| Método | Endpoint | Descrição |
| --- | --- | --- |
| `POST` | `/users/register` | Cadastra um usuário e envia código de verificação por e-mail. |
| `POST` | `/users/verify-email` | Valida o código de verificação de e-mail. |
| `POST` | `/users/resend-verification` | Reenvia o código de verificação. |
| `POST` | `/users/login/` | Autentica o usuário e retorna token JWT. |
| `GET` | `/users/{user_id}` | Busca um usuário por ID. |
| `PUT` | `/users/{user_id}` | Atualiza dados de um usuário. |
| `DELETE` | `/users/{user_id}` | Remove um usuário. |

### Entrevistas

Prefixo: `/interviews`

| Método | Endpoint | Descrição |
| --- | --- | --- |
| `POST` | `/interviews/` | Cria uma entrevista/processo seletivo. |
| `GET` | `/interviews/` | Lista entrevistas. |
| `GET` | `/interviews/{interview_id}` | Busca uma entrevista por ID. |
| `PUT` | `/interviews/{interview_id}` | Atualiza uma entrevista. |
| `DELETE` | `/interviews/{interview_id}` | Remove uma entrevista. |
| `GET` | `/interviews/next/` | Lista próximas entrevistas. |

### IA e currículo

| Método | Endpoint | Descrição |
| --- | --- | --- |
| `POST` | `/generate-interview-questions/` | Gera perguntas técnicas com base em cargo, senioridade, descrição e currículo opcional. |
| `POST` | `/resume-feedback/` | Gera feedback síncrono para um currículo em PDF. |
| `POST` | `/submit-feedback/` | Envia currículo para processamento assíncrono via Celery. |
| `GET` | `/feedback-status/{task_id}` | Consulta o status de uma task Celery. |
| `GET` | `/feedback-result/{task_id}` | Retorna o feedback quando a task estiver concluída. |

### Simulação de entrevistas

| Método | Endpoint | Descrição |
| --- | --- | --- |
| `POST` | `/interview-simulation/questions` | Gera perguntas para uma entrevista simulada. |
| `POST` | `/interview-simulation/transcribe` | Transcreve áudio de resposta usando OpenAI Whisper. |
| `POST` | `/interview-simulation/evaluate` | Avalia respostas da entrevista simulada. |
| `POST` | `/interview-simulation/saved-questions` | Salva perguntas geradas no banco. |

### Plano de estudos

Prefixo: `/study-plan`

| Método | Endpoint | Descrição |
| --- | --- | --- |
| `POST` | `/study-plan/generate` | Gera um plano de estudos personalizado. |

### Dashboard

Prefixo: `/dashboard`

| Método | Endpoint | Descrição |
| --- | --- | --- |
| `GET` | `/dashboard/progress` | Retorna métricas de progresso, skills, empresas ativas e evolução mensal. |

### Vagas via GitHub

| Método | Endpoint | Descrição |
| --- | --- | --- |
| `GET` | `/repositories-available/` | Lista os repositórios disponíveis para busca de vagas. |
| `GET` | `/job-listings/` | Lista vagas a partir de issues abertas dos repositórios configurados. |

Repositórios consultados atualmente:

- `frontendbr/vagas`
- `backend-br/vagas`
- `soujava/vagas-java`
- `remotejobsbr/design-ux-vagas`
- `remoteintech/remote-jobs`
- `datascience-br/vagas`
- `dotnetdevbr/vagas`

## Observações e limitações conhecidas

- A aplicação modular principal está em `PythonApp/app/main.py`.
- O `PythonApp/Dockerfile` atualmente executa `uvicorn main:app`, apontando para `PythonApp/main.py`. Esse arquivo aparenta ser legado/incompleto em relação à estrutura modular atual. Para execução local, prefira `uvicorn app.main:app --reload`.
- O `PythonApp/docker-compose.yml` não sobe a API FastAPI nem PostgreSQL; apenas Redis e Celery worker.
- O projeto possui Alembic, mas `app/main.py` também chama `Base.metadata.create_all(...)`. O ideal é padronizar o uso de migrações para ambientes compartilhados e produção.
- O arquivo `PythonApp/alembic.ini` contém uma URL de banco configurada diretamente. Evite reproduzir credenciais em documentação e considere migrar essa configuração para variável de ambiente.
- O arquivo `PythonApp/.env`, quando existir, pode conter segredos reais e não deve ser commitado.
- O `requirements.txt` não fixa versões, então instalações em momentos diferentes podem resolver versões distintas.
- Recursos de IA dependem de `OPENAI_API_KEY` válido.
- Consulta de vagas usa a API do GitHub e pode depender de `GITHUB_TOKEN` para evitar limites de requisição.
- Verificação de e-mail depende de configuração SMTP funcional.

## Segurança

Antes de commitar ou publicar este projeto, verifique se nenhum segredo foi incluído no Git:

- `.env`
- chaves OpenAI;
- tokens GitHub;
- credenciais SMTP;
- senha do banco;
- `JWT_SECRET_KEY`;
- URLs de banco com usuário e senha.

Também é recomendável manter um `.env.example` versionado com apenas nomes de variáveis e placeholders, sem valores reais.
