"""
数据层：A股行情 / 列表 / 市场概况 / 资金流向采集。

页面与示例直接使用：
- AKShareData / AKShareIndicator
- TuShareData

两套适配器输出同一套标准化列名；任一源失败时按配置回退到另一源。
资金流金额统一为万元。OpenBB 未接入，仅作为可选的未来扩展。
"""

from .akshare_data import AKShareData, AKShareIndicator
from .cache import reset_cache
from .config import get_data_config, load_app_config
from .quality import describe_data_problems, outlier_count
from .tushare_data import TuShareData

__all__ = [
    "AKShareData",
    "AKShareIndicator",
    "TuShareData",
    "get_data_source",
    "get_active_client",
    "get_data_config",
    "load_app_config",
    "describe_data_problems",
    "outlier_count",
    "source_switch_note",
    "reset_cache",
]


def get_data_source(name=None):
    """
    按名称返回数据源实例，不在工厂里偷偷换源。

    name 为空时用配置 `data_sources.primary`。
    主源失败时的回退由 get_history_data / get_stock_list 等按 config.fallback 处理。
    页面请用 get_active_client()：当前源不可用时会换到另一源。
    """
    cfg = get_data_config()
    source = (name or cfg.primary or "akshare").strip().lower()
    if source in ("tushare", "ts"):
        return TuShareData(cfg)
    return AKShareData(cfg)


def get_active_client(name=None):
    """
    给页面用的客户端：先按 name / primary 取源，不可用则换到另一源。
    与 get_data_source 不同，这里会换源（akshare ↔ tushare），避免每个页面复制降级逻辑。
    """
    client = get_data_source(name)
    if client.is_available():
        return client
    other_name = "tushare" if getattr(client, "name", "") == "akshare" else "akshare"
    other = get_data_source(other_name)
    if other.is_available():
        return other
    return client


def source_switch_note(preferred, client):
    """页面空态：所选源不可用并已换到另一源时返回提示，否则空串。"""
    used = getattr(client, "name", "") or ""
    want = (preferred or "").strip().lower()
    if want in ("ts",):
        want = "tushare"
    if want and used and used != want:
        return f"数据源 {want} 不可用，已切换为 {used}"
    return ""
