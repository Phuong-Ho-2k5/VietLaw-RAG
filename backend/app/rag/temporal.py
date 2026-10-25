import re
from datetime import date

from app.chat.schemas import TemporalDecision


def resolve_date(question, supplied, previous, context) -> TemporalDecision:
    verified = [date.fromisoformat(d) for d in context.verified_dates]
    notice = "Phạm vi pháp luật đã xác minh: " + ", ".join(context.verified_dates) + "."
    clarification = "Bạn muốn hỏi tại ngày nào trong phạm vi đã xác minh? " + notice
    text = question.casefold()
    explicit = set()
    try:
        for year, month, day in re.findall(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text):
            explicit.add(date(int(year), int(month), int(day)))
        for day, month, year in re.findall(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", text):
            explicit.add(date(int(year), int(month), int(day)))
    except ValueError:
        return TemporalDecision(as_of_date=None, clarification=clarification, scope_notice=notice)
    if (
        any(
            x in text
            for x in [
                "hiện nay",
                "hiện tại",
                "hôm nay",
                "bây giờ",
                "mới nhất",
                "năm nay",
                "tháng này",
                "tuần này",
            ]
        )
        or len(explicit) > 1
        or (supplied and explicit and supplied not in explicit)
    ):
        return TemporalDecision(as_of_date=None, clarification=clarification, scope_notice=notice)
    # A bare year/month cannot safely be collapsed to one verified day.
    if not explicit and re.search(
        r"\b(?:năm\s+\d{4}|tháng\s+\d{1,2}|ngày\s+\d{1,2}[/.-]\d{1,2})\b", text
    ):
        return TemporalDecision(as_of_date=None, clarification=clarification, scope_notice=notice)
    resolved = supplied or next(iter(explicit), None) or previous
    if resolved is None and len(verified) == 1:
        resolved = verified[0]
    if resolved not in verified:
        return TemporalDecision(as_of_date=None, clarification=clarification, scope_notice=notice)
    return TemporalDecision(as_of_date=resolved, scope_notice=notice)
