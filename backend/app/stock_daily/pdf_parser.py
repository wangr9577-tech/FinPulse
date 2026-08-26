"""PDF 下载 + pypdf 解析 + 正文截取。

仅用 pypdf 快通道提取纯文本（0.1s 级）；扫描件/复杂版式提取为空时，
由调用方降级为仅标题分析（不再回退 MinerU）。
"""
import re
from pathlib import Path

import httpx

from app.stock_daily.http_client import build_headers


def download_pdf(url: str, dest_dir: Path, client: httpx.Client | None) -> Path | None:
    """下载 PDF 到 dest_dir。已存在且非空则直接复用（断点续跑）。失败返回 None。

    先下载到 `.part` 临时文件、成功后再 rename 为正式文件；失败删除残留，
    避免半截下载被下一次运行当作有效缓存复用。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[\\/:*?\"<>|]", "_", url.rsplit("/", 1)[-1])
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    dest = dest_dir / name
    if dest.exists() and dest.stat().st_size > 0:
        if is_valid_pdf(dest):
            return dest
        dest.unlink(missing_ok=True)  # 坏缓存文件重新下载
    if client is None:
        return None
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with client.stream("GET", url, headers=build_headers(), timeout=60) as resp:
            if resp.status_code != 200:
                return None
            with part.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        if part.stat().st_size > 0:
            part.replace(dest)
            if not is_valid_pdf(dest):
                dest.unlink(missing_ok=True)  # HTML 伪装等非 PDF，删除防污染缓存
                return None
            return dest
        part.unlink(missing_ok=True)
        return None
    except Exception:
        part.unlink(missing_ok=True)  # 删除半截下载，防止下次复用
        return None


def is_valid_pdf(path: Path) -> bool:
    """校验文件是否为真正的 PDF（前 8 字节须为 %PDF 开头）。"""
    try:
        with path.open("rb") as f:
            return f.read(8).startswith(b"%PDF")
    except OSError:
        return False


def parse_with_pypdf(pdf_path: Path, max_chars: int) -> str:
    """用 pypdf 提取 PDF 纯文本，截取前 max_chars；空/异常返回 ""。"""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        parts = [page.extract_text() or "" for page in reader.pages]
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        return text[:max_chars]
    except Exception:
        return ""


def clean_invalid_pdfs(pdf_dir: Path) -> int:
    """清理目录下非 %PDF 开头的缓存文件（HTML 伪装/半截下载），返回删除数量。

    递归扫描——真实缓存按 data/pdfs/<日期>/<股票键>/<uuid>.PDF 嵌套存放，
    非递归 glob 在生产上匹配不到任何文件。
    手动维护工具：无自动调用点，仅当需要清掉历史坏缓存时手动触发。
    """
    removed = 0
    if not pdf_dir.exists():
        return 0
    for p in pdf_dir.rglob("*.pdf"):
        if not is_valid_pdf(p):
            try:
                p.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
    return removed
