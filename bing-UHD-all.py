# bing-UHD-all-0.0.0.py
# github.com/shenjuexiao
# 20261022

# bing-UHD-all.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bing 每日壁纸：抓取/合并 JSON + UHD 下载 + Markdown 生成

流程：
1. 抓取 Bing 每日壁纸 JSON，按年汇总到 bing-JSON-{mkt}-{year}.json
   （同日期去重、日期倒序），并按天保存到 bing-JSON-{mkt}-{year}/YYYYMMDD_JSON_{mkt}.json
2. 基于汇总 JSON 下载 UHD（失败回退 1920x1080）与 320x240 缩略图
3. 生成 bing-UHD-{mkt}-{year}.md（数据不存在时只生成表头）
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------- 常量配置

H1 = {
    "de-DE": "Bing-Tägliches Hintergrundbild",
    "en-CA": "Bing Daily Wallpaper",
    "en-GB": "Bing Daily Wallpaper",
    "en-IN": "Bing Daily Wallpaper",
    "en-US": "Bing Daily Wallpaper",
    "fr-FR": "Fond d'écran quotidien Bing",
    "it-IT": "Sfondo giornaliero di Bing",
    "ja-JP": "Bing デイリー壁紙",
    "zh-CN": "Bing 每日壁纸",
}

LAST_UPDATED = {
    "de-DE": "Zuletzt aktualisiert",
    "en-CA": "Last updated",
    "en-GB": "Last updated",
    "en-IN": "Last updated",
    "en-US": "Last updated",
    "fr-FR": "Dernière mise à jour",
    "it-IT": "Ultimo aggiornamento",
    "ja-JP": "最終更新",
    "zh-CN": "最后更新",
}

TABLE_HEADERS = {
    "de-DE": "| Datum | Titel | Urheberrecht | Vorschaubild |",
    "en-CA": "| Date | Title | Copyright | Thumbnail |",
    "en-GB": "| Date | Title | Copyright | Thumbnail |",
    "en-IN": "| Date | Title | Copyright | Thumbnail |",
    "en-US": "| Date | Title | Copyright | Thumbnail |",
    "fr-FR": "| Date | Titre | Droits d'auteur | Vignette |",
    "it-IT": "| Data | Titolo | Copyright | Miniatura |",
    "ja-JP": "| 日付 | タイトル | 著作権 | サムネイル |",
    "zh-CN": "| 日期 | 标题 | 版权 | 缩略图 |",
}

TABLE_SEPARATOR = "| :---: | :---: | :---: | :---: |"

BING_BASE = "https://www.bing.com"
BING_ARCHIVE = "https://www.bing.com/HPImageArchive.aspx"
CDN_BASE = "https://cdn.jsdelivr.net/gh/bingmen/bing-UHD-{year}@main"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

SUPPORTED_MKTS = [
    "de-DE", "en-CA", "en-GB", "en-IN", "en-US",
    "fr-FR", "it-IT", "ja-JP", "zh-CN",
]

# ---------------------------------------------------------------- 工具函数

def sanitize_title(title: str) -> str:
    """将标题转换为适合文件名的形式：去掉非法字符、空格转下划线。"""
    if not title:
        return "untitled"
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "", title)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "untitled"


def escape_md_cell(text: str) -> str:
    """Markdown 表格单元格内的 | 转义为 \\|。"""
    if not text:
        return ""
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def format_date(enddate: str) -> str:
    """'YYYYMMDD' -> 'YYYY-MM-DD'"""
    if len(enddate) == 8 and enddate.isdigit():
        return f"{enddate[0:4]}-{enddate[4:6]}-{enddate[6:8]}"
    return enddate


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def download_image(url: str, dest: Path, retries: int = 3) -> bool:
    """下载图片到 dest，成功返回 True。已存在且非空则跳过。"""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200 and resp.content:
                dest.write_bytes(resp.content)
                return True
            print(f"  [警告] 下载失败 (HTTP {resp.status_code})：{url}")
        except Exception as e:  # noqa: BLE001
            print(f"  [错误] 第 {attempt} 次下载异常：{url} ({e})")
        time.sleep(1.5 * attempt)
    return False

# ---------------------------------------------------------------- JSON 抓取

