from collections import Counter
from datetime import date
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.models import Interview


ACTIVE_STATUSES = {
    "applied",
    "screening",
    "interview",
    "challenge",
    "offer",
}

RESPONSE_STATUSES = {
    "screening",
    "interview",
    "challenge",
    "offer",
    "accepted",
    "rejected",
}

OFFER_STATUSES = {
    "offer",
    "accepted",
}


def build_progress_dashboard(
    db: Session,
    months: int = 6,
) -> Dict[str, Any]:
    applications = db.query(Interview).all()
    today = date.today()

    total_applications = len(applications)

    completed_interviews = sum(
        1
        for application in applications
        if application.last_interview_date is not None
        and application.last_interview_date <= today
    )

    scheduled_interviews = sum(
        1
        for application in applications
        if application.next_interview_date is not None
        and application.next_interview_date >= today
    )

    responses_count = sum(
        1
        for application in applications
        if _has_received_response(application)
    )

    response_rate = (
        round(
            responses_count / total_applications * 100,
            1,
        )
        if total_applications > 0
        else 0.0
    )

    offers_count = sum(
        1
        for application in applications
        if _normalize_status(application) in OFFER_STATUSES
    )

    active_companies = _build_active_companies(
        applications
    )

    top_skills = _build_top_skills(
        applications=applications,
        total_applications=total_applications,
    )

    monthly_evolution = _build_monthly_evolution(
        applications=applications,
        months=months,
    )

    return {
        "summary": {
            "total_applications": total_applications,
            "completed_interviews": completed_interviews,
            "scheduled_interviews": scheduled_interviews,
            "response_rate": response_rate,
            "offers_count": offers_count,
            "active_companies_count": len(active_companies),
        },
        "top_skills": top_skills,
        "active_companies": active_companies,
        "monthly_evolution": monthly_evolution,
    }


def _normalize_status(
    application: Interview,
) -> str:
    status = getattr(
        application,
        "status",
        None,
    )

    return (
        status.strip().lower()
        if status
        else "applied"
    )


def _has_received_response(
    application: Interview,
) -> bool:
    if application.last_interview_date is not None:
        return True

    if application.next_interview_date is not None:
        return True

    return (
        _normalize_status(application)
        in RESPONSE_STATUSES
    )


def _build_top_skills(
    applications: List[Interview],
    total_applications: int,
) -> List[Dict[str, Any]]:
    skill_counter = Counter()

    for application in applications:
        for skill in application.skills or []:
            normalized_skill = str(skill).strip()

            if normalized_skill:
                skill_counter[
                    normalized_skill
                ] += 1

    result = []

    for skill, count in skill_counter.most_common(8):
        percentage = (
            round(
                count / total_applications * 100,
                1,
            )
            if total_applications > 0
            else 0.0
        )

        result.append(
            {
                "skill": skill,
                "count": count,
                "percentage": percentage,
            }
        )

    return result


def _build_active_companies(
    applications: List[Interview],
) -> List[Dict[str, Any]]:
    companies: Dict[str, Dict[str, Any]] = {}

    for application in applications:
        status = _normalize_status(application)

        if status not in ACTIVE_STATUSES:
            continue

        company_name = (
            application.company_name or ""
        ).strip()

        if not company_name:
            continue

        latest_activity = (
            application.updated_at
            or application.created_at
        )

        if company_name not in companies:
            companies[company_name] = {
                "company_name": company_name,
                "active_processes": 0,
                "latest_activity": latest_activity,
            }

        companies[company_name][
            "active_processes"
        ] += 1

        current_latest = companies[
            company_name
        ]["latest_activity"]

        if (
            latest_activity is not None
            and (
                current_latest is None
                or latest_activity > current_latest
            )
        ):
            companies[company_name][
                "latest_activity"
            ] = latest_activity

    return sorted(
        companies.values(),
        key=lambda item: (
            -item["active_processes"],
            item["company_name"].lower(),
        ),
    )


def _build_monthly_evolution(
    applications: List[Interview],
    months: int,
) -> List[Dict[str, Any]]:
    period = _build_month_period(months)

    evolution = {
        month_key: {
            "month": month_key,
            "label": label,
            "applications": 0,
            "interviews": 0,
            "offers": 0,
        }
        for month_key, label in period
    }

    for application in applications:
        created_month = _month_key(
            application.created_at
        )

        if created_month in evolution:
            evolution[created_month][
                "applications"
            ] += 1

        interview_month = _month_key(
            application.last_interview_date
        )

        if interview_month in evolution:
            evolution[interview_month][
                "interviews"
            ] += 1

        if (
            _normalize_status(application)
            in OFFER_STATUSES
        ):
            offer_month = _month_key(
                application.updated_at
                or application.created_at
            )

            if offer_month in evolution:
                evolution[offer_month][
                    "offers"
                ] += 1

    return list(evolution.values())


def _month_key(
    value,
) -> str:
    if value is None:
        return ""

    return "{:04d}-{:02d}".format(
        value.year,
        value.month,
    )


def _build_month_period(
    months: int,
) -> List[Tuple[str, str]]:
    today = date.today()

    month_names = {
        1: "Jan",
        2: "Fev",
        3: "Mar",
        4: "Abr",
        5: "Mai",
        6: "Jun",
        7: "Jul",
        8: "Ago",
        9: "Set",
        10: "Out",
        11: "Nov",
        12: "Dez",
    }

    result = []

    current_month_index = (
        today.year * 12
        + today.month
        - 1
    )

    for offset in reversed(range(months)):
        target_index = (
            current_month_index - offset
        )

        year = target_index // 12
        month = target_index % 12 + 1

        month_key = "{:04d}-{:02d}".format(
            year,
            month,
        )

        label = "{}/{}".format(
            month_names[month],
            str(year)[-2:],
        )

        result.append(
            (
                month_key,
                label,
            )
        )

    return result