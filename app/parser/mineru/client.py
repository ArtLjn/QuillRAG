"""MinerU 云端 API 客户端。

借鉴自 airQA 项目 src/chunking/mineru.py（用户自有代码）。
流程：
1. POST /file-urls/batch 申请上传 URL 与 batch_id
2. PUT 上传 PDF 二进制到预签名 URL
3. GET /extract-results/batch/{batch_id} 轮询直到 state=done/failed
4. GET full_zip_url 下载 zip → 解压 → 读 content_list_v2.json

返回的 raw_data 交给 mineru_parser 转 Chunk 列表。
"""

from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.exceptions import ParseFailed
from app.core.logging import logger

DEFAULT_BASE_URL = "https://mineru.net/api/v4"
DEFAULT_MODEL_VERSION = "vlm"  # vlm = MinerU 视觉语言模型；pipeline = 传统流水线
DEFAULT_POLL_INTERVAL = 3.0
DEFAULT_TIMEOUT = 600.0


class MinerUClient:
    def __init__(
        self,
        api_token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model_version: str = DEFAULT_MODEL_VERSION,
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self.model_version = model_version
        self.timeout = timeout
        self.poll_interval = poll_interval

    async def parse_pdf_bytes(
        self,
        content: bytes,
        *,
        filename: str = "upload.pdf",
        data_id: str | None = None,
    ) -> dict[str, Any]:
        """解析 PDF，返回 content_list_v2 + 其他 JSON 聚合字典。"""
        batch_id = await self._upload(content, filename=filename, data_id=data_id)
        logger.info(f"mineru batch_id={batch_id} uploaded, waiting for result...")
        result = await self._wait(batch_id)
        if result is None:
            raise ParseFailed(f"mineru parse timeout or failed for batch_id={batch_id}")
        zip_url = result.get("full_zip_url")
        if not zip_url:
            raise ParseFailed(f"mineru result missing full_zip_url: {result}")
        return await self._download_zip(zip_url)

    async def _upload(self, content: bytes, *, filename: str, data_id: str | None) -> str:
        endpoint = f"{self.base_url}/file-urls/batch"
        payload = {
            "files": [{"name": filename, "data_id": data_id or filename}],
            "model_version": self.model_version,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(endpoint, json=payload, headers=headers)
                resp.raise_for_status()
            except Exception as exc:
                raise ParseFailed(f"mineru apply upload url failed: {exc}") from exc

            body = resp.json()
            if body.get("code") != 0:
                raise ParseFailed(f"mineru apply rejected: {body.get('msg')}")

            data = body.get("data") or {}
            batch_id = data.get("batch_id")
            upload_urls = data.get("file_urls") or []
            if not batch_id or not upload_urls:
                raise ParseFailed(f"mineru apply missing batch_id/url: {body}")
            upload_url = upload_urls[0]

            try:
                put_resp = await client.put(upload_url, content=content)
                put_resp.raise_for_status()
            except Exception as exc:
                raise ParseFailed(f"mineru upload pdf failed: {exc}") from exc

        return batch_id

    async def _wait(self, batch_id: str) -> dict[str, Any] | None:
        url = f"{self.base_url}/extract-results/batch/{batch_id}"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        deadline = time.time() + self.timeout
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while time.time() < deadline:
                try:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    body = resp.json()
                except Exception as exc:
                    logger.debug(f"mineru poll error: {exc!r}; retry in {self.poll_interval}s")
                    await asyncio.sleep(self.poll_interval)
                    continue

                extract_result = (body.get("data") or {}).get("extract_result") or []
                if not extract_result:
                    await asyncio.sleep(self.poll_interval)
                    continue

                entry = extract_result[0]
                state = entry.get("state")
                if state == "done":
                    return entry
                if state == "failed":
                    err_msg = entry.get("err_msg") or "unknown"
                    raise ParseFailed(f"mineru parse failed: {err_msg}")
                await asyncio.sleep(self.poll_interval)
        return None

    async def _download_zip(self, zip_url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                resp = await client.get(zip_url)
                resp.raise_for_status()
            except Exception as exc:
                raise ParseFailed(f"mineru zip download failed: {exc}") from exc

        zip_bytes = resp.content

        # 调试用：把 zip 落盘到 data/mineru_cache/，便于排查 MinerU 实际返回结构
        try:
            cache_root = Path("data/mineru_cache")
            cache_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cache_path = cache_root / f"mineru_{stamp}.zip"
            cache_path.write_bytes(zip_bytes)
            logger.info(f"mineru zip cached at {cache_path} ({len(zip_bytes)} bytes)")
        except Exception as exc:
            logger.debug(f"mineru zip cache failed: {exc!r}")

        results: dict[str, Any] = {}
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for name in zf.namelist():
                    if not name.endswith(".json"):
                        continue
                    with zf.open(name) as f:
                        try:
                            data = json.loads(f.read().decode("utf-8"))
                        except Exception as exc:
                            logger.debug(f"mineru zip entry {name} parse failed: {exc!r}")
                            continue
                    stem = Path(name).stem
                    results[stem] = data
        except zipfile.BadZipFile as exc:
            raise ParseFailed(f"mineru zip corrupted: {exc}") from exc

        if not results:
            raise ParseFailed(f"mineru zip contains no JSON: size={len(zip_bytes)} bytes")
        logger.info(f"mineru zip parsed, json_files={list(results.keys())}")
        return results


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL_VERSION",
    "MinerUClient",
]
