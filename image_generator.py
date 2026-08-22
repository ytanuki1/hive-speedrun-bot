# -*- coding: utf-8 -*-
"""
マイクラ風GUIのランキング画像を生成するモジュール。
項目ごとに独立した半透明ボックスを配置し、背景画像を活かしたレイアウトに再現する。
"""

from __future__ import annotations

import io
import logging
import os
import re
from functools import lru_cache
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import config
from gas_client import PlayerEntry

logger = logging.getLogger("image_generator")

_JP_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
)

# ------------------------------------------------------------
# フォント読み込み
# ------------------------------------------------------------
@lru_cache(maxsize=64)
def _load_font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    if kind == "mojang":
        path = config.FONT_MOJANGLES
    else:
        path = config.FONT_UNIFONT

    try:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
        logger.warning("フォントファイルが見つかりません: %s", path)
    except OSError as e:
        logger.warning("フォント読み込みに失敗しました (%s): %s", path, e)
    return ImageFont.load_default()

@lru_cache(maxsize=8)
def _load_unifont_fallback(size: int) -> Optional[ImageFont.FreeTypeFont]:
    candidates = [
        config.FONT_UNIFONT,
        "/usr/share/fonts/opentype/unifont/unifont_jp.otf",
    ]
    # Unifontは小さく見えやすいため微調整
    adjusted_size = int(size * 1.1)
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, adjusted_size)
            except OSError:
                continue
    return None

def _has_jp(text: str) -> bool:
    return bool(_JP_RE.search(text))

def _pick_font(text: str, size: int) -> ImageFont.FreeTypeFont:
    if _has_jp(text):
        font = _load_unifont_fallback(size)
        if font:
            return font
    return _load_font("mojang", size)

# ------------------------------------------------------------
# 描画ユーティリティ
# ------------------------------------------------------------
def _draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    shadow: tuple[int, int, int, int] = config.COLORS["shadow"],
    anchor: str = "la",
    shadow_offset: int = 2,
) -> None:
    x, y = pos
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=shadow, anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)

def _draw_mixed_text(
    draw: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    text: str,
    size: int,
    fill: tuple[int, int, int, int],
    shadow: tuple[int, int, int, int] = config.COLORS["shadow"],
    shadow_offset: int = 2,
) -> int:
    x, y = pos

    if not _has_jp(text):
        font = _load_font("mojang", size)
        draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=shadow, anchor="lm")
        draw.text((x, y), text, font=font, fill=fill, anchor="lm")
        return int(draw.textlength(text, font=font))

    cursor_x = x
    for ch in text:
        font = _pick_font(ch, size)
        draw.text((cursor_x + shadow_offset, y + shadow_offset), ch, font=font, fill=shadow, anchor="lm")
        draw.text((cursor_x, y), ch, font=font, fill=fill, anchor="lm")
        cursor_x += int(draw.textlength(ch, font=font))
    return cursor_x - x

def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: Optional[tuple] = None,
    outline: Optional[tuple] = None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

# ------------------------------------------------------------
# 画像取得 (背景・ロゴ)
# ------------------------------------------------------------
_background_cache: dict[str, Image.Image] = {}
_logo_cache: dict[str, Optional[Image.Image]] = {}

def _fetch_background(url: str, size: tuple[int, int]) -> Image.Image:
    cache_key = f"{url}|{size[0]}x{size[1]}"
    if cache_key in _background_cache:
        return _background_cache[cache_key].copy()

    try:
        # Imgur対策としてUser-Agentを偽装
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except (requests.RequestException, OSError) as e:
        logger.warning("背景の取得に失敗しました: %s", e)
        img = Image.new("RGB", size, (18, 24, 36))
        return img

    img = ImageOps.fit(img, size, method=Image.LANCZOS, centering=(0.5, 0.4))
    img = img.filter(ImageFilter.GaussianBlur(2))
    dark_overlay = Image.new("RGBA", size, (0, 0, 0, 90))
    img_rgba = img.convert("RGBA")
    result = Image.alpha_composite(img_rgba, dark_overlay).convert("RGB")

    _background_cache[cache_key] = result.copy()
    return result

