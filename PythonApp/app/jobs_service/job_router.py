import requests
import os
from fastapi import APIRouter, HTTPException, Query

job_router = APIRouter()

REPOSITORIES = [
    "frontendbr/vagas",
    "backend-br/vagas",
    "soujava/vagas-java",
    "remotejobsbr/design-ux-vagas",
    "remoteintech/remote-jobs",
    "datascience-br/vagas",
    "dotnetdevbr/vagas"
]

@job_router.get("/repositories-available/")
def list_github_repositories_available():
    return REPOSITORIES


@job_router.get("/job-listings/")
def list_github_jobs(repository: str = Query(None, description="Nome do repositório a filtrar")):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"
    }

    repos_to_fetch = []

    if repository:
        if repository not in REPOSITORIES:
            raise HTTPException(status_code=400, detail="Repositório inválido")
        repos_to_fetch = [repository]
    else:
        repos_to_fetch = REPOSITORIES

    results = []

    for repo in repos_to_fetch:
        url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=10"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            issues = response.json()
            for issue in issues:
                if "pull_request" in issue:
                    continue
                results.append({
                    "title": issue.get("title"),
                    "icon": issue.get("user", {}).get("avatar_url"),
                    "url": issue.get("html_url"),
                    "published_at": issue.get("created_at"),
                    "updated_at": issue.get("updated_at"),
                    "labels": [label["name"] for label in issue.get("labels", [])],
                    "repository": repo
                })
        except requests.RequestException as e:
            print(f"❌ Erro ao acessar {url}: {e}")
            continue

    return sorted(results, key=lambda x: x["published_at"], reverse=True)
