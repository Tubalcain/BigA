"""
数据层：A股行情 / 列表 / 市场概况采集。

页面与示例直接使用：
- AKShareData / AKShareIndicator
- TuShareData

两套适配器输出同一套标准化列名；任一源失败时按配置回退到另一源。
OpenBB 未接入，仅作为可选的未来扩展。
"""

from .akshare_data import AKShareData, AKShareIndicator
from .config import get_data_config, load_app_config
from .tushare_data import TuShareData

__all__ = [
    "AKShareData",
    "AKShareIndicator",
    "TuShareData",
    "get_data_source",
    "get_data_config",
    "load_app_config",
]


def get_data_source(name=None):
    """
    按名称返回数据源实例，不在工厂里偷偷换源。

    name 为空时用配置 `data_sources.primary`。
    主源失败时的回退由 get_history_data / get_stock_list 等按 config.fallback 处理。
    页面若选了 TuShare，应检查 is_available() 后再决定是否改用 akshare。
    """
    cfg = get_data_config()
    source = (name or cfg.primary or "akshare").strip().lower()
    if source in ("tushare", "ts"):
        return TuShareData(cfg)
    return AKShareData(cfg)
