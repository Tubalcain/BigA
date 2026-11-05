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
    """按名称返回数据源实例。name 为空时使用配置中的 primary。"""
    cfg = get_data_config()
    source = (name or cfg.primary or "akshare").strip().lower()
    if source in ("tushare", "ts"):
        client = TuShareData()
        if client.is_available():
            return client
        if cfg.fallback:
            return AKShareData()
        return client
    return AKShareData()
