"""
A 股交易时段（Asia/Shanghai）。

内置上交所休市日回退表（含调休补班），calendar.py 自身不发起网络请求。
适配器若已有缓存日历，可 install_trade_calendar 覆盖；缺省走 bundled fallback。
日频盘中用上一交易日，收盘后才把当天当作已完成日频。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ_NAME = "Asia/Shanghai"
SHANGHAI = ZoneInfo(TZ_NAME)

# 含集合竞价与收盘后一小段缓冲，避免 15:00 整点误判。
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 5)

# 进程内覆盖：open_dates 为 YYYY-MM-DD 集合。None 表示使用 bundled fallback。
_TRADE_CALENDAR_OPEN = None
_TRADE_CALENDAR_SOURCE = "bundled_fallback"

# 国务院放假安排 + 交易所休市的保守回退。不是交易所官方 API。
# 调休上班日单独列入 SSE_MAKEUP_OPEN，避免把补班当成周末休市。
SSE_CLOSED_DATES = frozenset(
    {
        # 2024
        "2024-01-01",
        "2024-02-09",
        "2024-02-10",
        "2024-02-11",
        "2024-02-12",
        "2024-02-13",
        "2024-02-14",
        "2024-02-15",
        "2024-02-16",
        "2024-02-17",
        "2024-04-04",
        "2024-04-05",
        "2024-04-06",
        "2024-05-01",
        "2024-05-02",
        "2024-05-03",
        "2024-05-04",
        "2024-05-05",
        "2024-06-08",
        "2024-06-09",
        "2024-06-10",
        "2024-09-15",
        "2024-09-16",
        "2024-09-17",
        "2024-10-01",
        "2024-10-02",
        "2024-10-03",
        "2024-10-04",
        "2024-10-05",
        "2024-10-06",
        "2024-10-07",
        # 2025
        "2025-01-01",
        "2025-01-28",
        "2025-01-29",
        "2025-01-30",
        "2025-01-31",
        "2025-02-01",
        "2025-02-02",
        "2025-02-03",
        "2025-02-04",
        "2025-04-04",
        "2025-04-05",
        "2025-04-06",
        "2025-05-01",
        "2025-05-02",
        "2025-05-03",
        "2025-05-04",
        "2025-05-05",
        "2025-05-31",
        "2025-06-01",
        "2025-06-02",
        "2025-10-01",
        "2025-10-02",
        "2025-10-03",
        "2025-10-04",
        "2025-10-05",
        "2025-10-06",
        "2025-10-07",
        "2025-10-08",
        # 2026（国庆按已公布窗口；其余法定假日按常见安排保守列入）
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
        "2026-02-15",
        "2026-02-16",
        "2026-02-17",
        "2026-02-18",
        "2026-02-19",
        "2026-02-20",
        "2026-02-21",
        "2026-02-22",
        "2026-02-23",
        "2026-04-04",
        "2026-04-05",
        "2026-04-06",
        "2026-05-01",
        "2026-05-02",
        "2026-05-03",
        "2026-05-04",
        "2026-05-05",
        "2026-06-19",
        "2026-06-20",
        "2026-06-21",
        "2026-09-25",
        "2026-09-26",
        "2026-09-27",
        "2026-09-30",
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
        "2026-10-04",
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
    }
)

SSE_MAKEUP_OPEN = frozenset(
    {
        "2024-02-04",
        "2024-02-18",
        "2024-04-07",
        "2024-04-28",
        "2024-05-11",
        "2024-09-14",
        "2024-09-29",
        "2024-10-12",
        "2025-01-26",
        "2025-02-08",
        "2025-04-27",
        "2025-09-28",
        "2025-10-11",
        "2026-02-14",
        "2026-02-28",
        "2026-09-20",
        "2026-10-10",
    }
)


def shanghai_now(now=None):
    if now is None:
        return datetime.now(SHANGHAI)
    if getattr(now, "tzinfo", None) is None:
        return now.replace(tzinfo=SHANGHAI)
    return now.astimezone(SHANGHAI)


def shanghai_today(now=None):
    return shanghai_now(now).date()


def _as_date(day):
    if day is None:
        return None
    if isinstance(day, datetime):
        return shanghai_now(day).date()
    if isinstance(day, date):
        return day
    text = str(day).strip()[:10]
    return date.fromisoformat(text)


def calendar_source():
    return _TRADE_CALENDAR_SOURCE


def install_trade_calendar(open_dates=None, *, source="cached"):
    """
    安装已缓存的交易日集合。open_dates 为 YYYY-MM-DD 可迭代；None 恢复 bundled fallback。
    不在此处拉网。
    """
    global _TRADE_CALENDAR_OPEN, _TRADE_CALENDAR_SOURCE
    if open_dates is None:
        _TRADE_CALENDAR_OPEN = None
        _TRADE_CALENDAR_SOURCE = "bundled_fallback"
        return
    _TRADE_CALENDAR_OPEN = frozenset(str(item)[:10] for item in open_dates)
    _TRADE_CALENDAR_SOURCE = source or "cached"


def reset_trade_calendar():
    install_trade_calendar(None)


def is_trading_day(day=None, now=None):
    """
    是否为 A 股交易日。优先进程内覆盖日历，否则 bundled 休市表 + 周末/补班。
    未知工作日按开市（weekday fallback），已知假日一律休市。
    """
    if day is None:
        day = shanghai_today(now)
    day = _as_date(day)
    iso = day.isoformat()
    if _TRADE_CALENDAR_OPEN is not None:
        return iso in _TRADE_CALENDAR_OPEN
    if iso in SSE_MAKEUP_OPEN:
        return True
    if iso in SSE_CLOSED_DATES:
        return False
    return day.weekday() < 5


def is_weekday(day=None, now=None):
    if day is None:
        day = shanghai_today(now)
    return _as_date(day).weekday() < 5


def previous_weekday(day):
    cursor = _as_date(day) - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def previous_trading_day(day, now=None):
    cursor = _as_date(day) - timedelta(days=1)
    guard = 0
    while not is_trading_day(cursor, now=now) and guard < 32:
        cursor -= timedelta(days=1)
        guard += 1
    return cursor


def session_phase(now=None):
    """open / pre / closed / weekend / holiday。"""
    dt = shanghai_now(now)
    day = dt.date()
    if not is_trading_day(day, now=dt):
        return "weekend" if day.weekday() >= 5 else "holiday"
    clock = dt.time()
    if clock < SESSION_OPEN:
        return "pre"
    if clock <= SESSION_CLOSE:
        return "open"
    return "closed"


def in_session(now=None):
    return session_phase(now) == "open"


def session_bucket(now=None):
    """日历日 + 时段，供 TTL/新鲜度使用；逻辑缓存键不再嵌入此时段。"""
    dt = shanghai_now(now)
    return f"{dt.date().isoformat()}:{session_phase(dt)}"


def expected_daily_data_date(now=None, is_open=None):
    """
    日频数据应展示的交易日。

    - 周末/假日：上一交易日
    - 交易日盘前/盘中：上一交易日（当日 K 线/资金尚未完成）
    - 交易日收盘后：当日
    is_open 可传入交易日历判断；缺省用 is_trading_day（bundled fallback）。
    """
    dt = shanghai_now(now)
    day = dt.date()
    phase = session_phase(dt)

    def _open(candidate):
        if is_open is None:
            return is_trading_day(candidate, now=dt)
        try:
            return bool(is_open(candidate))
        except Exception:
            return is_trading_day(candidate, now=dt)

    if phase in ("pre", "open", "weekend", "holiday") or not _open(day):
        cursor = previous_trading_day(day, now=dt) if is_open is None else previous_weekday(day)
        guard = 0
        while not _open(cursor) and guard < 32:
            cursor = cursor - timedelta(days=1) if is_open is None else previous_weekday(cursor)
            guard += 1
        return cursor
    return day


def format_leg_date_caption(data_date, now=None):
    """UI 用：数据日期 vs 上海日历，避免用 as_of 冒充今日行情。"""
    if not data_date:
        return "数据日期未知"
    expected = expected_daily_data_date(now).isoformat()
    today = shanghai_today(now).isoformat()
    text = str(data_date)
    if text == expected and text != today:
        return f"数据日期 {text}（日频·上一交易日）"
    if text == today:
        return f"数据日期 {text}（上海日历当日）"
    return f"数据日期 {text}"
