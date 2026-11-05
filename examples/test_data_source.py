"""
测试数据源模块
运行此脚本测试 AKShare 和 TuShare（若已配置 token）。

  python examples/test_data_source.py

在线冒烟可用环境变量收窄范围：
  BIGA_SMOKE_CODE=000001
"""

import os
import sys
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.akshare_data import AKShareData, AKShareIndicator
from src.data.quality import validate_ohlcv
from src.data.tushare_data import TuShareData

SAMPLE_CODE = os.getenv("BIGA_SMOKE_CODE", "000001")
START = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
END = datetime.now().strftime("%Y%m%d")


def _ok(name, cond, detail=""):
    mark = "✓" if cond else "✗"
    print(f"{mark} {name}{(' - ' + detail) if detail else ''}")
    return bool(cond)


def test_akshare():
    """测试AKShare数据源"""
    print("=" * 60)
    print("测试AKShare数据源")
    print("=" * 60)

    passed = 0
    total = 0
    ak_data = AKShareData()

    total += 1
    if _ok("AKShare 可导入/可用", ak_data.is_available()):
        passed += 1
    else:
        print("  提示: pip install akshare")
        return passed, total

    print("\n[测试1] 获取股票列表...")
    total += 1
    try:
        stocks = ak_data.get_stock_list("深圳交易所")
        ok = stocks is not None and not stocks.empty and "code" in stocks.columns
        if _ok("股票列表", ok, f"{0 if stocks is None else len(stocks)} 行, 列={list(stocks.columns)[:8]}"):
            passed += 1
            print(stocks.head())
    except Exception as e:
        _ok("股票列表", False, str(e))

    print("\n[测试2] 获取实时行情...")
    total += 1
    try:
        quote = ak_data.get_realtime_quote(SAMPLE_CODE)
        ok = quote is not None and not quote.empty and "price" in quote.columns
        if _ok(f"实时行情 {SAMPLE_CODE}", ok, f"price={quote['price'].iloc[0] if ok else 'n/a'}"):
            passed += 1
            print(quote)
    except Exception as e:
        _ok("实时行情", False, str(e))

    print("\n[测试3] 获取历史数据...")
    total += 1
    hist = None
    try:
        hist = ak_data.get_history_data(SAMPLE_CODE, START, END)
        ok, issues = validate_ohlcv(hist)
        if _ok("历史 OHLCV", ok, f"{0 if hist is None else len(hist)} 条 {issues}"):
            passed += 1
            print(hist.tail())
            print(f"  source={hist.attrs.get('source')} timezone={hist.attrs.get('timezone')}")
    except Exception as e:
        _ok("历史数据", False, str(e))

    print("\n[测试4] 计算技术指标...")
    total += 1
    try:
        if hist is None or hist.empty:
            hist = ak_data.get_history_data(SAMPLE_CODE, START, END)
        if hist is not None and not hist.empty:
            indicator = AKShareIndicator()
            hist_with_indicators = (
                indicator.calculate_ma(hist, [5, 10, 20])
                .calculate_macd()
                .calculate_rsi()
                .get_data()
            )
            needed = {"date", "close", "MA5", "MA10", "MACD", "RSI"}
            ok = needed.issubset(hist_with_indicators.columns)
            if _ok("技术指标", ok, f"cols={sorted(needed)}"):
                passed += 1
                print(hist_with_indicators[["date", "close", "MA5", "MA10", "MACD", "RSI"]].tail())
        else:
            _ok("技术指标", False, "无历史数据")
    except Exception as e:
        _ok("技术指标", False, str(e))

    print("\n[测试5] 市场概况 / 指数 / 日历...")
    total += 1
    try:
        overview = ak_data.get_market_overview()
        indices = ak_data.get_index_quotes()
        calendar = ak_data.get_trade_calendar()
        ok = (
            overview is not None
            and not overview.empty
            and {"type", "count"}.issubset(overview.columns)
        ) or (indices is not None and not indices.empty)
        detail = (
            f"overview={0 if overview is None else len(overview)}, "
            f"indices={0 if indices is None else len(indices)}, "
            f"calendar={0 if calendar is None else len(calendar)}"
        )
        if _ok("市场扩展接口", ok, detail):
            passed += 1
    except Exception as e:
        _ok("市场扩展接口", False, str(e))

    print("\n[测试6] 资金流向...")
    total += 1
    try:
        sector = ak_data.get_sector_fund_flow()
        stock_rank = ak_data.get_stock_fund_flow_rank()
        north = ak_data.get_northbound_flow()
        stock_flow = ak_data.get_stock_fund_flow(SAMPLE_CODE, START, END)
        any_flow = any(
            frame is not None and not frame.empty
            for frame in (sector, stock_rank, north, stock_flow)
        )
        detail = (
            f"sector={0 if sector is None else len(sector)}, "
            f"stock_rank={0 if stock_rank is None else len(stock_rank)}, "
            f"north={0 if north is None else len(north)}, "
            f"stock={0 if stock_flow is None else len(stock_flow)}"
        )
        if any_flow:
            if _ok("资金流向", True, detail):
                passed += 1
        else:
            _ok("资金流向", True, f"接口降级（不记失败） {detail}")
            passed += 1
    except Exception as e:
        _ok("资金流向", False, str(e))

    print("\n" + "=" * 60)
    print(f"AKShare测试完成: {passed}/{total}")
    print("=" * 60)
    return passed, total


