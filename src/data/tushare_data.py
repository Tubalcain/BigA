"""
TuShare Pro 数据适配器。

提供与 AKShareData 对齐的 get_history_data / get_stock_list / get_realtime_quote
等接口，以及 examples 使用的 get_daily_data / get_daily_basic / get_basic_info。
Token 只从环境变量 TUSHARE_TOKEN 或本地配置读取，不会写回仓库。
"""

from __future__ import annotations

import logging

import pandas as pd

from .cache import bound_failure_ttl, bound_success_ttl, cached_load, get_cache, make_cache_key
from .calendar import session_bucket, shanghai_now
from .config import get_data_config
from .fetch import (
    SAME_UPSTREAM_EASTMONEY,
    DataFetchError,
    last_fetch_diagnostic,
    raise_if_cancelled,
    safe_fetch,
)
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
    sector_type_short,
    stamp_frame,
    to_numeric,
    to_ts_code,
    validate_ohlcv,
)

logger = logging.getLogger("biga.data.tushare")


class TuShareData:
    name = "tushare"

    def __init__(self, config=None):
        self.config = config or get_data_config()
        self.source_cfg = self.config.tushare
        self.cache = get_cache(self.config)
        self.cache_ttl = self.config.cache.ttl
        self.ttl_realtime = self.config.cache.ttl_realtime
        self.ttl_list = self.config.cache.ttl_list
        self.ttl_calendar = self.config.cache.ttl_calendar
        self.token = (self.source_cfg.token or "").strip()
        self._pro = None
        self._ts = None
        self._init_error = None
        if self.source_cfg.enabled and self.token:
            self._connect()

    def _connect(self):
        try:
            import tushare as ts

            self._ts = ts
            ts.set_token(self.token)
            kwargs = {}
            if self.source_cfg.base_url:
                kwargs["url"] = self.source_cfg.base_url
            self._pro = ts.pro_api(**kwargs) if kwargs else ts.pro_api()
        except Exception as exc:
            self._init_error = exc
            self._pro = None
            logger.warning("TuShare 初始化失败: %s", exc)

    def is_available(self):
        return bool(self.source_cfg.enabled and self.token and self._pro is not None)

    def _retries(self):
        return max(int(self.source_cfg.retries or 1), 1)

    def _timeout(self):
        return int(self.source_cfg.timeout or 30)

    def _budget(self):
        return int(getattr(self.source_cfg, "retry_budget", 0) or 0) or None

    def _stamp_diag(self, value):
        diag = last_fetch_diagnostic()
        if value is None or diag is None or not hasattr(value, "attrs"):
            return value
        value.attrs["fetch_diagnostic"] = diag.as_dict()
        issues = list(value.attrs.get("issues") or [])
        issue = diag.as_issue()
        if issue not in issues:
            issues.append(issue)
        value.attrs["issues"] = issues
        return value

    def _fetch(self, func, default=None, label=""):
        raise_if_cancelled()
        result = safe_fetch(
            func,
            retries=self._retries(),
            timeout=self._timeout(),
            default=default,
            label=label,
            budget=self._budget(),
        )
        if result is None or (isinstance(result, pd.DataFrame) and result.empty):
            return self._stamp_diag(result)
        return result

    def _cached(self, key_parts, ttl, loader, default, kind="generic"):
        key = make_cache_key("TuShareData", session_bucket(), *key_parts)

        def wrapped():
            raise_if_cancelled()
            value = loader()
            if value is None:
                value = default
            if isinstance(value, pd.DataFrame) and value.empty:
                return self._stamp_diag(value)
            return value

        return cached_load(
            self.cache,
            key,
            wrapped,
            default=default,
            success_ttl=bound_success_ttl(ttl, kind=kind, cfg=self.config),
            failure_ttl=bound_failure_ttl(self.config),
            kind=kind,
            source="tushare",
        )

    def _require(self):
        if not self.is_available():
            reason = "未配置 TUSHARE_TOKEN" if not self.token else (self._init_error or "TuShare 不可用")
            raise DataFetchError(str(reason))

    def _peer(self):
        if not self.config.fallback:
            return None
        try:
            from .akshare_data import AKShareData

            other = AKShareData(self.config)
            return other if other.is_available() else None
        except Exception as exc:
            logger.warning("AKShare 回退不可用: %s", exc)
            return None

    def _try_peer(self, method, *args, **kwargs):
        if method in SAME_UPSTREAM_EASTMONEY:
            logger.info("跳过同东财上游备用 %s（AKShare 东财接口与 TuShare *_dc 同源）", method)
            return None
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
            logger.info("TuShare 历史行情失败，已回退到 AKShare: %s", code)
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
        """与 AKShareData.get_history_data 相同的页面接口。"""
        code = normalize_stock_code(stock_code)
        start, end, swapped = ordered_date_range(start_date, end_date)
        if not code:
            return empty_ohlcv(
                "tushare",
                error=f"invalid stock code: {stock_code!r}",
                issues=["invalid stock code"],
            )
        if not self.is_available():
            if allow_fallback:
                fallback = self._fallback_history(code, start, end, period, adjust)
                if fallback is not None and validate_ohlcv(fallback)[0]:
                    return attach_date_swap(fallback, swapped)
            return empty_ohlcv(
                "tushare",
                error="tushare unavailable",
                issues=["tushare unavailable"],
            )
        df = self.get_daily_data(stock_code, start_date, end_date, period=period, adjust=adjust)
        ok, issues = validate_ohlcv(df)
        if not ok and allow_fallback:
            fallback = self._fallback_history(code, start, end, period, adjust)
            if fallback is not None and validate_ohlcv(fallback)[0]:
                return attach_date_swap(fallback, swapped)
        if not ok:
            df.attrs["issues"] = issues
        return attach_date_swap(df, swapped)

    def get_daily_data(self, stock_code, start_date, end_date, period="daily", adjust=None):
        """TuShare 日/周/月线，标准化为 OHLCV。"""
        code = normalize_stock_code(stock_code)
        ts_code = to_ts_code(code)
        start, end, _ = ordered_date_range(start_date, end_date)
        period_key = normalize_period(period)
        adj = normalize_adjust(adjust if adjust is not None else self.config.akshare.adjust)
        if not code:
            return empty_ohlcv(
                "tushare",
                error=f"invalid stock code: {stock_code!r}",
                issues=["invalid stock code"],
            )

        def loader():
            if not self.is_available():
                return empty_ohlcv("tushare", issues=["tushare unavailable"])
            raw = self._fetch_bars(ts_code, start, end, period_key, adj)
            if raw is None or raw.empty:
                return empty_ohlcv("tushare", error="upstream empty", issues=["empty frame"])
            work = raw.copy()
            if "amount" in work.columns:
                work["amount"] = to_numeric(work["amount"]) * 1000
            df = prepare_ohlcv(
                work,
                source="tushare",
                code=code,
                adjust=adj,
                start=start_date,
                end=end_date,
                max_abs_return=self.config.quality_max_abs_return,
                drop_outliers=self.config.drop_outlier_bars,
            )
            df.attrs["period"] = period_key
            df.attrs["code"] = code
            return df

        return self._cached(
            ("daily", ts_code, start, end, period_key, adj),
            self.cache_ttl,
            loader,
            empty_ohlcv("tushare"),
        )

    def _fetch_bars(self, ts_code, start, end, period, adjust):
        freq = {"daily": "D", "weekly": "W", "monthly": "M"}.get(period, "D")
        raw = None
        if self._ts is not None and hasattr(self._ts, "pro_bar"):
            kwargs = {
                "ts_code": ts_code,
                "start_date": start or None,
                "end_date": end or None,
                "freq": freq,
            }
            if adjust:
                kwargs["adj"] = adjust
            raw = self._fetch(
                lambda: self._ts.pro_bar(**{k: v for k, v in kwargs.items() if v}),
                default=None,
                label=f"pro_bar:{ts_code}",
            )
        if raw is not None and not raw.empty:
            return raw

        api_name = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}.get(period, "daily")
        api = getattr(self._pro, api_name, None)
        if api is None:
            return None
        return self._fetch(
            lambda: api(ts_code=ts_code, start_date=start or "", end_date=end or ""),
            default=None,
            label=f"{api_name}:{ts_code}",
        )

    def get_daily_basic(self, stock_code, start_date, end_date):
        """每日基本面：PE/PB/换手率/市值（万元）。"""
        if not self.is_available():
            return stamp_frame(pd.DataFrame(), "tushare")
        ts_code = to_ts_code(stock_code)
        start = compact_date(start_date)
        end = compact_date(end_date)

        def loader():
            raw = self._fetch(
                lambda: self._pro.daily_basic(
                    ts_code=ts_code, start_date=start, end_date=end,
                    fields="ts_code,trade_date,close,turnover_rate,pe,pe_ttm,pb,total_mv,circ_mv,volume_ratio",
                ),
                default=None,
                label=f"daily_basic:{ts_code}",
            )
            if raw is None or raw.empty:
                return stamp_frame(pd.DataFrame(), "tushare")
            work = raw.copy()
            work = work.rename(columns={"trade_date": "date", "ts_code": "code", "turnover_rate": "turnover"})
            work["date"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
            work["code"] = work["code"].map(normalize_stock_code)
            work["source"] = "tushare"
            return stamp_frame(work.sort_values("date").reset_index(drop=True), "tushare")

        return self._cached(("daily_basic", ts_code, start, end), self.cache_ttl, loader, stamp_frame(pd.DataFrame(), "tushare"))

    def get_basic_info(self, stock_code):
        code = normalize_stock_code(stock_code)
        if not code:
            return {}
        if not self.is_available():
            return {"code": code, "source": "tushare", "available": False}

        def loader():
            ts_code = to_ts_code(code)
            raw = self._fetch(
                lambda: self._pro.stock_basic(
                    ts_code=ts_code,
                    fields="ts_code,symbol,name,area,industry,market,list_date,list_status,exchange",
                ),
                default=None,
                label=f"stock_basic:{ts_code}",
            )
            info = {"code": code, "ts_code": ts_code, "source": "tushare"}
            if raw is not None and not raw.empty:
                row = raw.iloc[0]
                info.update(
                    {
                        "name": row.get("name"),
                        "area": row.get("area"),
                        "industry": row.get("industry"),
                        "market": row.get("market"),
                        "list_date": row.get("list_date"),
                        "list_status": row.get("list_status"),
                    }
                )
            latest = self.get_daily_basic(code, "", "")
            if latest is not None and not latest.empty:
                last = latest.iloc[-1]
                info["pe"] = last.get("pe_ttm") if "pe_ttm" in latest.columns else last.get("pe")
                info["pb"] = last.get("pb")
                info["turnover"] = last.get("turnover")
            from .quality import infer_board, infer_exchange

            info["exchange"] = infer_exchange(code)
            info["board"] = infer_board(code, info.get("name") or "")
            return info

        return self._cached(("basic_info", code), self.ttl_list, loader, {"code": code, "source": "tushare"})

    def get_stock_list(self, exchange="所有", allow_fallback=True):
        def loader():
            if not self.is_available():
                return empty_list("tushare", error="tushare unavailable", issues=["tushare unavailable"])
            raw = self._fetch(
                lambda: self._pro.stock_basic(
                    list_status="L",
                    fields="ts_code,symbol,name,area,industry,market,list_date,list_status,exchange",
                ),
                default=None,
                label="stock_basic",
            )
            if raw is None or raw.empty:
                return empty_list("tushare")
            work = raw.copy()
            work["code"] = work["symbol"].map(normalize_stock_code)
            listed = normalize_stock_list(work, source="tushare")
            return listed

        df = self._cached(("stock_list",), self.ttl_list, loader, empty_list("tushare"))
        if (df is None or df.empty) and allow_fallback:
            alt = self._try_peer("get_stock_list", exchange, allow_fallback=False)
            if alt is not None and not alt.empty:
                return alt
        if df is None or df.empty:
            return empty_list("tushare", error="stock list unavailable", issues=["stock list unavailable"])
        if "code" in df.columns:
            df = df[df["code"].map(lambda c: match_exchange(c, exchange))].reset_index(drop=True)
        return df

    def get_realtime_quote(self, stock_code):
        """TuShare 免费接口无真正实时，取最近一个交易日 daily + daily_basic。"""
        code = normalize_stock_code(stock_code)
        if not code:
            return empty_quotes(
                "tushare",
                error=f"invalid stock code: {stock_code!r}",
                issues=["invalid stock code"],
            )
        if not self.is_available():
            peer_quote = self._try_peer("get_realtime_quote", stock_code)
            if peer_quote is not None and not peer_quote.empty:
                return peer_quote
            return empty_quotes("tushare", error="tushare unavailable", issues=["tushare unavailable"])

        def loader():
            end = shanghai_now().strftime("%Y%m%d")
            start = (shanghai_now() - pd.Timedelta(days=14)).strftime("%Y%m%d")
            bars = self.get_daily_data(code, start, end, period="daily")
            if bars is None or bars.empty:
                return empty_quotes("tushare")
            last = bars.iloc[-1]
            basic = self.get_daily_basic(code, start, end)
            pe = pb = turnover = market_cap = circ_mv = None
            if basic is not None and not basic.empty:
                brow = basic.iloc[-1]
                pe = brow.get("pe_ttm") if "pe_ttm" in basic.columns else brow.get("pe")
                pb = brow.get("pb")
                turnover = brow.get("turnover")
                market_cap = brow.get("total_mv")
                circ_mv = brow.get("circ_mv")
            frame = pd.DataFrame(
                {
                    "code": [code],
                    "price": [last.get("close")],
                    "open": [last.get("open")],
                    "high": [last.get("high")],
                    "low": [last.get("low")],
                    "pre_close": [last.get("pre_close") if "pre_close" in bars.columns else last.get("close")],
                    "change": [last.get("change")],
                    "change_pct": [last.get("change_pct")],
                    "volume": [last.get("volume")],
                    "amount": [last.get("amount")],
                    "pe": [pe],
                    "pb": [pb],
                    "turnover": [turnover],
                    "market_cap": [market_cap],
                    "circ_mv": [circ_mv],
                    "status": ["unknown"],
                    "source": ["tushare"],
                }
            )
            # daily_basic 市值已经是万元
            return normalize_quotes(frame, source="tushare", market_cap_unit="wan")

        quote = self._cached(("quote", code), self.ttl_realtime, loader, empty_quotes("tushare"))
        if quote is None or quote.empty:
            alt = self._try_peer("get_realtime_quote", code)
            if alt is not None and not alt.empty:
                return alt
            issues = list((quote.attrs.get("issues") if quote is not None else None) or ["quote unavailable"])
            return empty_quotes(
                "tushare",
                error=(quote.attrs.get("error") if quote is not None else None) or "quote unavailable",
                issues=issues,
            )
        return quote

    def get_market_overview(self, light=False, allow_fallback=True):
        """用最近交易日 daily 全市场涨跌估算。light 与 AKShare 对齐，但不因此返回空表。"""
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer("get_market_overview", light=light, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return empty_overview("tushare", error="tushare unavailable", issues=["tushare unavailable"])

        def loader():
            trade_date = self._latest_open_date()
            if not trade_date:
                return empty_overview("tushare")
            raw = self._fetch(
                lambda: self._pro.daily(trade_date=trade_date),
                default=None,
                label=f"daily@{trade_date}",
            )
            if raw is None or raw.empty or "pct_chg" not in raw.columns:
                return empty_overview("tushare")
            chg = to_numeric(raw["pct_chg"])
            basic = self._fetch(
                lambda: self._pro.stock_basic(list_status="L", fields="ts_code,name"),
                default=pd.DataFrame(),
                label="stock_basic:names",
            )
            names = {}
            if basic is not None and not basic.empty:
                names = dict(zip(basic["ts_code"], basic["name"]))
            limits = [
                infer_limit_pct(normalize_stock_code(ts_code), names.get(ts_code, ""))
                for ts_code in raw["ts_code"]
            ]
            limit_s = pd.Series(limits, index=raw.index)
            up_limit = chg >= (limit_s - 0.1)
            down_limit = chg <= -(limit_s - 0.1)
            rows = [
                ("涨停", int(up_limit.sum())),
                ("上涨", int(((chg > 0) & ~up_limit).sum())),
                ("平盘", int((chg == 0).sum())),
                ("下跌", int(((chg < 0) & ~down_limit).sum())),
                ("跌停", int(down_limit.sum())),
            ]
            return stamp_frame(pd.DataFrame(rows, columns=["type", "count"]).assign(source="tushare"), "tushare")

        result = self._cached(("overview",), self.ttl_realtime, loader, empty_overview("tushare"))
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer("get_market_overview", light=light, allow_fallback=False)
            if alt is not None and not alt.empty:
                return alt
        if result is None or result.empty:
            return empty_overview("tushare", issues=["overview unavailable"])
        return result

    def get_index_quotes(self, allow_fallback=True):
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer("get_index_quotes", allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return empty_index("tushare", error="tushare unavailable", issues=["tushare unavailable"])

        def loader():
            mapping = {
                "000001.SH": "上证指数",
                "399001.SZ": "深证成指",
                "399006.SZ": "创业板指",
                "000688.SH": "科创50",
                "000300.SH": "沪深300",
            }
            end = shanghai_now().strftime("%Y%m%d")
            start = (shanghai_now() - pd.Timedelta(days=10)).strftime("%Y%m%d")
            rows = []
            api = getattr(self._pro, "index_daily", None)
            if api is None:
                return empty_index("tushare")
            for ts_code, name in mapping.items():
                raw = self._fetch(
                    lambda ts_code=ts_code: api(ts_code=ts_code, start_date=start, end_date=end),
                    default=None,
                    label=f"index_daily:{ts_code}",
                )
                if raw is None or raw.empty:
                    continue
                last = raw.sort_values("trade_date").iloc[-1]
                rows.append(
                    {
                        "code": ts_code.split(".")[0],
                        "name": name,
                        "price": last.get("close"),
                        "change": last.get("change"),
                        "change_pct": last.get("pct_chg"),
                        "volume": last.get("vol"),
                        "amount": last.get("amount"),
                        "source": "tushare",
                    }
                )
            if not rows:
                return empty_index("tushare")
            return stamp_frame(pd.DataFrame(rows), "tushare")

        result = self._cached(("index_quotes",), self.ttl_realtime, loader, empty_index("tushare"))
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer("get_index_quotes", allow_fallback=False)
            if alt is not None and not alt.empty:
                return alt
        if result is None or result.empty:
            return empty_index("tushare", issues=["index quotes unavailable"])
        return result

    def get_industry_boards(self):
        """TuShare 行业分类列表（无实时涨跌时仅返回名称）。"""
        if not self.is_available():
            return stamp_frame(pd.DataFrame(), "tushare")

        def loader():
            api = getattr(self._pro, "index_classify", None)
            if api is None:
                return stamp_frame(pd.DataFrame(), "tushare")
            raw = self._fetch(lambda: api(level="L1", src="SW2021"), default=None, label="index_classify")
            if raw is None or raw.empty:
                raw = self._fetch(lambda: api(level="L1"), default=None, label="index_classify:L1")
            if raw is None or raw.empty:
                return stamp_frame(pd.DataFrame(), "tushare")
            work = raw.rename(columns={"industry_name": "name", "index_code": "code"})
            work["source"] = "tushare"
            return stamp_frame(work, "tushare")

        return self._cached(("industry_boards",), self.ttl_list, loader, stamp_frame(pd.DataFrame(), "tushare"))

    def get_fund_flow(self, indicator="今日", allow_fallback=True):
        """兼容旧接口：行业资金流向排名。不再把沪深股通当日当成板块流。"""
        return self.get_sector_fund_flow(indicator=indicator, allow_fallback=allow_fallback)

    def get_sector_fund_flow(self, indicator="今日", sector_type="行业资金流", allow_fallback=True):
        """行业 / 概念 / 地域资金流。东财行业接口是日频，多日周期不假装成功。"""
        period = normalize_flow_indicator(indicator)
        sector = normalize_sector_type(sector_type)
        if period != "今日":
            if allow_fallback:
                alt = self._try_peer("get_sector_fund_flow", period, sector, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            empty = empty_flow("tushare", issues=["tushare sector is daily only"])
            empty.attrs["requested_period"] = period
            empty.attrs["requested_sector"] = sector
            return empty
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer("get_sector_fund_flow", period, sector, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return empty_flow("tushare", error="tushare unavailable", issues=["tushare unavailable"])

        def loader():
            api = getattr(self._pro, "moneyflow_ind_dc", None)
            trade_date = self._latest_open_date()
            if api is None or not trade_date:
                return empty_flow("tushare", issues=["tushare moneyflow_ind_dc unavailable"])
            content = sector_type_short(sector)
            raw = self._fetch(
                lambda: api(trade_date=trade_date, content_type=content),
                default=None,
                label=f"moneyflow_ind_dc:{content}@{trade_date}",
            )
            if raw is None or raw.empty:
                return empty_flow("tushare", issues=["tushare sector fund flow unavailable"])
            df = prepare_flow_rank(
                raw, source="tushare", period="今日", flow_type="sector", amount_unit="yuan"
            )
            return attach_rank_scope(
                df,
                requested_period=period,
                actual_period="今日",
                requested_sector=sector,
                actual_sector=sector,
            )

        result = self._cached(
            ("sector_fund_flow", period, sector),
            self.ttl_realtime,
            loader,
            empty_flow("tushare"),
            kind="flow",
        )
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer("get_sector_fund_flow", period, sector, allow_fallback=False)
            if alt is not None and not alt.empty:
                return alt
        if result is None or result.empty:
            return empty_flow("tushare", issues=["sector fund flow unavailable"])
        return result

    def get_stock_fund_flow_rank(self, indicator="今日", allow_fallback=True):
        """最近交易日全市场 moneyflow 排名。多日周期不盖假章，回退 AKShare。"""
        period = normalize_flow_indicator(indicator)
        if period != "今日":
            if allow_fallback:
                alt = self._try_peer("get_stock_fund_flow_rank", period, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            empty = empty_flow("tushare", issues=["tushare stock rank is daily only"])
            empty.attrs["requested_period"] = period
            return empty
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer("get_stock_fund_flow_rank", period, allow_fallback=False)
                if alt is not None and not alt.empty:
                    return alt
            return empty_flow("tushare", error="tushare unavailable", issues=["tushare unavailable"])

        def loader():
            trade_date = self._latest_open_date()
            api = getattr(self._pro, "moneyflow", None)
            if api is None or not trade_date:
                return empty_flow("tushare", issues=["tushare moneyflow unavailable"])
            raw = self._fetch(
                lambda: api(trade_date=trade_date),
                default=None,
                label=f"moneyflow@{trade_date}",
            )
            if raw is None or raw.empty:
                return empty_flow("tushare", issues=["tushare stock fund flow rank unavailable"])
            work = raw.copy()
            if "ts_code" in work.columns:
                work["code"] = work["ts_code"].map(normalize_stock_code)
            names = self._code_name_map()
            if names and "code" in work.columns:
                work["name"] = work["code"].map(lambda c: names.get(c, c))
            df = prepare_flow_rank(
                work, source="tushare", period="今日", flow_type="stock", amount_unit="wan"
            )
            return attach_rank_scope(df, requested_period=period, actual_period="今日")

        result = self._cached(
            ("stock_fund_flow_rank", period),
            self.ttl_realtime,
            loader,
            empty_flow("tushare"),
            kind="flow",
        )
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer("get_stock_fund_flow_rank", period, allow_fallback=False)
            if alt is not None and not alt.empty:
                return alt
        if result is None or result.empty:
            return empty_flow("tushare", issues=["stock fund flow rank unavailable"])
        return result

    def get_stock_fund_flow(self, stock_code, start_date=None, end_date=None, allow_fallback=True):
        """个股 moneyflow 日序列。金额单位：万元。"""
        code = normalize_stock_code(stock_code)
        start, end, swapped = ordered_date_range(start_date, end_date)
        if not code:
            return empty_stock_flow(
                "tushare",
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
            return empty_stock_flow("tushare", error="tushare unavailable", issues=["tushare unavailable"])

        def loader():
            api = getattr(self._pro, "moneyflow", None)
            if api is None:
                return empty_stock_flow("tushare", issues=["tushare moneyflow unavailable"])
            ts_code = to_ts_code(code)
            raw = self._fetch(
                lambda: api(ts_code=ts_code, start_date=start or "", end_date=end or ""),
                default=None,
                label=f"moneyflow:{ts_code}",
            )
            if raw is None or raw.empty:
                return empty_stock_flow("tushare", issues=["stock fund flow unavailable"])
            work = raw.copy()
            if "ts_code" in work.columns:
                work["code"] = work["ts_code"].map(normalize_stock_code)
            return prepare_stock_flow(
                work,
                source="tushare",
                code=code,
                start=start_date,
                end=end_date,
                amount_unit="wan",
            )

        result = self._cached(
            ("stock_fund_flow", code, start, end),
            self.cache_ttl,
            loader,
            empty_stock_flow("tushare"),
            kind="flow",
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
                empty_stock_flow("tushare", issues=["stock fund flow unavailable"]),
                swapped,
            )
        return attach_date_swap(result, swapped)

    def get_market_fund_flow(self, start_date=None, end_date=None, allow_fallback=True):
        """东财大盘资金流向（需积分）。失败回退 AKShare。"""
        start, end, swapped = ordered_date_range(start_date, end_date)
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer(
                    "get_market_fund_flow", start or None, end or None, allow_fallback=False
                )
                if alt is not None and not alt.empty:
                    return attach_date_swap(alt, swapped)
            return empty_market_flow("tushare", error="tushare unavailable", issues=["tushare unavailable"])

        def loader():
            api = getattr(self._pro, "moneyflow_mkt_dc", None)
            if api is None:
                return empty_market_flow("tushare", issues=["tushare moneyflow_mkt_dc unavailable"])
            raw = self._fetch(
                lambda: api(start_date=start or "", end_date=end or ""),
                default=None,
                label="moneyflow_mkt_dc",
            )
            if raw is None or raw.empty:
                return empty_market_flow("tushare", issues=["market fund flow unavailable"])
            return prepare_market_flow(
                raw, source="tushare", amount_unit="yuan", start=start_date, end=end_date
            )

        result = self._cached(
            ("market_fund_flow", start, end),
            self.cache_ttl,
            loader,
            empty_market_flow("tushare"),
            kind="flow",
        )
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer(
                "get_market_fund_flow", start or None, end or None, allow_fallback=False
            )
            if alt is not None and not alt.empty:
                return attach_date_swap(alt, swapped)
        if result is None or result.empty:
            return attach_date_swap(
                empty_market_flow("tushare", issues=["market fund flow unavailable"]),
                swapped,
            )
        return attach_date_swap(result, swapped)

    def get_cross_border_flow(self, start_date=None, end_date=None, allow_fallback=True):
        """沪深股通 moneyflow_hsgt。金额：接口为百万，输出万元。"""
        start, end, swapped = ordered_date_range(start_date, end_date)
        if not start:
            start = (pd.Timestamp(shanghai_now()) - pd.Timedelta(days=180)).strftime("%Y%m%d")
        if not end:
            end = shanghai_now().strftime("%Y%m%d")
        if not self.is_available():
            if allow_fallback:
                alt = self._try_peer(
                    "get_cross_border_flow", start, end, allow_fallback=False
                )
                if alt is not None and not alt.empty:
                    return attach_date_swap(alt, swapped)
            return empty_cross_border("tushare", error="tushare unavailable", issues=["tushare unavailable"])

        def loader():
            api = getattr(self._pro, "moneyflow_hsgt", None)
            if api is None:
                return empty_cross_border("tushare", issues=["tushare moneyflow_hsgt unavailable"])
            raw = self._fetch(
                lambda: api(start_date=start, end_date=end),
                default=None,
                label="moneyflow_hsgt",
            )
            if raw is None or raw.empty:
                return empty_cross_border("tushare", issues=["cross-border flow unavailable"])
            return prepare_cross_border(
                raw,
                source="tushare",
                direction="northbound",
                amount_unit="baiwan",
                start=start_date,
                end=end_date,
            )

        result = self._cached(
            ("cross_border_flow", start, end),
            self.cache_ttl,
            loader,
            empty_cross_border("tushare"),
            kind="flow",
        )
        if (result is None or result.empty) and allow_fallback:
            alt = self._try_peer("get_cross_border_flow", start, end, allow_fallback=False)
            if alt is not None and not alt.empty:
                return attach_date_swap(alt, swapped)
        if result is None or result.empty:
            return attach_date_swap(
                empty_cross_border("tushare", issues=["cross-border flow unavailable"]),
                swapped,
            )
        return attach_date_swap(result, swapped)

    def get_northbound_flow(self, start_date=None, end_date=None, allow_fallback=True):
        frame = self.get_cross_border_flow(start_date, end_date, allow_fallback=allow_fallback)
        if frame is None or frame.empty:
            return frame if frame is not None else empty_cross_border("tushare", direction="northbound")
        work = frame.copy()
        work.attrs.update(frame.attrs)
        if "north_inflow" in work.columns:
            work["net_inflow"] = work["north_inflow"]
        work["direction"] = "northbound"
        work.attrs["direction"] = "northbound"
        return work

    def get_southbound_flow(self, start_date=None, end_date=None, allow_fallback=True):
        frame = self.get_cross_border_flow(start_date, end_date, allow_fallback=allow_fallback)
        if frame is None or frame.empty or "south_inflow" not in getattr(frame, "columns", []):
            return empty_cross_border(
                "tushare",
                issues=["southbound unavailable"],
                direction="southbound",
            )
        work = frame.copy()
        work.attrs.update(frame.attrs)
        work["net_inflow"] = work["south_inflow"]
        work["direction"] = "southbound"
        work.attrs["direction"] = "southbound"
        return work

    def _code_name_map(self):
        listed = self.get_stock_list("所有", allow_fallback=False)
        if listed is None or listed.empty or "code" not in listed.columns or "name" not in listed.columns:
            return {}
        return dict(zip(listed["code"], listed["name"]))

    def get_trade_calendar(self, start_date=None, end_date=None):
        start = compact_date(start_date) or (pd.Timestamp(shanghai_now()) - pd.Timedelta(days=365)).strftime("%Y%m%d")
        end = compact_date(end_date) or (pd.Timestamp(shanghai_now()) + pd.Timedelta(days=30)).strftime("%Y%m%d")

        def loader():
            if not self.is_available():
                return stamp_frame(pd.DataFrame(columns=["date", "is_open"]), "tushare")
            raw = self._fetch(
                lambda: self._pro.trade_cal(exchange="SSE", start_date=start, end_date=end),
                default=None,
                label="trade_cal",
            )
            if raw is None or raw.empty:
                return stamp_frame(pd.DataFrame(columns=["date", "is_open"]), "tushare")
            work = pd.DataFrame(
                {
                    "date": pd.to_datetime(raw["cal_date"], format="%Y%m%d", errors="coerce"),
                    "is_open": raw["is_open"].astype(str) == "1",
                    "source": "tushare",
                }
            )
            return stamp_frame(work.dropna(subset=["date"]), "tushare")

        return self._cached(("trade_calendar", start, end), self.ttl_calendar, loader, stamp_frame(pd.DataFrame(columns=["date", "is_open"]), "tushare"))

    def is_trading_day(self, day=None):
        day = pd.to_datetime(day or pd.Timestamp(shanghai_now()).normalize()).normalize()
        cal = self.get_trade_calendar(
            (day - pd.Timedelta(days=10)).strftime("%Y%m%d"),
            (day + pd.Timedelta(days=10)).strftime("%Y%m%d"),
        )
        if cal is None or cal.empty:
            return bool(day.weekday() < 5)
        hit = cal[cal["date"] == day]
        if hit.empty:
            return bool(day.weekday() < 5)
        return bool(hit.iloc[0]["is_open"])

    def get_halted_stocks(self):
        if not self.is_available():
            return empty_list("tushare", error="tushare unavailable", issues=["tushare unavailable"])

        def loader():
            trade_date = self._latest_open_date()
            api = getattr(self._pro, "suspend_d", None)
            if api is None or not trade_date:
                return empty_list("tushare")
            raw = self._fetch(
                lambda: api(suspend_type="S", trade_date=trade_date),
                default=None,
                label="suspend_d",
            )
            if raw is None or raw.empty:
                return empty_list("tushare")
            work = raw.copy()
            work["code"] = work["ts_code"].map(normalize_stock_code)
            work["status"] = "halted"
            return normalize_stock_list(work, source="tushare")

        return self._cached(("halted",), self.ttl_realtime, loader, empty_list("tushare"))

    def _latest_open_date(self):
        end = shanghai_now().strftime("%Y%m%d")
        start = (pd.Timestamp(shanghai_now()) - pd.Timedelta(days=14)).strftime("%Y%m%d")
        cal = self.get_trade_calendar(start, end)
        if cal is None or cal.empty or "is_open" not in cal.columns:
            return end
        opened = cal[cal["is_open"]].sort_values("date")
        if opened.empty:
            return end
        return opened.iloc[-1]["date"].strftime("%Y%m%d")


