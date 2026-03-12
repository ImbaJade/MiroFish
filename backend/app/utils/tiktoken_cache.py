"""tiktoken 编码缓存初始化与离线降级工具。"""

import hashlib
import os
from pathlib import Path
from typing import Optional

import requests

from ..config import Config

# tiktoken 官方 o200k_base 编码地址和哈希
O200K_BLOB_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
O200K_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"


class TiktokenFallbackError(RuntimeError):
    """tiktoken 离线降级失败。"""


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _cache_file_path(cache_dir: str, blob_url: str) -> Path:
    cache_key = hashlib.sha1(blob_url.encode()).hexdigest()
    return Path(cache_dir) / cache_key


def _copy_if_valid(source: Path, target: Path) -> bool:
    if not source.exists():
        return False

    if _sha256_file(source) != O200K_SHA256:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    return True


def _download_to_cache(target: Path, timeout_s: int = 10) -> bool:
    try:
        response = requests.get(O200K_BLOB_URL, timeout=timeout_s)
        response.raise_for_status()
        data = response.content
    except Exception:
        return False

    if hashlib.sha256(data).hexdigest() != O200K_SHA256:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return True


def ensure_tiktoken_o200k_cache(logger) -> Optional[str]:
    """确保 o200k_base 编码在本地缓存中，避免内网环境请求公网失败。"""
    cache_dir = Config.TIKTOKEN_CACHE_DIR
    if not cache_dir:
        # 空字符串表示禁用缓存，不做处理
        return None

    os.environ.setdefault("TIKTOKEN_CACHE_DIR", cache_dir)
    cache_file = _cache_file_path(cache_dir, O200K_BLOB_URL)

    if cache_file.exists():
        logger.info("tiktoken 缓存已存在: %s", cache_file)
        return cache_dir

    local_file = Config.TIKTOKEN_O200K_BASE_FILE
    if local_file and _copy_if_valid(Path(local_file), cache_file):
        logger.info("已从本地文件预热 tiktoken 缓存: %s -> %s", local_file, cache_file)
        return cache_dir

    if Config.TIKTOKEN_AUTO_FETCH and _download_to_cache(cache_file):
        logger.info("已从公网下载并缓存 tiktoken o200k_base: %s", cache_file)
        return cache_dir

    logger.warning(
        "tiktoken o200k_base 缓存未就绪。内网环境请配置 TIKTOKEN_O200K_BASE_FILE 指向离线编码文件，"
        "或在可联网环境预热 %s。",
        cache_file,
    )
    return cache_dir


def apply_tiktoken_offline_fallback(logger) -> bool:
    """在无法获取 o200k_base 时，降级为本地 byte-level 编码，避免首次离线运行直接失败。"""
    if not Config.TIKTOKEN_ENABLE_OFFLINE_FALLBACK:
        return False

    try:
        import tiktoken
        import tiktoken.registry as registry
        from tiktoken_ext import openai_public
    except Exception as exc:  # pragma: no cover - 极端导入失败
        raise TiktokenFallbackError(f"导入 tiktoken 失败: {exc}") from exc

    try:
        tiktoken.get_encoding("o200k_base")
        return False
    except Exception:
        pass

    original_o200k_base = openai_public.o200k_base

    def _offline_o200k_base():
        try:
            return original_o200k_base()
        except Exception:
            # 构造纯本地 byte-level 编码，避免任何网络请求。
            mergeable_ranks = {bytes([i]): i for i in range(256)}
            return {
                "name": "o200k_base",
                "pat_str": r"(?s).",
                "mergeable_ranks": mergeable_ranks,
                "special_tokens": {
                    "<|endoftext|>": 199999,
                    "<|endofprompt|>": 200018,
                },
            }

    openai_public.o200k_base = _offline_o200k_base

    if registry.ENCODING_CONSTRUCTORS is not None and "o200k_base" in registry.ENCODING_CONSTRUCTORS:
        registry.ENCODING_CONSTRUCTORS["o200k_base"] = _offline_o200k_base

    # 如果之前尝试过失败，清理潜在残留并重新加载
    registry.ENCODINGS.pop("o200k_base", None)

    try:
        tiktoken.get_encoding("o200k_base")
        logger.warning(
            "tiktoken o200k_base 已启用离线降级（映射到本地 byte-level 编码）。"
            "这会影响 token 计数精度，但可避免首次离线运行失败。"
        )
        return True
    except Exception as exc:
        raise TiktokenFallbackError(f"应用离线降级后仍无法加载 o200k_base: {exc}") from exc
