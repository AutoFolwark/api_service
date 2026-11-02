from datetime import datetime, timedelta, timezone

from aws_lambda_functions.lots_seo_lambda_handler import (
    DELETED_LOT_LOOKBACK_DAYS,
    UPDATED_LOT_LOOKBACK_DAYS,
    _get_date_range,
)


def test_updated_lot_date_from_stays_within_three_days():
    now = datetime(2026, 11, 2, 19, 2, tzinfo=timezone.utc)

    date_from, date_to = _get_date_range(UPDATED_LOT_LOOKBACK_DAYS, now)

    assert (date_from, date_to) == ("2026-10-31", "2026-11-02")
    parsed_from = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    assert now - parsed_from < timedelta(days=3)


def test_deleted_lot_range_keeps_three_day_lookback():
    now = datetime(2026, 11, 2, 19, 2, tzinfo=timezone.utc)

    date_from, date_to = _get_date_range(DELETED_LOT_LOOKBACK_DAYS, now)

    assert (date_from, date_to) == ("2026-10-30", "2026-11-02")
