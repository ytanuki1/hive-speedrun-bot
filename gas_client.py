# -*- coding: utf-8 -*-
"""
speedrun.com APIから直接データを取得するクライアントモジュール。
（GASを使わず、Pythonから直接スピードランのAPIを叩く）
"""

from __future__ import annotations

import datetime
from typing import Optional

# 既存の speedrun_api からインポート
from speedrun_api import (
    PlayerEntry,
    SpeedrunAPIError as GasClientError,
    fetch_leaderboard,
)


def fetch_division_data(division_key: str) -> tuple[list[PlayerEntry], str]:
  """指定された部門のリーダーボードデータを speedrun.com から直接取得する。"""
  entries = fetch_leaderboard(division_key, 60)
  # 現在の時刻をISO形式の文字列で返す（キャッシュの更新日時として使用）
  return entries, datetime.datetime.now(datetime.timezone.utc).isoformat()


def refresh_division(division_key: Optional[str] = None) -> None:
  """Python側でのキャッシュ更新のみで完結するため、手動更新トリガー時は何もしなくてOK。"""
  pass
