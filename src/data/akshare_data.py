"""
AKShare 数据适配器。

覆盖页面真正用到的能力：历史 OHLCV、实时报价、股票列表、
市场概况、指数、行业板块、行业/个股/市场/北向资金流向、交易日历、停牌股。
"""

from __future__ import annotations

import logging

import pandas as pd

from src.analysis.technical import TechnicalAnalyzer

from .cache import get_cache, make_cache_key
from .config import get_data_config
from .fetch import DataFetchError, safe_fetch
from .quality import (
    attach_date_swap,
    compact_date,
    empty_cross_border,
    empty_flow,
    empty_index,
    empty_list,
    empty_market_flow,
    empty_ohlcv,
    empty_overview,
    empty_quotes,
    empty_stock_flow,
    attach_rank_scope,
    infer_limit_pct,
    match_exchange,
    normalize_adjust,
    normalize_flow_indicator,
    normalize_period,
    normalize_quotes,
    normalize_sector_type,
    normalize_stock_code,
    normalize_stock_list,
    ordered_date_range,
    prepare_cross_border,
    prepare_flow_rank,
    prepare_market_flow,
    prepare_ohlcv,
    prepare_stock_flow,
    rename_columns,
    scale_money_to_wan,
    stamp_frame,
    to_numeric,
    validate_ohlcv,
)

logger = logging.getLogger("biga.data.akshare")


def _import_akshare():
    try:
        import akshare as ak
        return ak
    except ImportError as exc:
        raise DataFetchError("未安装 akshare，请执行 pip install akshare") from exc


