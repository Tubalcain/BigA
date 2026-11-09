"""
A 股交易时段（Asia/Shanghai）。

没有交易日历时按工作日近似；节假日在有日历数据时再收紧。
日频盘中用上一交易日，收盘后才把当天当作已完成日频。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ_NAME = "Asia/Shanghai"
SHANGHAI = ZoneInfo(TZ_NAME)

# 含集合竞价与收盘后一小段缓冲，避免 15:00 整点误判。
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 5)


def shanghai_now(now=None):
    if now is None:
        return datetime.now(SHANGHAI)
    if getattr(now, "tzinfo", None) is None:
        return now.replace(tzinfo=SHANGHAI)
    return now.astimezone(SHANGHAI)


def shanghai_today(now=None):
    return shanghai_now(now).date()


def is_weekday(day=None, now=None):
    if day is None:
        day = shanghai_today(now)
    return day.weekday() < 5


def previous_weekday(day):
    cursor = day - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def session_phase(now=None):
    """open / pre / closed / weekend。"""
    dt = shanghai_now(now)
    if dt.weekday() >= 5:
        return "weekend"
    clock = dt.time()
    if clock < SESSION_OPEN:
        return "pre"
    if clock <= SESSION_CLOSE:
        return "open"
    return "closed"


def in_session(now=None):
    return session_phase(now) == "open"


def session_bucket(now=None):
    """缓存分段：日历日 + 时段，禁止把盘中结果当成全日永久缓存。"""
    dt = shanghai_now(now)
    return f"{dt.date().isoformat()}:{session_phase(dt)}"


def expected_daily_data_date(now=None, is_open=None):
    """
    日频数据应展示的交易日。

    - 周末：上一个工作日
    - 交易日盘前/盘中：上一交易日（当日 K 线/资金尚未完成）
    - 交易日收盘后：当日
    is_open 可传入交易日历判断；缺省按工作日。
    """
    dt = shanghai_now(now)
    day = dt.date()
    phase = session_phase(dt)

    def _open(candidate):
        if is_open is None:
            return candidate.weekday() < 5
        try:
            return bool(is_open(candidate))
        except Exception:
            return candidate.weekday() < 5

    if phase in ("pre", "open") or not _open(day):
        cursor = previous_weekday(day)
        guard = 0
        while not _open(cursor) and guard < 15:
            cursor = previous_weekday(cursor)
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