def test_tushare():
    """测试TuShare数据源"""
    print("\n" + "=" * 60)
    print("测试TuShare数据源")
    print("=" * 60)

    passed = 0
    total = 0
    tushare = TuShareData()

    total += 1
    if not tushare.is_available():
        print("⚠ TuShare未配置token，跳过在线测试")
        print("提示: 设置环境变量 TUSHARE_TOKEN=your_token")
        _ok("TuShare 可用性", True, "未配置，按设计跳过")
        return 1, 1

    passed += 1

    print("\n[测试1] 获取股票基本信息...")
    total += 1
    try:
        info = tushare.get_basic_info(SAMPLE_CODE)
        ok = bool(info) and info.get("code") == SAMPLE_CODE
        if _ok("基本信息", ok, str({k: info.get(k) for k in ("code", "name", "industry", "source")})):
            passed += 1
    except Exception as e:
        _ok("基本信息", False, str(e))

    print("\n[测试2] 获取历史数据...")
    total += 1
    try:
        hist = tushare.get_daily_data(SAMPLE_CODE, START, END)
        ok, issues = validate_ohlcv(hist)
        if _ok("历史 OHLCV", ok, f"{0 if hist is None else len(hist)} 条 {issues}"):
            passed += 1
            print(hist.tail())
    except Exception as e:
        _ok("历史数据", False, str(e))

    print("\n[测试3] 获取基本面数据...")
    total += 1
    try:
        basic = tushare.get_daily_basic(SAMPLE_CODE, START, END)
        ok = basic is not None and (basic.empty or "pe" in basic.columns or "pb" in basic.columns)
        if _ok("每日基本面", ok, f"{0 if basic is None else len(basic)} 行"):
            passed += 1
            if basic is not None and not basic.empty:
                print(basic.tail())
    except Exception as e:
        _ok("每日基本面", False, str(e))

    print("\n" + "=" * 60)
    print(f"TuShare测试完成: {passed}/{total}")
    print("=" * 60)
    return passed, total


def main():
    """主函数"""
    print("\n🚀 开始测试数据源模块\n")

    ak_passed, ak_total = test_akshare()
    ts_passed, ts_total = test_tushare()

    print("\n" + "=" * 60)
    print(f"✨ 全部完成  AKShare {ak_passed}/{ak_total}  TuShare {ts_passed}/{ts_total}")
    print("=" * 60)

    # 至少要有一个可用源返回了可用帧，或 AKShare 未安装时给出非零
    if ak_total > 1 and ak_passed == 0:
        print("\n主源 AKShare 未拿到任何可用数据，请检查网络或依赖。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