class AKShareData:
    """AKShare 数据源。方法失败时返回空表，必要时回退到 TuShare。"""

    name = "akshare"

    def __init__(self, config=None):
        self.config = config or get_data_config()
        self.source_cfg = self.config.akshare
        self.cache = get_cache(self.config)
        self.cache_ttl = self.config.cache.ttl
        self.ttl_realtime = self.config.cache.ttl_realtime
        self.ttl_list = self.config.cache.ttl_list
        self.ttl_calendar = self.config.cache.ttl_calendar
        self._ak = None

    def is_available(self):
        if not self.source_cfg.enabled:
            return False
        try:
            self._client()
            return True
        except Exception:
            return False

    def _client(self):
        if self._ak is None:
            self._ak = _import_akshare()
        return self._ak

    def _retries(self):
        return max(int(self.source_cfg.retries or 1), 1)

    def _timeout(self):
        return int(self.source_cfg.timeout or 30)

    def _unavailable(self, factory):
        return factory("akshare", error="akshare unavailable", issues=["akshare unavailable"])

    def _peer(self):
        if not self.config.fallback:
            return None
        try:
            from .tushare_data import TuShareData

            other = TuShareData(self.config)
            return other if other.is_available() else None
        except Exception as exc:
            logger.warning("TuShare 回退不可用: %s", exc)
            return None

    def _try_peer(self, method, *args, **kwargs):
        other = self._peer()
        if other is None:
            return None
        func = getattr(other, method, None)
        if not callable(func):
            return None
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logger.warning("回退 %s 失败: %s", method, exc)
            return None

    def _fetch(self, func, default=None, label="", retries=None, timeout=None):
        return safe_fetch(
            func,
            retries=retries if retries is not None else self._retries(),
            timeout=self._timeout() if timeout is None else timeout,
            default=default,
            label=label,
        )

    def _cached(self, key_parts, ttl, loader, default):
        key = make_cache_key("AKShareData", *key_parts)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        value = loader()
        if value is None:
            value = default
        # 空表也缓存一小段时间，避免雪崩打爆上游
        cache_ttl = ttl if (isinstance(value, pd.DataFrame) and not value.empty) else min(ttl, 30)
        self.cache.set(key, value, ttl=cache_ttl)
        return value

    def _fallback_history(self, code, start_date, end_date, period, adjust):
        df = self._try_peer(
            "get_history_data",
            code,
            start_date,
            end_date,
            period=period,
            adjust=adjust,
            allow_fallback=False,
        )
        if df is not None and not df.empty:
            logger.info("AKShare 历史行情失败，已回退到 TuShare: %s", code)
            return df
        return None

    def get_history_data(
        self,
        stock_code,
        start_date,
        end_date,
        period="daily",
        adjust=None,
        allow_fallback=True,
    ):
        """
        历史 K 线。

        Args:
            stock_code: 6 位代码
            start_date / end_date: YYYYMMDD 或 YYYY-MM-DD
            period: daily / weekly / monthly（也接受 日线/周线/月线）
            adjust: "" 不复权, qfq/hfq 或 前复权/后复权
        """
        code = normalize_stock_code(stock_code)
        period_key = normalize_period(period)
        adj = normalize_adjust(adjust if adjust is not None else self.source_cfg.adjust)
        start, end, swapped = ordered_date_range(start_date, end_date)
        if not code:
            return empty_ohlcv(
                "akshare",
                error=f"invalid stock code: {stock_code!r}",
                issues=["invalid stock code"],
            )
        if not self.is_available():
            if allow_fallback:
                fallback = self._fallback_history(code, start, end, period_key, adj)
                if fallback is not None and validate_ohlcv(fallback)[0]:
                    return attach_date_swap(fallback, swapped)
            return empty_ohlcv(
                "akshare",
                error="akshare unavailable",
                issues=["akshare unavailable"],
            )

        key = ("history", code, start, end, period_key, adj)
        cache_key = make_cache_key("AKShareData", *key)
        cached = self.cache.get(cache_key)
        if cached is not None and validate_ohlcv(cached)[0]:
            return cached

        try:
            df = self._fetch_history(
                code, start, end, period_key, adj,
                filter_start=start_date, filter_end=end_date,
            )
        except Exception as exc:
            logger.warning("AKShare 历史拉取异常 %s: %s", code, exc)
            df = empty_ohlcv("akshare", error=str(exc), issues=["fetch failed"])
        ok, issues = validate_ohlcv(df)
        if ok:
            self.cache.set(cache_key, df, ttl=self.cache_ttl)
            return attach_date_swap(df, swapped)
        if allow_fallback:
            fallback = self._fallback_history(code, start, end, period_key, adj)
            if fallback is not None and validate_ohlcv(fallback)[0]:
                return attach_date_swap(fallback, swapped)
        logger.warning("AKShare 历史数据不可用 %s: %s", code, issues)
        out = df if df is not None else empty_ohlcv("akshare", issues=issues)
        return attach_date_swap(out, swapped)

    def _fetch_history(self, code, start, end, period, adjust, filter_start=None, filter_end=None):
        if not code:
            return empty_ohlcv("akshare", issues=["invalid stock code"])
        ak = self._client()
        ak_period = period if period in ("daily", "weekly", "monthly") else "daily"

        specs = []
        def _add(**kwargs):
            if kwargs not in specs:
                specs.append(dict(kwargs))

        _add(symbol=code, period=ak_period, start_date=start, end_date=end, adjust=adjust)
        if adjust:
            _add(symbol=code, period=ak_period, start_date=start, end_date=end, adjust="")
        _add(symbol=code, period=ak_period, start_date=start, end_date=end)
        _add(symbol=code, period=ak_period, adjust=adjust or "")

        raw = None
        for kwargs in specs:
            raw = self._fetch(
                lambda kwargs=kwargs: ak.stock_zh_a_hist(**kwargs),
                default=None,
                label=f"stock_zh_a_hist:{code}",
                retries=1,
            )
            if isinstance(raw, pd.DataFrame) and not raw.empty:
                break
        if raw is None or (isinstance(raw, pd.DataFrame) and raw.empty):
            logger.warning("AKShare 未返回历史数据 %s", code)
            return empty_ohlcv("akshare", error="upstream empty", issues=["empty frame"])

        df = prepare_ohlcv(
            raw,
            source="akshare",
            code=code,
            adjust=adjust,
            start=filter_start if filter_start is not None else start,
            end=filter_end if filter_end is not None else end,
            max_abs_return=self.config.quality_max_abs_return,
            drop_outliers=self.config.drop_outlier_bars,
        )
        df.attrs["period"] = period
        df.attrs["code"] = code
        return df

    def get_spot_snapshot(self, force=False):
        """全市场实时快照（东财）。供列表、报价、涨跌统计复用。"""

        def loader():
            ak = self._client()
            raw = None
            # 东财全市场快照分页多、易限流：只试一次，失败立刻回退新浪
            for api_name, retries, timeout in (
                ("stock_zh_a_spot_em", 1, 90),
                ("stock_zh_a_spot", 1, 90),
            ):
                api = getattr(ak, api_name, None)
                if api is None:
                    continue
                raw = self._fetch(api, default=None, label=api_name, retries=retries, timeout=timeout)
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    break
            if raw is None or raw.empty:
                return empty_quotes("akshare", issues=["spot snapshot unavailable"])
            return normalize_quotes(raw, source="akshare", market_cap_unit="yuan")

        if not self.is_available():
            return self._unavailable(empty_quotes)
        if force:
            return loader()
        return self._cached(("spot_snapshot",), self.ttl_realtime, loader, empty_quotes("akshare"))

    def get_stock_list(self, exchange="所有", allow_fallback=True):
        """
        股票列表。优先返回带行情字段的快照，便于筛选器按市值/涨跌幅/成交量过滤。
        """
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer("get_stock_list", exchange, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return self._unavailable(empty_list)

        def loader():
            spot = self.get_spot_snapshot()
            if spot is not None and not spot.empty:
                return spot
            ak = self._client()
            raw = self._fetch(
                lambda: ak.stock_info_a_code_name(),
                default=None,
                label="stock_info_a_code_name",
            )
            if raw is None or raw.empty:
                return empty_list("akshare")
            return normalize_stock_list(raw, source="akshare")

        df = self._cached(("stock_list",), self.ttl_list, loader, empty_list("akshare"))
        if df is None or df.empty:
            if allow_fallback:
                alt = self._try_peer("get_stock_list", exchange, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return empty_list(
                "akshare",
                error="stock list unavailable",
                issues=["stock list unavailable"],
            )
        if "code" in df.columns:
            mask = df["code"].map(lambda c: match_exchange(c, exchange))
            df = df[mask].reset_index(drop=True)
        return stamp_frame(df, df.attrs.get("source") or "akshare")

    def get_realtime_quote(self, stock_code):
        """单只股票实时行情，至少包含 price 列（投资组合页依赖）。"""
        code = normalize_stock_code(stock_code)
        if not code:
            return empty_quotes(
                "akshare",
                error=f"invalid stock code: {stock_code!r}",
                issues=["invalid stock code"],
            )

        spot = self.get_spot_snapshot()
        if spot is not None and not spot.empty and "code" in spot.columns:
            row = spot[spot["code"] == code]
            if not row.empty:
                return stamp_frame(row.reset_index(drop=True), "akshare")

        def loader():
            if not self.is_available():
                return self._unavailable(empty_quotes)
            ak = self._client()
            for api_name, kwargs in (
                ("stock_bid_ask_em", {"symbol": code}),
                ("stock_individual_info_em", {"symbol": code}),
            ):
                api = getattr(ak, api_name, None)
                if api is None:
                    continue
                raw = self._fetch(lambda api=api, kwargs=kwargs: api(**kwargs), default=None, label=api_name)
                quote = _quote_from_item_value(raw, code)
                if quote is not None:
                    return quote
            return empty_quotes("akshare")

        quote = self._cached(("quote", code), self.ttl_realtime, loader, empty_quotes("akshare"))
        if quote is None or quote.empty:
            end = compact_date(pd.Timestamp.now())
            start = compact_date(pd.Timestamp.now() - pd.Timedelta(days=14))
            hist = self.get_history_data(code, start, end, allow_fallback=True)
            if hist is not None and not hist.empty:
                last = hist.iloc[[-1]]
                fallback = pd.DataFrame(
                    {
                        "code": [code],
                        "price": [last["close"].iloc[0]],
                        "open": [last["open"].iloc[0]],
                        "high": [last["high"].iloc[0]],
                        "low": [last["low"].iloc[0]],
                        "pre_close": [last["close"].iloc[0]],
                        "volume": [last["volume"].iloc[0]],
                        "status": ["unknown"],
                        "source": [last["source"].iloc[0] if "source" in last.columns else "akshare"],
                    }
                )
                return normalize_quotes(fallback, source=fallback["source"].iloc[0])
        if quote is None or quote.empty:
            issues = list((quote.attrs.get("issues") if quote is not None else None) or ["quote unavailable"])
            return empty_quotes(
                "akshare",
                error=(quote.attrs.get("error") if quote is not None else None) or "quote unavailable",
                issues=issues,
            )
        return quote

    def get_market_overview(self, light=False, allow_fallback=True):
        """涨跌分布，列：type, count。默认先乐咕再快照；light=True 不打全市场。"""
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer("get_market_overview", light=light, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return self._unavailable(empty_overview)

        def from_spot():
            spot = self.get_spot_snapshot()
            if spot is None or spot.empty or "change_pct" not in spot.columns:
                return None
            rows = []
            chg = to_numeric(spot["change_pct"])
            names = spot["name"] if "name" in spot.columns else pd.Series([""] * len(spot))
            codes = spot["code"] if "code" in spot.columns else pd.Series([""] * len(spot))
            limits = [
                infer_limit_pct(code, name) for code, name in zip(codes, names)
            ]
            limit_s = pd.Series(limits, index=spot.index)
            up_limit = chg >= (limit_s - 0.1)
            down_limit = chg <= -(limit_s - 0.1)
            rows.append(("涨停", int(up_limit.sum())))
            rows.append(("上涨", int(((chg > 0) & ~up_limit).sum())))
            rows.append(("平盘", int((chg == 0).sum())))
            rows.append(("下跌", int(((chg < 0) & ~down_limit).sum())))
            rows.append(("跌停", int(down_limit.sum())))
            return stamp_frame(
                pd.DataFrame(rows, columns=["type", "count"]).assign(source="akshare"),
                "akshare",
            )

        def from_legu():
            ak = self._client()
            api = getattr(ak, "stock_market_activity_legu", None)
            if api is None:
                return None
            raw = self._fetch(api, default=None, label="stock_market_activity_legu")
            if raw is None or raw.empty:
                return None
            work = rename_columns(raw)
            if {"type", "count"}.issubset(work.columns):
                work = work[["type", "count"]].copy()
            elif work.shape[1] >= 2:
                work = work.iloc[:, :2].copy()
                work.columns = ["type", "count"]
            else:
                return None
            work["count"] = to_numeric(work["count"])
            work["source"] = "akshare"
            return stamp_frame(work, "akshare")

        # 乐咕接口轻量，优先用于首页/概况；全市场快照仅作回退
        overview = from_legu()
        if (overview is None or overview.empty) and not light:
            overview = from_spot()
        if overview is None or overview.empty:
            if allow_fallback:
                alt = self._try_peer("get_market_overview", light=light, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return empty_overview("akshare", issues=["overview unavailable"])
        return overview

    def get_index_quotes(self, allow_fallback=True):
        """主要 A 股指数实时行情。"""
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer("get_index_quotes", allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return self._unavailable(empty_index)

        def loader():
            ak = self._client()
            raw = None
            for api_name in ("stock_zh_index_spot_em", "stock_zh_index_spot_sina", "stock_zh_index_spot"):
                api = getattr(ak, api_name, None)
                if api is None:
                    continue
                raw = self._fetch(api, default=None, label=api_name)
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    break
            if raw is None or raw.empty:
                return empty_index("akshare", issues=["index quotes unavailable"])
            work = rename_columns(raw)
            if "price" not in work.columns and "close" in work.columns:
                work["price"] = work["close"]
            if "code" in work.columns:
                work["code"] = work["code"].map(lambda x: str(x).zfill(6) if pd.notna(x) else "")
            work["source"] = "akshare"
            keep = [c for c in ["code", "name", "price", "change", "change_pct", "volume", "amount", "source"] if c in work.columns]
            work = work[keep]
            wanted = {
                "000001": "上证指数",
                "399001": "深证成指",
                "399006": "创业板指",
                "000688": "科创50",
                "399300": "沪深300",
                "000300": "沪深300",
            }
            if "code" in work.columns:
                subset = work[work["code"].isin(wanted.keys())]
                if subset.empty and "name" in work.columns:
                    subset = work[work["name"].isin(wanted.values())]
                if not subset.empty:
                    work = subset
            return stamp_frame(work.reset_index(drop=True), "akshare")

        result = self._cached(("index_quotes",), self.ttl_realtime, loader, empty_index("akshare"))
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer("get_index_quotes", allow_fallback=False)
            if alt is not None and not alt.empty:
                return alt
        if result is None or result.empty:
            return empty_index("akshare", issues=["index quotes unavailable"])
        return result

    def get_industry_boards(self):
        """行业板块行情（东财）。"""
        if not self.is_available():
            return stamp_frame(
                pd.DataFrame(), "akshare", error="akshare unavailable", issues=["akshare unavailable"]
            )

        def loader():
            ak = self._client()
            raw = None
            for api_name in (
                "stock_board_industry_name_em",
                "stock_board_industry_spot_em",
                "stock_sector_spot",
            ):
                api = getattr(ak, api_name, None)
                if api is None:
                    continue
                raw = self._fetch(api, default=None, label=api_name)
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    break
            if raw is None or raw.empty:
                return stamp_frame(pd.DataFrame(), "akshare")
            work = rename_columns(raw)
            if "name" not in work.columns and "板块名称" in raw.columns:
                work["name"] = raw["板块名称"]
            work["source"] = "akshare"
            return stamp_frame(work, "akshare")

        return self._cached(("industry_boards",), self.ttl_list, loader, stamp_frame(pd.DataFrame(), "akshare"))

    def get_fund_flow(self, indicator="今日", allow_fallback=True):
        """兼容旧接口：行业资金流向排名。"""
        return self.get_sector_fund_flow(indicator=indicator, allow_fallback=allow_fallback)

    def get_sector_fund_flow(self, indicator="今日", sector_type="行业资金流", allow_fallback=True):
        """行业 / 概念 / 地域资金流排名。金额单位：万元。"""
        period = normalize_flow_indicator(indicator)
        sector = normalize_sector_type(sector_type)
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer(
                    "get_sector_fund_flow", period, sector, allow_fallback=False
                )
                if alt is not None and not alt.empty:
                    return alt
            return self._unavailable(empty_flow)

        def loader():
            ak = self._client()
            api = getattr(ak, "stock_sector_fund_flow_rank", None)
            if api is None:
                return empty_flow("akshare", issues=["sector fund flow unavailable"])
            attempts = [(period, sector)]
            if period != "今日":
                attempts.append(("今日", sector))
            if sector != "行业资金流":
                attempts.append((period, "行业资金流"))
            if period != "今日" and sector != "行业资金流":
                attempts.append(("今日", "行业资金流"))
            raw = None
            actual_period, actual_sector = period, sector
            seen = set()
            for try_period, try_sector in attempts:
                key = (try_period, try_sector)
                if key in seen:
                    continue
                seen.add(key)
                raw = self._fetch(
                    lambda p=try_period, s=try_sector: api(indicator=p, sector_type=s),
                    default=None,
                    label=f"stock_sector_fund_flow_rank:{try_period}:{try_sector}",
                    retries=1,
                )
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    actual_period, actual_sector = try_period, try_sector
                    break
            if raw is None or raw.empty:
                return empty_flow("akshare", issues=["sector fund flow unavailable"])
            df = prepare_flow_rank(
                raw, source="akshare", period=actual_period, flow_type="sector", amount_unit="yuan"
            )
            return attach_rank_scope(
                df,
                requested_period=period,
                actual_period=actual_period,
                requested_sector=sector,
                actual_sector=actual_sector,
            )

        result = self._cached(
            ("sector_fund_flow", period, sector),
            self.ttl_realtime,
            loader,
            empty_flow("akshare"),
        )
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer("get_sector_fund_flow", period, sector, allow_fallback=False)
            if alt is not None and not alt.empty:
                return alt
        if result is None or result.empty:
            return empty_flow("akshare", issues=["sector fund flow unavailable"])
        return result

    def get_stock_fund_flow_rank(self, indicator="今日", allow_fallback=True):
        """个股主力资金排名。金额单位：万元。"""
        period = normalize_flow_indicator(indicator)
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer("get_stock_fund_flow_rank", period, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return self._unavailable(empty_flow)

        def loader():
            ak = self._client()
            raw = None
            actual_period = period
            api = getattr(ak, "stock_individual_fund_flow_rank", None)
            if api is not None:
                raw = self._fetch(
                    lambda: api(indicator=period),
                    default=None,
                    label=f"stock_individual_fund_flow_rank:{period}",
                    retries=1,
                )
                if (raw is None or raw.empty) and period != "今日":
                    raw = self._fetch(
                        lambda: api(indicator="今日"),
                        default=None,
                        label="stock_individual_fund_flow_rank:今日",
                        retries=1,
                    )
                    if isinstance(raw, pd.DataFrame) and not raw.empty:
                        actual_period = "今日"
            if raw is None or raw.empty:
                return empty_flow("akshare", issues=["stock fund flow rank unavailable"])
            df = prepare_flow_rank(
                raw, source="akshare", period=actual_period, flow_type="stock", amount_unit="yuan"
            )
            return attach_rank_scope(
                df, requested_period=period, actual_period=actual_period
            )

        result = self._cached(
            ("stock_fund_flow_rank", period),
            self.ttl_realtime,
            loader,
            empty_flow("akshare"),
        )
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer("get_stock_fund_flow_rank", period, allow_fallback=False)
            if alt is not None and not alt.empty:
                return alt
        if result is None or result.empty:
            return empty_flow("akshare", issues=["stock fund flow rank unavailable"])
        return result

    def get_stock_fund_flow(self, stock_code, start_date=None, end_date=None, allow_fallback=True):
        """单只股票主力/超大/大/中/小单净流入时间序列。金额单位：万元。"""
        code = normalize_stock_code(stock_code)
        start, end, swapped = ordered_date_range(start_date, end_date)
        if not code:
            return empty_stock_flow(
                "akshare",
                error=f"invalid stock code: {stock_code!r}",
                issues=["invalid stock code"],
            )
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer(
                    "get_stock_fund_flow",
                    code,
                    start or None,
                    end or None,
                    allow_fallback=False,
                )
                if alt is not None and not alt.empty:
                    return attach_date_swap(alt, swapped)
            return self._unavailable(empty_stock_flow)

        def loader():
            ak = self._client()
            api = getattr(ak, "stock_individual_fund_flow", None)
            if api is None:
                return empty_stock_flow("akshare", issues=["stock_individual_fund_flow unavailable"])
            market = _ak_flow_market(code)
            raw = None
            for mk in (market, "sz", "sh"):
                raw = self._fetch(
                    lambda mk=mk: api(stock=code, market=mk),
                    default=None,
                    label=f"stock_individual_fund_flow:{code}:{mk}",
                    retries=1,
                )
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    break
            if raw is None or raw.empty:
                return empty_stock_flow("akshare", issues=["stock fund flow unavailable"])
            return prepare_stock_flow(
                raw,
                source="akshare",
                code=code,
                start=start_date,
                end=end_date,
                amount_unit="yuan",
            )

        result = self._cached(
            ("stock_fund_flow", code, start, end),
            self.cache_ttl,
            loader,
            empty_stock_flow("akshare"),
        )
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer(
                "get_stock_fund_flow",
                code,
                start or None,
                end or None,
                allow_fallback=False,
            )
            if alt is not None and not alt.empty:
                return attach_date_swap(alt, swapped)
        if result is None or result.empty:
            return attach_date_swap(
                empty_stock_flow("akshare", issues=["stock fund flow unavailable"]),
                swapped,
            )
        return attach_date_swap(result, swapped)

    def get_market_fund_flow(self, start_date=None, end_date=None, allow_fallback=True):
        """两市主力资金时间序列。金额单位：万元。"""
        start, end, swapped = ordered_date_range(start_date, end_date)
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer(
                    "get_market_fund_flow", start or None, end or None, allow_fallback=False
                )
                if alt is not None and not alt.empty:
                    return attach_date_swap(alt, swapped)
            return self._unavailable(empty_market_flow)

        def loader():
            ak = self._client()
            raw = None
            for api_name in ("stock_market_fund_flow", "stock_main_fund_flow"):
                api = getattr(ak, api_name, None)
                if api is None:
                    continue
                raw = self._fetch(api, default=None, label=api_name, retries=1)
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    break
            if raw is None or raw.empty:
                return empty_market_flow("akshare", issues=["market fund flow unavailable"])
            return prepare_market_flow(
                raw, source="akshare", amount_unit="yuan", start=start_date, end=end_date
            )

        result = self._cached(
            ("market_fund_flow", start, end),
            self.cache_ttl,
            loader,
            empty_market_flow("akshare"),
        )
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer(
                "get_market_fund_flow", start or None, end or None, allow_fallback=False
            )
            if alt is not None and not alt.empty:
                return attach_date_swap(alt, swapped)
        if result is None or result.empty:
            return attach_date_swap(
                empty_market_flow("akshare", issues=["market fund flow unavailable"]),
                swapped,
            )
        return attach_date_swap(result, swapped)

    def get_cross_border_flow(self, start_date=None, end_date=None, allow_fallback=True):
        """北向 + 南向（能拿到的列都保留）。金额单位：万元。"""
        start, end, swapped = ordered_date_range(start_date, end_date)
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer(
                    "get_cross_border_flow", start or None, end or None, allow_fallback=False
                )
                if alt is not None and not alt.empty:
                    return attach_date_swap(alt, swapped)
            return self._unavailable(empty_cross_border)

        def loader():
            north = self._fetch_hsgt_leg("北向资金", "northbound")
            south = self._fetch_hsgt_leg("南向资金", "southbound")
            merged = _merge_cross_border(north, south, source="akshare")
            if merged is None or merged.empty:
                return empty_cross_border("akshare", issues=["cross-border flow unavailable"])
            return prepare_cross_border(
                merged,
                source="akshare",
                direction="northbound",
                amount_unit="wan",
                start=start_date,
                end=end_date,
            )

        result = self._cached(
            ("cross_border_flow", start, end),
            self.cache_ttl,
            loader,
            empty_cross_border("akshare"),
        )
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer(
                "get_cross_border_flow", start or None, end or None, allow_fallback=False
            )
            if alt is not None and not alt.empty:
                return attach_date_swap(alt, swapped)
        if result is None or result.empty:
            return attach_date_swap(
                empty_cross_border("akshare", issues=["cross-border flow unavailable"]),
                swapped,
            )
        return attach_date_swap(result, swapped)

    def _fetch_hsgt_leg(self, symbol, direction):
        ak = self._client()
        raw = None
        used_api = None
        hist = getattr(ak, "stock_hsgt_hist_em", None)
        if hist is not None:
            raw = self._fetch(
                lambda: hist(symbol=symbol),
                default=None,
                label=f"stock_hsgt_hist_em:{symbol}",
                retries=1,
            )
            if isinstance(raw, pd.DataFrame) and not raw.empty:
                used_api = "stock_hsgt_hist_em"
        if (raw is None or (isinstance(raw, pd.DataFrame) and raw.empty)) and direction == "northbound":
            for api_name, kwargs in (
                ("stock_hsgt_north_net_flow_in_em", {}),
                ("stock_hsgt_fund_flow_summary_em", {}),
            ):
                api = getattr(ak, api_name, None)
                if api is None:
                    continue
                raw = self._fetch(
                    lambda api=api, kwargs=kwargs: api(**kwargs),
                    default=None,
                    label=api_name,
                    retries=1,
                )
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    used_api = api_name
                    break
        if raw is None or (isinstance(raw, pd.DataFrame) and raw.empty):
            return pd.DataFrame()
        work = rename_columns(raw.copy())
        work = work.copy()
        work["_leg"] = direction
        # 东财沪深港通历史「当日成交净买额」为万元；north_net_flow_in 多为元。
        unit = "wan"
        if used_api == "stock_hsgt_north_net_flow_in_em":
            unit = "yuan"
        elif used_api == "stock_hsgt_fund_flow_summary_em":
            unit = "auto"
        work["_amount_unit"] = unit
        return work

    def get_northbound_flow(self, start_date=None, end_date=None, allow_fallback=True):
        """北向资金净流入时间序列。金额单位：万元。"""
        frame = self.get_cross_border_flow(start_date, end_date, allow_fallback=allow_fallback)
        if frame is None or frame.empty:
            return frame if frame is not None else empty_cross_border("akshare", direction="northbound")
        work = frame.copy()
        work.attrs.update(frame.attrs)
        if "north_inflow" in work.columns:
            work["net_inflow"] = work["north_inflow"]
        work["direction"] = "northbound"
        work.attrs["direction"] = "northbound"
        return work

    def get_southbound_flow(self, start_date=None, end_date=None, allow_fallback=True):
        """南向资金净流入时间序列。金额单位：万元。"""
        frame = self.get_cross_border_flow(start_date, end_date, allow_fallback=allow_fallback)
        if frame is None or frame.empty:
            return empty_cross_border(
                frame.attrs.get("source") if frame is not None else "akshare",
                issues=(frame.attrs.get("issues") if frame is not None else None) or ["southbound unavailable"],
                direction="southbound",
            )
        if "south_inflow" not in frame.columns or frame["south_inflow"].notna().sum() == 0:
            issues = list(frame.attrs.get("issues") or [])
            if "southbound unavailable" not in issues:
                issues.append("southbound unavailable")
            return empty_cross_border(
                frame.attrs.get("source") or "akshare",
                issues=issues,
                direction="southbound",
            )
        work = frame.copy()
        work.attrs.update(frame.attrs)
        work["net_inflow"] = work["south_inflow"]
        work["direction"] = "southbound"
        work.attrs["direction"] = "southbound"
        return work

    def get_trade_calendar(self, start_date=None, end_date=None):
        """交易日历，列：date, is_open。"""
        if not self.is_available():
            return stamp_frame(
                pd.DataFrame(columns=["date", "is_open"]),
                "akshare",
                error="akshare unavailable",
                issues=["akshare unavailable"],
            )

        def loader():
            ak = self._client()
            raw = None
            for api_name in ("tool_trade_date_hist_sina", "tool_trade_date_hist"):
                api = getattr(ak, api_name, None)
                if api is None:
                    continue
                raw = self._fetch(api, default=None, label=api_name)
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    break
            if raw is None or raw.empty:
                return stamp_frame(pd.DataFrame(columns=["date", "is_open"]), "akshare")
            work = rename_columns(raw)
            date_col = "date" if "date" in work.columns else work.columns[0]
            dates = pd.to_datetime(work[date_col], errors="coerce").dt.normalize()
            cal = pd.DataFrame({"date": dates, "is_open": True, "source": "akshare"})
            cal = cal.dropna(subset=["date"]).drop_duplicates("date")
            return stamp_frame(cal, "akshare")

        cal = self._cached(("trade_calendar",), self.ttl_calendar, loader, stamp_frame(pd.DataFrame(columns=["date", "is_open"]), "akshare"))
        if cal is None or cal.empty:
            return cal
        work = cal.copy()
        if start_date:
            work = work[work["date"] >= pd.to_datetime(compact_date(start_date), format="%Y%m%d", errors="coerce")]
        if end_date:
            work = work[work["date"] <= pd.to_datetime(compact_date(end_date), format="%Y%m%d", errors="coerce")]
        return work.reset_index(drop=True)

    def is_trading_day(self, day=None):
        day = pd.to_datetime(day or pd.Timestamp.now().normalize()).normalize()
        cal = self.get_trade_calendar()
        if cal is None or cal.empty:
            return bool(day.weekday() < 5)
        return bool((cal["date"] == day).any())

    def get_halted_stocks(self):
        """停牌列表。"""
        if not self.is_available():
            return self._unavailable(empty_list)

        def loader():
            ak = self._client()
            raw = None
            for api_name in ("stock_tfp_em", "stock_zh_a_stop_em"):
                api = getattr(ak, api_name, None)
                if api is None:
                    continue
                raw = self._fetch(api, default=None, label=api_name, retries=1)
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    break
            if raw is None or raw.empty:
                spot = self.get_spot_snapshot()
                if spot is not None and not spot.empty and "status" in spot.columns:
                    halted = spot[spot["status"] == "halted"].copy()
                    return stamp_frame(halted, "akshare")
                return empty_list("akshare")
            work = normalize_stock_list(raw, source="akshare")
            work["status"] = "halted"
            return work

        return self._cached(("halted",), self.ttl_realtime, loader, empty_list("akshare"))

    def get_basic_info(self, stock_code):
        """个股概况，返回 dict。"""
        code = normalize_stock_code(stock_code)
        if not code:
            return {"code": stock_code, "source": "akshare", "available": False, "error": "invalid stock code"}
        if not self.is_available():
            return {"code": code, "source": "akshare", "available": False, "error": "akshare unavailable"}

        def loader():
            info = {"code": code, "source": "akshare", "exchange": None, "board": None}
            ak = self._client()
            api = getattr(ak, "stock_individual_info_em", None)
            raw = None
            if api is not None:
                raw = self._fetch(lambda: api(symbol=code), default=None, label="stock_individual_info_em", retries=1)
            if isinstance(raw, pd.DataFrame) and not raw.empty:
                item_col = raw.columns[0]
                value_col = raw.columns[1] if raw.shape[1] > 1 else raw.columns[0]
                mapping = {
                    "股票简称": "name",
                    "名称": "name",
                    "行业": "industry",
                    "所属行业": "industry",
                    "上市时间": "list_date",
                    "总市值": "market_cap",
                    "流通市值": "circ_mv",
                }
                for _, row in raw.iterrows():
                    key = str(row[item_col]).strip()
                    if key in mapping:
                        info[mapping[key]] = row[value_col]
            quote = self.get_realtime_quote(code)
            if quote is not None and not quote.empty:
                row = quote.iloc[0]
                info.setdefault("name", row.get("name"))
                info["price"] = row.get("price")
                info["pe"] = row.get("pe")
                info["pb"] = row.get("pb")
                info["exchange"] = row.get("exchange")
                info["board"] = row.get("board")
                info["status"] = row.get("status")
            from .quality import infer_board, infer_exchange

            info["exchange"] = info.get("exchange") or infer_exchange(code)
            info["board"] = info.get("board") or infer_board(code, info.get("name") or "")
            return info

        return self._cached(("basic_info", code), self.ttl_list, loader, {"code": code, "source": "akshare"})


class AKShareIndicator:
    """
    链式技术指标计算，兼容 examples/test_data_source.py 与 simple_analysis.py。
    内部复用 src.analysis.technical.TechnicalAnalyzer。
    """

    def __init__(self):
        self.df = None
        self._analyzer = None

    def calculate_ma(self, hist, periods=None):
        periods = periods or [5, 10, 20]
        self._analyzer = TechnicalAnalyzer(hist)
        self._analyzer.calculate_ma(periods)
        self.df = self._analyzer.get_data()
        return self

    def calculate_macd(self, fast=12, slow=26, signal=9):
        self._ensure_analyzer()
        self._analyzer.calculate_macd(fast=fast, slow=slow, signal=signal)
        self.df = self._analyzer.get_data()
        return self

    def calculate_rsi(self, period=14):
        self._ensure_analyzer()
        self._analyzer.calculate_rsi(period=period)
        self.df = self._analyzer.get_data()
        return self

    def calculate_bollinger(self, period=20, num_std=2):
        self._ensure_analyzer()
        self._analyzer.calculate_bollinger(period=period, num_std=num_std)
        self.df = self._analyzer.get_data()
        return self

    def calculate_kdj(self):
        self._ensure_analyzer()
        self._analyzer.calculate_kdj()
        self.df = self._analyzer.get_data()
        return self

    def get_data(self):
        if self.df is None and self._analyzer is not None:
            return self._analyzer.get_data()
        return self.df

    def _ensure_analyzer(self):
        if self._analyzer is None:
            if self.df is None:
                raise ValueError("请先调用 calculate_ma(hist, periods) 传入行情")
            self._analyzer = TechnicalAnalyzer(self.df)


def _ak_flow_market(code):
    if str(code).startswith(("6", "9")):
        return "sh"
    if str(code).startswith(("8", "4")):
        return "bj"
    return "sz"


def _merge_cross_border(north, south, source="akshare"):
    """把北向 / 南向两腿合成一张带 date 的表，供 prepare_cross_border 使用。"""
    frames = []
    for raw, inflow_col in ((north, "north_inflow"), (south, "south_inflow")):
        if raw is None or (isinstance(raw, pd.DataFrame) and raw.empty):
            continue
        work = raw.copy()
        if "date" not in work.columns:
            for candidate in work.columns:
                if "date" in str(candidate).lower() or "日期" in str(candidate):
                    work = work.rename(columns={candidate: "date"})
                    break
        if "date" not in work.columns:
            continue
        keep = ["date"]
        value = None
        for col in ("net_inflow", "当日成交净买额", "value", "north_money", "south_money"):
            if col in work.columns:
                value = work[col]
                break
        if value is None:
            numeric = [c for c in work.columns if c != "date" and pd.api.types.is_numeric_dtype(work[c])]
            if numeric:
                value = work[numeric[0]]
        if value is None:
            continue
        piece = pd.DataFrame({"date": work["date"], inflow_col: value})
        for extra in ("buy_amount", "sell_amount", "买入成交额", "卖出成交额"):
            if extra in work.columns:
                dest = {"买入成交额": "buy_amount", "卖出成交额": "sell_amount"}.get(extra, extra)
                piece[dest] = work[extra]
        unit = "wan"
        if "_amount_unit" in work.columns and len(work):
            unit = str(work["_amount_unit"].iloc[0] or "wan")
        money = [c for c in (inflow_col, "buy_amount", "sell_amount") if c in piece.columns]
        piece, _, _ = scale_money_to_wan(piece, money, unit, context="cross_border")
        frames.append(piece)
    if not frames:
        return pd.DataFrame()
    merged = frames[0]
    for extra in frames[1:]:
        merged = pd.merge(merged, extra, on="date", how="outer")
    merged["source"] = source
    return merged


def _quote_from_item_value(raw, code):
    if raw is None or (isinstance(raw, pd.DataFrame) and raw.empty):
        return None
    if not isinstance(raw, pd.DataFrame):
        return None
    work = raw.copy()
    if work.shape[1] < 2:
        return None
    data = {}
    item_col, value_col = work.columns[0], work.columns[1]
    for _, row in work.iterrows():
        data[str(row[item_col]).strip()] = row[value_col]
    price = None
    for key in ("最新价", "现价", "price", "最新"):
        if key in data:
            price = to_numeric(pd.Series([data[key]])).iloc[0]
            break
    if price is None:
        return None
    frame = pd.DataFrame(
        {
            "code": [code],
            "name": [data.get("名称") or data.get("股票简称")],
            "price": [price],
            "source": ["akshare"],
        }
    )
    return normalize_quotes(frame, source="akshare")
