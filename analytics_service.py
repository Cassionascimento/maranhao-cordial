import os

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)

def _property_id():
    property_id = os.getenv("GA4_PROPERTY_ID")

    if not property_id:
        raise RuntimeError(
            "GA4_PROPERTY_ID não configurado."
        )

    return property_id


def _client():
    return BetaAnalyticsDataClient()


def resumo_geral(dias=7):
    request = RunReportRequest(
        property=f"properties/{_property_id()}",
        date_ranges=[
            DateRange(start_date=f"{dias}daysAgo", end_date="today")
        ],
        metrics=[
            Metric(name="activeUsers"),
            Metric(name="newUsers"),
            Metric(name="sessions"),
            Metric(name="screenPageViews"),
            Metric(name="engagementRate"),
        ],
    )

    response = _client().run_report(request)

    if not response.rows:
        return {}

    row = response.rows[0]

    return {
        "usuarios_ativos": row.metric_values[0].value,
        "novos_usuarios": row.metric_values[1].value,
        "sessoes": row.metric_values[2].value,
        "visualizacoes": row.metric_values[3].value,
        "taxa_engajamento": row.metric_values[4].value,
    }


def origens_trafego(dias=30):
    request = RunReportRequest(
        property=f"properties/{_property_id()}",
        date_ranges=[
            DateRange(start_date=f"{dias}daysAgo", end_date="today")
        ],
        dimensions=[
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
        ],
        limit=20,
    )

    response = _client().run_report(request)

    return [
        {
            "origem": row.dimension_values[0].value,
            "meio": row.dimension_values[1].value,
            "sessoes": row.metric_values[0].value,
            "usuarios": row.metric_values[1].value,
        }
        for row in response.rows
    ]


def paginas_mais_acessadas(dias=30):
    request = RunReportRequest(
        property=f"properties/{_property_id()}",
        date_ranges=[
            DateRange(start_date=f"{dias}daysAgo", end_date="today")
        ],
        dimensions=[
            Dimension(name="pagePath"),
            Dimension(name="pageTitle"),
        ],
        metrics=[
            Metric(name="screenPageViews"),
            Metric(name="activeUsers"),
        ],
        limit=20,
    )

    response = _client().run_report(request)

    return [
        {
            "pagina": row.dimension_values[0].value,
            "titulo": row.dimension_values[1].value,
            "visualizacoes": row.metric_values[0].value,
            "usuarios": row.metric_values[1].value,
        }
        for row in response.rows
    ]
