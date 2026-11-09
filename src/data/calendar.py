"""
A 股交易时段（Asia/Shanghai）。

bundled 休市表来自上交所公告，不是国务院行政调休，也不是交易所实时 API。
calendar.py 自身不发起网络请求。适配器若已有缓存日历，可 install_trade_calendar 覆盖。
未知年份只做周末休市 + 工作日近似，并标明 weekday_fallback，不假装官方。
日频盘中用上一交易日；收盘后期望当日，但有上限的发布宽限可暂用上一完整交易日。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ_NAME = "Asia/Shanghai"
SHANGHAI = ZoneInfo(TZ_NAME)

# 含集合竞价与收盘后一小段缓冲，避免 15:00 整点误判。
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 5)
# 收盘后资金/日频落地常见滞后；宽限有上限，过期仍按当日期望，不放宽陈旧缓存门控。
PUBLISH_GRACE_MINUTES = 90

# 进程内覆盖：open_dates 为 YYYY-MM-DD 集合。None 表示使用 bundled fallback。
_TRADE_CALENDAR_OPEN = None
_TRADE_CALENDAR_SOURCE = "bundled_sse_notice"
_NOW_OVERRIDE = None

# 仅收录上交所公告中的休市日。行政调休上班日若公告写「周末休市」则不开市。
# 2024: 上证公告〔2023〕47号
# https://www.sse.com.cn/disclosure/announcement/general/c/c_20231226_5733939.shtml
# 2025: 上证公告〔2024〕38号
# https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml
# 2026: 上证公告〔2025〕45号；中秋/国庆复核 上证公告〔2026〕22号
# https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml
# https://www.sse.com.cn/disclosure/announcement/general/c/c_20260915_10832273.shtml
BUNDLED_YEARS = frozenset({2024, 2025, 2026})
SSE_CLOSED_DATES = frozenset(
    {
        # 2024 上证公告〔2023〕47号
        "2023-12-30",
        "2023-12-31",
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
        # 2025 上证公告〔2024〕38号
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
        # 2026 上证公告〔2025〕45号 / 〔2026〕22号
        # 9/25-27 休市 9/28 开市；10/1-7 休市 10/8 开市；9/30 正常交易。
        # 1/4、2/14、2/28、5/9、9/20、10/10 公告为周末休市，不得当成补班开市。
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
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
        "2026-10-04",
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
    }
)


def set_now_override(now=None):
    """测试用固定时钟。生产勿调用。None 表示恢复系统时间。"""
    global _NOW_OVERRIDE
    _NOW_OVERRIDE = now


def shanghai_now(now=None):
    if now is None:
        now = _NOW_OVERRIDE
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


def calendar_source(day=None, now=None):
    if _TRADE_CALENDAR_OPEN is not None:
        return _TRADE_CALENDAR_SOURCE
    if day is None:
        day = shanghai_today(now)
    day = _as_date(day)
    if day.year in BUNDLED_YEARS:
        return "bundled_sse_notice"
    return "weekday_fallback"


def install_trade_calendar(open_dates=None, *, source="cached"):
    """
    安装已缓存的交易日集合。open_dates 为 YYYY-MM-DD 可迭代；None 恢复 bundled fallback。
    不在此处拉网。
    """
    global _TRADE_CALENDAR_OPEN, _TRADE_CALENDAR_SOURCE
    if open_dates is None:
        _TRADE_CALENDAR_OPEN = None
        _TRADE_CALENDAR_SOURCE = "bundled_sse_notice"
        return
    _TRADE_CALENDAR_OPEN = frozenset(str(item)[:10] for item in open_dates)
    _TRADE_CALENDAR_SOURCE = source or "cached"


def reset_trade_calendar():
    install_trade_calendar(None)


def is_trading_day(day=None, now=None):
    """
    是否为 A 股交易日。优先进程内覆盖日历。
    bundled 年份用上交所休市表；周末一律休市（不把行政调休当成交易日）。
    未知年份：周末休市、工作日近似开市，calendar_source=weekday_fallback。
    """
    if day is None:
        day = shanghai_today(now)
    day = _as_date(day)
    iso = day.isoformat()
    if _TRADE_CALENDAR_OPEN is not None:
        return iso in _TRADE_CALENDAR_OPEN
    if day.weekday() >= 5:
        return False
    if iso in SSE_CLOSED_DATES:
        return False
    return True


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


def close_dt(now=None):
    dt = shanghai_now(now)
    return datetime.combine(dt.date(), SESSION_CLOSE, tzinfo=SHANGHAI)


def in_close_publish_grace(now=None):
    """
    交易日收盘后、SESSION_CLOSE+90 分钟内视为发布宽限。
    仅此时允许用上一完整交易日作为日频证据；不改变 stale_cache 门控。
    """
    dt = shanghai_now(now)
    if session_phase(dt) != "closed":
        return False
    return dt <= close_dt(dt) + timedelta(minutes=PUBLISH_GRACE_MINUTES)


def session_bucket(now=None):
    """日历日 + 时段，供 TTL/新鲜度使用；逻辑缓存键不再嵌入此时段。"""
    dt = shanghai_now(now)
    return f"{dt.date().isoformat()}:{session_phase(dt)}"


def expected_daily_data_date(now=None, is_open=None):
    """
    日频数据应展示的交易日。

    - 周末/假日：上一交易日
    - 交易日盘前/盘中：上一交易日（当日 K 线/资金尚未完成）
    - 交易日收盘后：当日（发布宽限另见 in_close_publish_grace / evidence_fresh）
    is_open 可传入交易日历判断；缺省用 is_trading_day。
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
    if in_close_publish_grace(now) and text == previous_trading_day(shanghai_today(now), now=now).isoformat():
        return f"数据日期 {text}（收盘发布延迟·上一完整交易日）"
    return f"数据日期 {text}"
