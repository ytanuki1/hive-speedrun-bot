# -*- coding: utf-8 -*-
"""
リーダーボードのキャッシュ管理（GAS Webアプリ連携版）。

speedrun.comへのデータ取得・保存はすべてGAS側で行われる。
このモジュールはGASのWebアプリ(GET action=fetch)からデータを取得し、
Python側のプロセス内メモリ（および任意でディスク）にキャッシュする。

GAS側も30分毎の時間主導トリガーで自動更新されるが、Python側でも
念のため30分毎にGASへ問い合わせ直す（GET、読み取りのみなので軽量）。
即時更新が必要な場合は cache_manager.trigger_gas_refresh() で
GASにPOSTして手動更新をトリガーできる。

JP判定は以下の優先順位で行う:
  1. speedrun.comに登録されている国籍情報 (location.country.code == "JP")
  2. 国籍が未登録の場合のみ、config.JP_WHITELIST（プレイヤー名）で補完判定
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from typing import Optional

import config
from gas_client import GasClientError, PlayerEntry, fetch_division_data, refresh_division

logger = logging.getLogger("cache_manager")

# メモリキャッシュ: key = f"{country}:{division}" -> {"entries": [...], "updated_at": float}
_memory_cache: dict[str, dict] = {}


def _cache_key(country: str, division: str) -> str:
    return f"{country}:{division}"


def _cache_file_path(key: str) -> str:
    safe_key = key.replace(":", "_")
    return os.path.join(config.CACHE_DIR, f"{safe_key}.json")


def _save_to_disk(key: str, entries: list[PlayerEntry], updated_at: float) -> None:
    try:
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        payload = {
            "updated_at": updated_at,
            "entries": [asdict(e) for e in entries],
        }
        with open(_cache_file_path(key), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError as e:
        logger.warning("キャッシュのディスク保存に失敗しました (%s): %s", key, e)


def _load_from_disk(key: str) -> Optional[dict]:
    path = _cache_file_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        entries = [PlayerEntry(**e) for e in payload.get("entries", [])]
        return {"entries": entries, "updated_at": payload.get("updated_at", 0)}
    except (OSError, json.JSONDecodeError, TypeError) as e:
        logger.warning("キャッシュのディスク読み込みに失敗しました (%s): %s", key, e)
        return None


def _is_jp_player(entry: PlayerEntry) -> bool:
    """
    JP判定:
      1. 国籍情報が登録されていれば、それが最優先（"JP"ならTrue、それ以外はFalse）
      2. 国籍情報が未登録 (country_code is None) の場合のみ、
         ホワイトリスト（プレイヤー名）で補完判定する
    """
    if entry.country_code:
        return entry.country_code == config.JP_COUNTRY_CODE

    if not config.JP_WHITELIST:
        return False

    return entry.player_name.strip().lower() in config.JP_WHITELIST


def _filter_jp(entries: list[PlayerEntry]) -> list[PlayerEntry]:
    """JP判定に合致するエントリのみ抽出し、順位(place)を振り直す。"""
    filtered = [e for e in entries if _is_jp_player(e)]
    for idx, e in enumerate(filtered, start=1):
        e.place = idx
    return filtered


def _iso_to_epoch(iso_str: Optional[str]) -> float:
    """GASが返すISO文字列(UTC)をUNIXエポック秒に変換する。取得できなければ現在時刻。"""
    if not iso_str:
        return time.time()
    try:
        import datetime as _dt

        dt = _dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return time.time()


async def refresh_all() -> None:
    """
    全ての国×部門の組み合わせについて、GAS Webアプリから最新データを取得し直す。
    speedrun.comへは直接アクセスしない（GAS側が保存済みのデータを読むだけ）。
    """
    for division_key in config.DIVISIONS.keys():
        try:
            raw_entries, updated_at_iso = fetch_division_data(division_key)
        except GasClientError as e:
            logger.error("GASからのデータ取得に失敗しました (division=%s): %s", division_key, e)
            continue

        now = _iso_to_epoch(updated_at_iso)

        # world表示: GASが保存している最大60件のうち、表示上限の上位40位までをキャッシュする
        world_entries = raw_entries[: config.MAX_ROWS_WORLD_DISPLAY]
        world_key = _cache_key("world", division_key)
        _memory_cache[world_key] = {"entries": world_entries, "updated_at": now}
        _save_to_disk(world_key, world_entries, now)

        # jp表示: GASが保存している最大60件（世界順位ベース）から国籍情報優先＋
        # ホワイトリスト補完でフィルタし、表示は上位20位までに絞る
        jp_entries = _filter_jp(raw_entries)[: config.MAX_ROWS_JP_DISPLAY]
        jp_key = _cache_key("jp", division_key)
        _memory_cache[jp_key] = {"entries": jp_entries, "updated_at": now}
        _save_to_disk(jp_key, jp_entries, now)

        logger.info(
            "キャッシュ更新完了: division=%s GAS取得件数=%d件 world表示=%d件 jp表示=%d件",
            division_key,
            len(raw_entries),
            len(world_entries),
            len(jp_entries),
        )


def trigger_gas_refresh(division_key: Optional[str] = None) -> None:
    """
    GAS Webアプリに対してPOSTを送り、その場でspeedrun.comから再取得させる（手動更新）。
    GAS側の更新が終わったら、Python側のキャッシュもrefresh_all()相当で更新し直す必要がある
    （呼び出し側が続けて refresh_all() を呼ぶこと）。
    """
    refresh_division(division_key)


def get_cached(country: str, division: str) -> Optional[dict]:
    """
    メモリキャッシュを返す。無ければディスクキャッシュを読み込んで補完する。
    戻り値: {"entries": [PlayerEntry, ...], "updated_at": float} または None
    """
    key = _cache_key(country, division)
    if key in _memory_cache:
        return _memory_cache[key]

    disk_cached = _load_from_disk(key)
    if disk_cached is not None:
        _memory_cache[key] = disk_cached
        return disk_cached

    return None


def get_page(country: str, division: str, page: int) -> Optional[dict]:
    """
    指定ページ（1始まり）分のエントリを切り出して返す。
    world: 表示上限40位までを取得件数に応じて動的にページ分割する
           （通常は最大4ページ=40位分。記録数が40件未満の場合はその実件数分）。
    jp:    表示上限20位までを取得件数に応じて動的にページ分割する
           （通常は最大2ページ=20位分。記録数が20件未満の場合はその実件数分）。
    戻り値: {"entries": [...], "updated_at": float, "page": int, "max_page": int} または None
    """
    cached = get_cached(country, division)
    if cached is None:
        return None

    all_entries = cached["entries"]

    # 実際に取得できた件数から動的にページ数を算出する
    # （記録数が表示上限に満たないゲーム・部門でもページ数が正しく縮小される）
    max_page = max(1, -(-len(all_entries) // config.ROWS_PER_PAGE))  # ceil division

    page = max(1, min(page, max_page))
    start = (page - 1) * config.ROWS_PER_PAGE
    end = start + config.ROWS_PER_PAGE
    page_entries = all_entries[start:end]

    return {
        "entries": page_entries,
        "updated_at": cached["updated_at"],
        "page": page,
        "max_page": max_page,
    }


def is_stale(updated_at: float) -> bool:
    """TTLを超えているかどうか（表示上の目安として使用）。"""
    return (time.time() - updated_at) > (config.CACHE_TTL_MINUTES * 60)