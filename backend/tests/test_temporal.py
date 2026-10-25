from datetime import date

from app.domain.serving_reader import ServingContext
from app.rag.temporal import resolve_date

CTX = ServingContext("s", "c", "p", 384, ("2026-02-12",))


def test_missing_date_reports_verified_scope():
    result = resolve_date("Hợp đồng là gì?", None, None, CTX)
    assert result.as_of_date == date(2026, 2, 12)
    assert "2026-02-12" in result.scope_notice


def test_current_or_conflicting_date_needs_clarification():
    for question, supplied in [
        ("Luật hiện nay?", None),
        ("Tại 13/02/2026?", date(2026, 2, 12)),
        ("Áp dụng năm 2025?", None),
    ]:
        assert resolve_date(question, supplied, None, CTX).clarification


def test_old_history_date_does_not_override_current_turn():
    decision = resolve_date("Tại 12/02/2026?", date(2026, 2, 12), date(2025, 1, 1), CTX)
    assert decision.as_of_date == date(2026, 2, 12)
    assert not decision.clarification


def test_dashed_date_and_relative_year_do_not_default_to_verified_day():
    for question in [
        "Ngày 01-01-2025 luật quy định thế nào?",
        "Năm nay thì sao?",
        "Tại ngày 01/03 thì sao?",
    ]:
        assert resolve_date(question, None, None, CTX).clarification
