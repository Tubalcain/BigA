"""
AKShare 数据适配器。

覆盖页面真正用到的能力：历史 OHLCV、实时报价、股票列表、
市场概况、指数、行业板块、资金流向、交易日历、停牌股。
"""

from __future__ import annotations

import logging

import pandas as pd

from src.analysis.technical import TechnicalAnalyzer

from .cache import get_cache, make_cache_key
from .config import get_data_config
from .fetch import DataFetchError, safe_fetch
from .quality import (
    compact_date,
    empty_flow,
    empty_index,
    empty_list,
    empty_ohlcv,
    empty_overview,
    empty_quotes,
    infer_limit_pct,
    match_exchange,
    normalize_adjust,
    normalize_period,
    normalize_quotes,
    normalize_stock_code,
    normalize_stock_list,
    prepare_ohlcv,
    rename_columns,
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
        if not self.config.fallback:
            return None
        try:
            from .tushare_data import TuShareData

            other = TuShareData(self.config)
            if not other.is_available():
                return None
            df = other.get_history_data(
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
        except Exception as exc:
            logger.warning("TuShare 回退失败: %s", exc)
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
        start = compact_date(start_date)
        end = compact_date(end_date)
        if not code:
            return empty_ohlcv(
                "akshare",
                error=f"invalid stock code: {stock_code!r}",
                issues=["invalid stock code"],
            )

        key = ("history", code, start, end, period_key, adj)
        cache_key = make_cache_key("AKShareData", *key)
        cached = self.cache.get(cache_key)
        if cached is not None and validate_ohlcv(cached)[0]:
            return cached

        df = self._fetch_history(code, start, end, period_key, adj)
        ok, issues = validate_ohlcv(df)
        if ok:
            self.cache.set(cache_key, df, ttl=self.cache_ttl)
            return df
        if allow_fallback:
            fallback = self._fallback_history(code, start, end, period_key, adj)
            if fallback is not None and validate_ohlcv(fallback)[0]:
                return fallback
        logger.warning("AKShare 历史数据不可用 %s: %s", code, issues)
        return df if df is not None else empty_ohlcv("akshare", issues=issues)

    def _fetch_history(self, code, start, end, period, adjust):
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
            start=start,
            end=end,
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
                return empty_quotes("akshare")
            return normalize_quotes(raw, source="akshare", market_cap_unit="yuan")

        if force:
            return loader()
        return self._cached(("spot_snapshot",), self.ttl_realtime, loader, empty_quotes("akshare"))

    def get_stock_list(self, exchange="所有", allow_fallback=True):
        """
        股票列表。优先返回带行情字段的快照，便于筛选器按市值/涨跌幅/成交量过滤。
        """

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
            if allow_fallback and self.config.fallback:
                try:
                    from .tushare_data import TuShareData

                    other = TuShareData(self.config)
                    if other.is_available():
                        return other.get_stock_list(exchange, allow_fallback=False)
                except Exception as exc:
                    logger.warning("股票列表回退失败: %s", exc)
            return empty_list("akshare", error="stock list unavailable")
        if "code" in df.columns:
            mask = df["code"].map(lambda c: match_exchange(c, exchange))
            df = df[mask].reset_index(drop=True)
        return stamp_frame(df, df.attrs.get("source") or "akshare")

    def get_realtime_quote(self, stock_code):
        """单只股票实时行情，至少包含 price 列（投资组合页依赖）。"""
        code = normalize_stock_code(stock_code)
        if not code:
            return empty_quotes("akshare")

        spot = self.get_spot_snapshot()
        if spot is not None and not spot.empty and "code" in spot.columns:
            row = spot[spot["code"] == code]
            if not row.empty:
                return stamp_frame(row.reset_index(drop=True), "akshare")

        def loader():
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
            hist = self.get_history_data(code, "", "", allow_fallback=True)
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
        return quote

    def get_market_overview(self, light=False):
        """涨跌分布，列：type, count。默认先乐咕再快照；light=True 不打全市场。"""

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
            return empty_overview("akshare")
        return overview

    def get_index_quotes(self):
        """主要 A 股指数实时行情。"""

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
                return empty_index("akshare")
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

        return self._cached(("index_quotes",), self.ttl_realtime, loader, empty_index("akshare"))

    def get_industry_boards(self):
        """行业板块行情（东财）。"""

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

    def get_fund_flow(self, indicator="今日"):
        """行业资金流向。列：name, net_inflow, change_pct。"""

        def loader():
            ak = self._client()
            raw = None
            attempts = []
            sector_api = getattr(ak, "stock_sector_fund_flow_rank", None)
            if sector_api is not None:
                attempts.append(
                    (
                        "stock_sector_fund_flow_rank",
                        lambda: sector_api(indicator=indicator, sector_type="行业资金流"),
                    )
                )
                attempts.append(
                    ("stock_sector_fund_flow_rank:今日", lambda: sector_api(indicator="今日"))
                )
            rank_api = getattr(ak, "stock_individual_fund_flow_rank", None)
            if rank_api is not None:
                attempts.append(
                    ("stock_individual_fund_flow_rank", lambda: rank_api(indicator=indicator))
                )
            for label, func in attempts:
                raw = self._fetch(func, default=None, label=label, retries=1)
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    break
            if raw is None or raw.empty:
                return empty_flow("akshare")
            work = rename_columns(raw)
            if "name" not in work.columns:
                for col in work.columns:
                    if "名称" in str(col) or "板块" in str(col):
                        work = work.rename(columns={col: "name"})
                        break
            if "net_inflow" not in work.columns:
                for col in list(work.columns):
                    if "净流入" in str(col) or "净额" in str(col):
                        work["net_inflow"] = to_numeric(work[col])
                        break
            if "change_pct" not in work.columns:
                for col in list(work.columns):
                    if "涨跌幅" in str(col):
                        work["change_pct"] = to_numeric(work[col])
                        break
            work["source"] = "akshare"
            keep = [c for c in ["name", "net_inflow", "change_pct", "source"] if c in work.columns]
            extras = [c for c in work.columns if c not in keep]
            return stamp_frame(work[keep + extras], "akshare")

        return self._cached(("fund_flow", indicator), self.ttl_realtime, loader, empty_flow("akshare"))

    def get_northbound_flow(self):
        """北向资金净流入（若接口可用）。"""

        def loader():
            ak = self._client()
            raw = None
            for api_name, kwargs in (
                ("stock_hsgt_north_net_flow_in_em", {}),
                ("stock_hsgt_hist_em", {"symbol": "北向资金"}),
                ("stock_hsgt_fund_flow_summary_em", {}),
            ):
                api = getattr(ak, api_name, None)
                if api is None:
                    continue
                raw = self._fetch(lambda api=api, kwargs=kwargs: api(**kwargs), default=None, label=api_name, retries=1)
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    break
            if raw is None or raw.empty:
                return stamp_frame(pd.DataFrame(), "akshare")
            work = rename_columns(raw)
            work["source"] = "akshare"
            return stamp_frame(work, "akshare")

        return self._cached(("northbound",), self.ttl_realtime, loader, stamp_frame(pd.DataFrame(), "akshare"))

    def get_trade_calendar(self, start_date=None, end_date=None):
        """交易日历，列：date, is_open。"""

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
            return {}

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
