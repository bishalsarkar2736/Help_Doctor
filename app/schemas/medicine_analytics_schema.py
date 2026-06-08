from pydantic import BaseModel


class TopMedicineResponse(BaseModel):
    medicine_name: str
    search_count: int


class FailedMedicineQueryResponse(BaseModel):
    question: str
    created_at: str


class DailyMedicineQueryResponse(BaseModel):
    date: str
    count: int


class MedicineAnalyticsResponse(BaseModel):
    total_queries: int
    queries_today: int

    top_medicines: list[
        TopMedicineResponse
    ]

    failed_queries: list[
        FailedMedicineQueryResponse
    ]

    daily_query_counts: list[
        DailyMedicineQueryResponse
    ]