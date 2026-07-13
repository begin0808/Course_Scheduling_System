"""M6-1:測試日期基準 helper 自身的單元測試。

這支 helper 是「所有調代課測試不會過期」的地基,它自己得先站得住。
"""

from datetime import date, timedelta

import pytest

from app.core.clock import is_past_slot
from tests import dates as d


@pytest.mark.parametrize("today", [
    date(2026, 7, 13),   # 週一(今天就是基準星期的邊界)
    date(2026, 7, 15),   # 週三(卡片點名的邊界:今天就是週三)
    date(2026, 7, 19),   # 週日
    date(2026, 12, 28),  # 跨年:基準週會落到隔年
    date(2028, 2, 26),   # 閏年 2/29 前後
])
def test_base_monday_is_a_future_monday(today):
    mon = d.base_monday(today)
    assert mon.isoweekday() == 1
    assert (mon - today).days >= d.LEAD_DAYS, "基準週必須距今至少 LEAD_DAYS,否則當天節次可能已上過"
    # 「本月代課少者優先」與月結統計都以節次日期的月份為範圍,基準週與下週三必須同月
    assert (mon + timedelta(days=9)).month == mon.month


@pytest.mark.parametrize("offset", range(40))
def test_base_week_never_straddles_a_month_regardless_of_today(offset):
    """不論今天是哪一天,WED 與 WED2 都必須同月(2026-07-14 曾在此翻車:7/29 vs 8/5)。"""
    mon = d.base_monday(date(2026, 7, 1) + timedelta(days=offset))
    assert (mon + timedelta(days=2)).month == (mon + timedelta(days=9)).month


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5, 6, 7])
def test_on_or_after_lands_on_the_asked_weekday(weekday):
    for offset in range(14):  # 涵蓋「當天就是該星期」與其餘每一種相對位置
        day = date(2026, 7, 13) + timedelta(days=offset)
        got = d.on_or_after(weekday, day)
        assert got.isoweekday() == weekday
        assert got >= day
        assert (got - day).days < 7


def test_on_or_after_returns_the_same_day_when_it_already_matches():
    wed = date(2026, 7, 15)  # 週三
    assert d.on_or_after(3, wed) == wed


def test_on_or_after_rejects_a_bad_weekday():
    with pytest.raises(ValueError):
        d.on_or_after(0, date(2026, 7, 13))


@pytest.mark.parametrize("today", [date(2026, 1, 5), date(2026, 7, 13), date(2027, 3, 1)])
def test_cross_month_wednesday_straddles_a_month_boundary(today):
    wed = d.cross_month_wednesday(today)
    nxt = wed + timedelta(days=7)
    assert wed.isoweekday() == 3 and nxt.isoweekday() == 3
    assert nxt.month != wed.month, "兩個週三必須落在不同月份,跨月拆帳才驗得到"
    assert wed >= d.base_monday(today)


def test_module_constants_are_a_consistent_future_week():
    assert [x.isoweekday() for x in (d.MON, d.WED, d.FRI, d.SAT)] == [1, 3, 5, 6]
    assert d.WED2 == d.WED + timedelta(days=7)
    assert d.NEXT_MON == d.MON + timedelta(days=7)
    # 每一個要拿來排課/請假的日子都還在未來(這正是硬編日期會失守的地方)
    for day in (d.MON, d.WED, d.FRI, d.WED2, d.CROSS_WED, d.CROSS_WED2):
        assert not is_past_slot(day, None) and day > date.today()


def test_semester_window_contains_every_test_day():
    for day in (d.MON, d.WED, d.FRI, d.SAT, d.WED2, d.CROSS_WED, d.CROSS_WED2):
        assert d.SEM_START < day < d.SEM_END
    assert d.BEFORE_SEM < d.SEM_START and d.AFTER_SEM > d.SEM_END