def _fetch_logo(url: str, target_height: int) -> Optional[Image.Image]:
    if not url:
        return None

    cache_key = f"{url}|h{target_height}"
    if cache_key in _logo_cache:
        cached = _logo_cache[cache_key]
        return cached.copy() if cached is not None else None

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except (requests.RequestException, OSError):
        _logo_cache[cache_key] = None
        return None

    orig_w, orig_h = img.size
    if orig_h == 0:
        _logo_cache[cache_key] = None
        return None

    ratio = target_height / orig_h
    new_w = max(1, round(orig_w * ratio))
    resized = img.resize((new_w, target_height), Image.LANCZOS)

    _logo_cache[cache_key] = resized.copy()
    return resized

# ------------------------------------------------------------
# メイン生成関数
# ------------------------------------------------------------
def generate_leaderboard_image(
    entries: list[PlayerEntry],
    division_label: str,
    country: str,
    background_url: str,
    page: int = 1,
    max_page: int = 1,
) -> Image.Image:

    # --- 国別フィルタリング ＆ 順位の再計算処理 ---
    display_entries = []
    if country and country.lower() == "jp":
        current_place = 1
        prev_time = None
        # JPプレイヤーのみ抽出
        filtered_entries = [e for e in entries if getattr(e, "country_code", "").upper() == "JP"]

        for i, e in enumerate(filtered_entries):
            # 前のプレイヤーとタイムが違う場合のみ順位を更新（同タイムの場合は同じ順位にする）
            if prev_time is not None and getattr(e, "time_seconds", None) != prev_time:
                current_place = i + 1

            # (再計算した順位, プレイヤー情報) のタプルとして保存
            display_entries.append((current_place, e))
            prev_time = getattr(e, "time_seconds", None)
    else:
        # 全体の場合は元の順位(e.place)を最優先で使う（無ければページ数を加味したインデックスを使用）
        display_entries = []
        for i, e in enumerate(entries):
            # hasattrでチェックしつつ、取得できなかった場合のフォールバックを強化
            place = getattr(e, "place", None)
            if not place:  
                place = i + 1 + (page - 1) * len(entries) # ページネーション時のズレ対策
            display_entries.append((place, e))

    # --- レイアウト設定 ---
    width = config.IMAGE_WIDTH
    height = int(width * 9 / 16) # 約16:9の比率に固定 (1010 x 568)

    pad = 20
    gap_x = 8
    gap_y = 6
    cell_h = 36

    col_w = {
        "pos": 50,
        "player": 320,
        "time": 140,
        "date": 140,
        "plat": 130
    }

    total_w = sum(col_w.values()) + gap_x * 4
    start_x = (width - total_w) // 2

    header_y = pad + cell_h + gap_y * 2
    data_start_y = header_y + cell_h + gap_y
    footer_h = 50

    # --- 背景とレイヤーの分離 ---
    # 1. 不透明な背景画像を用意 (RGB -> RGBA)
    bg = _fetch_background(background_url, (width, height)).convert("RGBA")

    # 2. 描画用の透明なオーバーレイレイヤーを作成
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 黒っぽい色、透明度50% (128 / 255) のボックス
    cell_bg = (15, 15, 15, 128) 

    # 列のX座標
    x_pos = start_x
    x_player = x_pos + col_w["pos"] + gap_x
    x_time = x_player + col_w["player"] + gap_x
    x_date = x_time + col_w["time"] + gap_x
    x_plat = x_date + col_w["date"] + gap_x

    def draw_cell(x, y, w, h, text, font, color, anchor="mm"):
        box = (x, y, x + w, y + h)
        _rounded_rect(draw, box, radius=8, fill=cell_bg)

        text_x = x + w // 2 if anchor == "mm" else x + 15
        text_y = y + h // 2
        _draw_text_with_shadow(draw, (text_x, text_y), text, font, fill=color, anchor=anchor)

    # --- ヘッダー上部: タブ + タイトル ---
    tab_text = "Japan" if country and country.lower() == "jp" else "Overall"
    tab_font = _load_font("mojang", 20)
    tab_w = int(draw.textlength(tab_text, font=tab_font)) + 30

    draw_cell(start_x, pad, tab_w, cell_h, tab_text, tab_font, config.COLORS["col_header_white"])

    title_text = f"Gravity {division_label} Leaderboard".replace("(", "").replace(")", "")
    title_font = _load_font("mojang", 20)

    t_box = (start_x + tab_w + gap_x, pad, start_x + total_w, pad + cell_h)
    _rounded_rect(draw, t_box, radius=8, fill=cell_bg)
    _draw_text_with_shadow(draw, ((t_box[0]+t_box[2])//2, (t_box[1]+t_box[3])//2), title_text, title_font, fill=config.COLORS["title_cyan"], anchor="mm")

    # --- カラムヘッダー ---
    header_font = _load_font("mojang", 20)
    draw_cell(x_pos, header_y, col_w["pos"], cell_h, "Pos", header_font, config.COLORS["col_header_pos"])
    draw_cell(x_player, header_y, col_w["player"], cell_h, "Player", header_font, config.COLORS["col_header_white"], anchor="lm")
    draw_cell(x_time, header_y, col_w["time"], cell_h, "Time", header_font, config.COLORS["col_header_green"])
    draw_cell(x_date, header_y, col_w["date"], cell_h, "Date", header_font, config.COLORS["col_header_green"])
    draw_cell(x_plat, header_y, col_w["plat"], cell_h, "Platform", header_font, config.COLORS["col_header_red"])

    # --- データ行 ---
    data_font = _load_font("mojang", 20)
    name_font_size = 20

    if not display_entries:
        empty_w = total_w
        draw_cell(start_x, data_start_y, empty_w, cell_h, "No data available", data_font, config.COLORS["text_white"])

    for i, (place, entry) in enumerate(display_entries):
        y = data_start_y + i * (cell_h + gap_y)

        # Pos (再計算された順位またはAPIの順位を利用)
        # ※整数変換しておくことで予期せぬ文字列事故を防止
        try:
            place_num = int(place)
            if place_num == 1: pos_color = config.COLORS["rank_gold"]
            elif place_num == 2: pos_color = config.COLORS["rank_silver"]
            elif place_num == 3: pos_color = config.COLORS["rank_bronze"]
            else: pos_color = config.COLORS["rank_other"]
        except ValueError:
            pos_color = config.COLORS["rank_other"]

        draw_cell(x_pos, y, col_w["pos"], cell_h, str(place), data_font, pos_color)

        # Player (混在テキスト対応)
        box_player = (x_player, y, x_player + col_w["player"], y + cell_h)
        _rounded_rect(draw, box_player, radius=8, fill=cell_bg)
        _draw_mixed_text(draw, (x_player + 15, y + cell_h//2), entry.player_name, name_font_size, fill=config.COLORS["player_name"])

        # Time (確実に半角コロンにする)
        time_text = entry.time_str.replace("：", ":")
        draw_cell(x_time, y, col_w["time"], cell_h, time_text, data_font, config.COLORS["time_lightgreen"])

        # Date (確実に半角スラッシュにする)
        date_text = (entry.date_str or "-").replace("-", "/").replace("ー", "/")
        draw_cell(x_date, y, col_w["date"], cell_h, date_text, data_font, config.COLORS["date_darkgreen"])

        # Platform
        draw_cell(x_plat, y, col_w["plat"], cell_h, entry.platform_name or "-", data_font, config.COLORS["platform_red"])

    # --- フッター (ページ番号・ロゴ表示) ---
    footer_center_y = height - (footer_h // 2)

    if max_page > 1:
        page_font = _load_font("mojang", 16)
        draw.text((start_x + total_w, footer_center_y), f"Page {page}/{max_page}", font=page_font, fill=(190, 190, 195, 200), anchor="rm")

    logo = _fetch_logo(config.LOGO_URL, config.LOGO_HEIGHT)
    if logo is not None:
        logo_x = (width - logo.width) // 2
        logo_y = footer_center_y - logo.height // 2
        # ロゴは透明レイヤー側に合成する
        overlay.alpha_composite(logo, (logo_x, logo_y))
    else:
        footer_font = _load_font("mojang", 16)
        footer_text = "The Hive - speedrun.com"
        draw.text((width // 2, footer_center_y), footer_text, font=footer_font, fill=(200, 200, 205, 200), anchor="mm")

    # 3. 背景画像と半透明オブジェクトを描画した透明レイヤーを合成
    final_canvas = Image.alpha_composite(bg, overlay)

    # RGBに変換して出力（最終的な画像ファイル自体の背景透過を防ぐ）
    return final_canvas.convert("RGB")