def fetch_one(mkt: str, idx: int) -> dict | None:
    """抓取 Bing 归档中第 idx 天的记录。"""
    params = {"format": "js", "idx": str(idx), "n": "1", "mkt": mkt}
    try:
        resp = requests.get(BING_ARCHIVE, params=params,
                            headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        print(f"  [警告] 抓取 JSON 失败 idx={idx}：{e}")
        return None

    images = data.get("images") or []
    if not images:
        return None
    img = images[0]

    url_path = img.get("url", "") or ""
    base_url_path = url_path.split("&")[0] if url_path else ""

    startdate = img.get("startdate", "")
    enddate = img.get("enddate", startdate) or startdate
    if not enddate:
        return None

    return {
        "startdate": startdate,
        "enddate": enddate,
        "title": img.get("title", ""),
        "copyright": img.get("copyright", ""),
        "url": base_url_path,
    }

def fetch_json(mkt: str, year: str, max_idx: int = 16) -> list[dict]:
    """回溯抓取 Bing 归档，返回该年度的记录列表（已去重、日期倒序）。"""
    print(f"[信息] 抓取 Bing JSON：{mkt} / {year}")
    collected: dict[str, dict] = {}
    empty_streak = 0

    for idx in range(0, max_idx + 1):
        item = fetch_one(mkt, idx)
        if not item:
            empty_streak += 1
            if empty_streak >= 3 and idx > 0:
                break
            continue
        empty_streak = 0
        enddate = item["enddate"]
        if enddate[:4] != str(year):
            # 越过目标年份后，继续少量探测后停止
            if enddate[:4] < str(year):
                continue
            continue
        collected[enddate] = item
        time.sleep(0.5)

    result = sorted(collected.values(), key=lambda x: x["enddate"], reverse=True)
    print(f"[信息] 抓取到 {len(result)} 条 {year} 年记录")
    return result

# ---------------------------------------------------------------- 主流程

def merge_and_save_json(mkt: str, year: str, out_root: Path) -> Path:
    """抓取并合并 JSON，返回汇总 JSON 路径。"""
    json_dir = out_root / f"bing-JSON-{mkt}-{year}"
    ensure_dir(json_dir)

    json_file = out_root / f"bing-JSON-{mkt}-{year}.json"

    existing: dict[str, dict] = {}
    if json_file.exists():
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                old = json.load(f)
            if isinstance(old, list):
                for it in old:
                    ed = it.get("enddate", "")
                    if ed:
                        existing[ed] = it
        except Exception as e:  # noqa: BLE001
            print(f"  [警告] 读取已有 JSON 失败：{e}")

    fetched = fetch_json(mkt, year)
    for it in fetched:
        existing[it["enddate"]] = it

    merged = sorted(existing.values(), key=lambda x: x["enddate"], reverse=True)

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    # 按天保存
    for it in merged:
        ed = it["enddate"]
        if not ed:
            continue
        day_file = json_dir / f"{ed}_JSON_{mkt}.json"
        day_file.write_text(
            json.dumps(it, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"[信息] 汇总 JSON 已写入：{json_file}（{len(merged)} 条）")
    return json_file


def process_item(item: dict, mkt: str, year: str,
                 uhd_dir: Path, thumb_dir: Path) -> dict | None:
    """处理单条记录，返回 Markdown 行所需信息。"""
    startdate = item.get("startdate", "")
    enddate = item.get("enddate", startdate) or startdate
    title = item.get("title", "")
    copyright_ = item.get("copyright", "")
    url_path = item.get("url", "")

    date_key = enddate
    base_url_path = url_path.split("&")[0] if url_path else ""

    uhd_url = f"{BING_BASE}{base_url_path.replace('1920x1080.jpg', 'UHD.jpg')}"
    thumb_url = f"{BING_BASE}{base_url_path.replace('1920x1080.jpg', '320x240.jpg')}"
    fallback_url = f"{BING_BASE}{base_url_path}"

    safe_title = sanitize_title(title)

    uhd_name = f"{date_key}_{safe_title}_UHD_{mkt}.jpg"
    fallback_name = f"{date_key}_{safe_title}_1920x1080_{mkt}.jpg"
    thumb_name = f"{date_key}_320_{mkt}.jpg"

    uhd_dest = uhd_dir / uhd_name
    fallback_dest = uhd_dir / fallback_name
    thumb_dest = thumb_dir / thumb_name

    # UHD 优先，失败回退 1920x1080
    actual_download_url = None
    if download_image(uhd_url, uhd_dest):
        actual_download_url = uhd_url
    else:
        print(f"  [回退] UHD 不存在，尝试 1920x1080：{date_key}")
        if download_image(fallback_url, fallback_dest):
            actual_download_url = fallback_url
        else:
            print(f"  [跳过] UHD 与 1920x1080 均无法下载：{date_key}")

    thumb_ok = download_image(thumb_url, thumb_dest)
    if not thumb_ok:
        print(f"  [跳过] 缩略图无法下载：{date_key}")

    if not actual_download_url and not thumb_ok:
        return None

    cdn_thumb = f"{CDN_BASE.format(year=year)}/bing-320-{mkt}-{year}/{thumb_name}"
    image_link = actual_download_url or cdn_thumb

    return {
        "startdate": startdate,
        "enddate": enddate,
        "date_key": date_key,
        "date_display": format_date(enddate),
        "title": title,
        "copyright": copyright_,
        "cdn_thumb": cdn_thumb,
        "image_link": image_link,
    }

def build_markdown(mkt: str, year: str, results: list[dict], out_root: Path) -> Path:
    """生成 Markdown。results 为空时只输出表头。"""
    md_lines = []
    md_lines.append(f"# {H1[mkt]} - UHD - {mkt} - {year}")
    md_lines.append("")
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    md_lines.append(f"> {LAST_UPDATED[mkt]}：{utc_now} UTC")
    md_lines.append("")
    md_lines.append(TABLE_HEADERS[mkt])
    md_lines.append(TABLE_SEPARATOR)

    for r in results:
        title_cell = escape_md_cell(r["title"])
        copyright_cell = escape_md_cell(r["copyright"])
        alt_text = escape_md_cell(r["title"])
        md_lines.append(
            f"| {r['date_display']} | {title_cell} | {copyright_cell} "
            f"| [![{alt_text}]({r['cdn_thumb']})]({r['image_link']}) |"
        )

    md_path = out_root / f"bing-UHD-{mkt}-{year}.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"[完成] Markdown 已写入：{md_path}")
    return md_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bing 每日壁纸 JSON 抓取、UHD 下载与 Markdown 生成"
    )
    parser.add_argument("--mkt", required=True, choices=SUPPORTED_MKTS,
                        help="市场，例如 zh-CN")
    parser.add_argument("--year", required=True, help="年份，例如 2025")
    parser.add_argument("--out-dir", default=".",
                        help="可选：输出根目录，默认为当前目录")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="可选：跳过 JSON 抓取，直接用已有汇总 JSON")
    args = parser.parse_args()

    mkt = args.mkt
    year = args.year
    out_root = Path(args.out_dir).resolve()
    ensure_dir(out_root)

    # 1) 抓取并合并 JSON
    json_file = out_root / f"bing-JSON-{mkt}-{year}.json"
    if not args.skip_fetch:
        try:
            json_file = merge_and_save_json(mkt, year, out_root)
        except Exception as e:  # noqa: BLE001
            print(f"[错误] 抓取 JSON 失败：{e}")

    # 2) 读取汇总 JSON（不存在则视为空）
    data: list[dict] = []
    if json_file.exists():
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                data = loaded
        except Exception as e:  # noqa: BLE001
            print(f"[错误] 读取 JSON 失败：{e}")
            data = []
    else:
        print(f"[信息] 汇总 JSON 不存在，仅生成表头：{json_file}")

    # 3) 目录
    uhd_dir = out_root / f"bing-UHD-{mkt}-{year}"
    thumb_dir = out_root / f"bing-320-{mkt}-{year}"
    ensure_dir(uhd_dir)
    ensure_dir(thumb_dir)

    # 4) 下载并收集行
    results: list[dict] = []
    for idx, item in enumerate(data, 1):
        enddate = item.get("enddate", "") or item.get("startdate", "")
        title = item.get("title", "")
        print(f"[{idx}/{len(data)}] {enddate} - {title}")
        try:
            row = process_item(item, mkt, year, uhd_dir, thumb_dir)
        except Exception as e:  # noqa: BLE001
            print(f"  [错误] 处理失败：{e}")
            continue
        if row:
            results.append(row)

    # 日期倒序，全量重建
    results.sort(key=lambda r: r["enddate"], reverse=True)

    # 5) 生成 Markdown
    build_markdown(mkt, year, results, out_root)
    print(f"[完成] UHD 图片目录：{uhd_dir}")
    print(f"[完成] 缩略图目录：{thumb_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
