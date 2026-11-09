"""
加载 config/config.yaml，并用环境变量覆盖密钥与开关。

优先级：环境变量 > YAML > 默认值。
切勿把真实 TuShare token 写入仓库，请用 TUSHARE_TOKEN 或本地 .env。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 可选依赖
    load_dotenv = None


def find_project_root(start=None):
    """向上查找包含 config/config.yaml 的项目根目录。"""
    here = Path(start or __file__).resolve()
    candidates = [here] if here.is_dir() else []
    candidates.extend(here.parents)
    candidates.append(Path.cwd())
    for path in candidates:
        if (path / "config" / "config.yaml").exists():
            return path
    return Path.cwd()


def _load_dotenv(root):
    if load_dotenv is None:
        return
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class SourceConfig:
    name: str
    enabled: bool = True
    token: str = ""
    base_url: str = ""
    timeout: int = 30
    retries: int = 3
    retry_budget: int = 45
    adjust: str = ""


@dataclass
class CacheConfig:
    enabled: bool = True
    ttl: int = 300
    ttl_realtime: int = 30
    ttl_list: int = 3600
    ttl_calendar: int = 86400
    ttl_failure: int = 45
    ttl_success_max: int = 3600
    ttl_stale_max: int = 259200
    lock_timeout: int = 8
    persist: bool = True
    max_size: int = 1000
    directory: str = "data/cache"


@dataclass
class DataConfig:
    primary: str = "akshare"
    fallback: bool = True
    tushare: SourceConfig = field(default_factory=lambda: SourceConfig(name="tushare"))
    akshare: SourceConfig = field(default_factory=lambda: SourceConfig(name="akshare"))
    cache: CacheConfig = field(default_factory=CacheConfig)
    quality_max_abs_return: float = 1.0
    drop_outlier_bars: bool = False


def _source_from_yaml(name, raw, defaults):
    raw = raw or {}
    return SourceConfig(
        name=name,
        enabled=_as_bool(raw.get("enabled"), defaults.enabled),
        token=str(raw.get("token") or defaults.token or ""),
        base_url=str(raw.get("base_url") or defaults.base_url or ""),
        timeout=_as_int(raw.get("timeout"), defaults.timeout),
        retries=_as_int(raw.get("retries"), defaults.retries),
        retry_budget=_as_int(raw.get("retry_budget"), defaults.retry_budget),
        adjust=str(raw.get("adjust") if raw.get("adjust") is not None else defaults.adjust),
    )


def _cache_from_yaml(raw, defaults):
    raw = raw or {}
    return CacheConfig(
        enabled=_as_bool(raw.get("enabled"), defaults.enabled),
        ttl=_as_int(raw.get("ttl"), defaults.ttl),
        ttl_realtime=_as_int(raw.get("ttl_realtime"), defaults.ttl_realtime),
        ttl_list=_as_int(raw.get("ttl_list"), defaults.ttl_list),
        ttl_calendar=_as_int(raw.get("ttl_calendar"), defaults.ttl_calendar),
        ttl_failure=_as_int(raw.get("ttl_failure"), defaults.ttl_failure),
        ttl_success_max=_as_int(raw.get("ttl_success_max"), defaults.ttl_success_max),
        ttl_stale_max=_as_int(raw.get("ttl_stale_max"), defaults.ttl_stale_max),
        lock_timeout=_as_int(raw.get("lock_timeout"), defaults.lock_timeout),
        persist=_as_bool(raw.get("persist"), defaults.persist),
        max_size=_as_int(raw.get("max_size"), defaults.max_size),
        directory=str(raw.get("directory") or defaults.directory),
    )


def _apply_env(cfg: DataConfig) -> DataConfig:
    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TS_TOKEN")
    if token:
        cfg.tushare.token = token.strip()

    primary = os.getenv("BIGA_DATA_PRIMARY") or os.getenv("DATA_SOURCE")
    if primary:
        cfg.primary = primary.strip().lower()

    fallback = os.getenv("BIGA_DATA_FALLBACK")
    if fallback is not None:
        cfg.fallback = _as_bool(fallback, cfg.fallback)

    ak_enabled = os.getenv("BIGA_AKSHARE_ENABLED")
    if ak_enabled is not None:
        cfg.akshare.enabled = _as_bool(ak_enabled, cfg.akshare.enabled)

    ts_enabled = os.getenv("BIGA_TUSHARE_ENABLED")
    if ts_enabled is not None:
        cfg.tushare.enabled = _as_bool(ts_enabled, cfg.tushare.enabled)

    adjust = os.getenv("BIGA_AKSHARE_ADJUST")
    if adjust is not None:
        cfg.akshare.adjust = adjust.strip()

    cache_enabled = os.getenv("BIGA_CACHE_ENABLED")
    if cache_enabled is not None:
        cfg.cache.enabled = _as_bool(cache_enabled, cfg.cache.enabled)

    cache_persist = os.getenv("BIGA_CACHE_PERSIST")
    if cache_persist is not None:
        cfg.cache.persist = _as_bool(cache_persist, cfg.cache.persist)

    cache_dir_env = os.getenv("BIGA_CACHE_DIR")
    if cache_dir_env:
        cfg.cache.directory = cache_dir_env.strip()

    return cfg


@lru_cache(maxsize=1)
def load_app_config():
    """读取完整 YAML（含 analysis / ui），供应用其它模块复用。"""
    root = find_project_root()
    _load_dotenv(root)
    path = root / "config" / "config.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def get_data_config(reload=False) -> DataConfig:
    """返回数据层配置。reload=True 时重新读取文件与环境变量。"""
    if reload:
        load_app_config.cache_clear()
    raw = load_app_config()
    sources = raw.get("data_sources") or {}
    defaults = DataConfig()

    cfg = DataConfig(
        primary=str(sources.get("primary") or defaults.primary).lower(),
        fallback=_as_bool(sources.get("fallback"), defaults.fallback),
        tushare=_source_from_yaml("tushare", sources.get("tushare"), defaults.tushare),
        akshare=_source_from_yaml("akshare", sources.get("akshare"), defaults.akshare),
        cache=_cache_from_yaml(raw.get("cache"), defaults.cache),
        quality_max_abs_return=_as_float(
            (raw.get("data_quality") or {}).get("max_abs_return"),
            defaults.quality_max_abs_return,
        ),
        drop_outlier_bars=_as_bool(
            (raw.get("data_quality") or {}).get("drop_outlier_bars"),
            defaults.drop_outlier_bars,
        ),
    )
    return _apply_env(cfg)


def cache_dir(cfg=None) -> Path:
    cfg = cfg or get_data_config()
    path = Path(cfg.cache.directory)
    if not path.is_absolute():
        path = find_project_root() / path
    path.mkdir(parents=True, exist_ok=True)
    return path
