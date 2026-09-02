# -*- coding: utf-8 -*-
"""
============================================================
  The Hive Speedrun Leaderboard Bot
  speedrun.com「The Hive」Gravityカテゴリのリーダーボードを
  マイクラ風GUI画像で表示するDiscord Bot。

  実行:
    python bot.py

  必要な環境変数:
    DISCORD_TOKEN   Discord Botトークン（必須）
    JP_WHITELIST    国籍未登録プレイヤーを補完判定するための名前リスト（任意）
    DEV_GUILD_ID    開発用ギルドID（任意。設定するとそのギルドのみ即時反映）
============================================================
"""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import logging
import os
import sys
import time
from threading import Thread
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

import cache_manager
import config
from gas_client import GasClientError
from image_generator import generate_leaderboard_image
from scheduler import cache_refresh_loop, run_initial_refresh

# ------------------------------------------------------------
# ロギング設定
# ------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("bot")

# ------------------------------------------------------------
# スリープ対策用 Webサーバー (Flask) の設定
# ------------------------------------------------------------
app = Flask("")


@app.route("/")
def home():
    return "Bot is running!"


def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()


# ------------------------------------------------------------
# Discord Bot 初期化
# ------------------------------------------------------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

COUNTRY_CHOICES = [
    app_commands.Choice(name="World（全プレイヤー）", value="world"),
    app_commands.Choice(name="JP（日本人プレイヤーのみ）", value="jp"),
]

DIVISION_CHOICES = [
    app_commands.Choice(name=div_conf["label"], value=key)
    for key, div_conf in config.DIVISIONS.items()
]

# ------------------------------------------------------------
# 画像キャッシュ (メモリ内)
# ------------------------------------------------------------
_image_cache: dict[tuple[str, str, int], tuple[float, bytes]] = {}


# ------------------------------------------------------------
# 画像生成 + Discord送信用ペイロード組み立て
# ------------------------------------------------------------
def _build_message_payload(
    country_key: str, division_key: str, page: int
) -> tuple[
    Optional[discord.File],
    Optional[str],
    Optional["LeaderboardView"],
    Optional[str],
]:
    div_conf = config.DIVISIONS[division_key]

    page_data = cache_manager.get_page(country_key, division_key, page)
    if page_data is None:
        return (
            None,
            None,
            None,
            (
                "リーダーボードのキャッシュがまだ準備できていません。"
                "起動直後の可能性があります。少し時間をおいて再度お試しください。"
            ),
        )

    entries = page_data["entries"]
    updated_at = page_data["updated_at"]
    current_page = page_data["page"]
    max_page = page_data["max_page"]

    cache_key = (country_key, division_key, current_page)

    # --- キャッシュの確認と画像生成 ---
    if cache_key in _image_cache and _image_cache[cache_key][0] == updated_at:
        image_bytes = _image_cache[cache_key][1]
        logger.info(
            f"キャッシュ画像を使用: {country_key}/{division_key}/page:{current_page}"
        )
    else:
        try:
            image = generate_leaderboard_image(
                entries=entries,
                division_label=div_conf["label"],
                country=country_key,
                background_url=div_conf["background_url"],
                page=current_page,
                max_page=max_page,
            )

            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            image_bytes = buffer.getvalue()

            _image_cache[cache_key] = (updated_at, image_bytes)
            logger.info(
                "画像を新規生成・キャッシュ更新:"
                f" {country_key}/{division_key}/page:{current_page}"
            )

        except Exception:
            logger.exception("画像生成中にエラーが発生しました。")
            return (
                None,
                None,
                None,
                (
                    "画像の生成中にエラーが発生しました。しばらくしてから再度お試しください。"
                ),
            )

    updated_str = dt.datetime.fromtimestamp(
        updated_at, tz=dt.timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")
    tab_label = "Japan" if country_key == "jp" else "Overall"

    range_start = (current_page - 1) * config.ROWS_PER_PAGE + 1
    range_end = range_start + len(entries) - 1
    range_label = f"{range_start}-{range_end}位" if entries else "データなし"

    content = (
        f"**{tab_label} - Gravity {div_conf['label']}** （{range_label}）\n"
        f"-# キャッシュ更新: {updated_str}（30分毎に自動更新）"
    )

    file = discord.File(fp=io.BytesIO(image_bytes), filename="leaderboard.png")

    view = (
        LeaderboardView(country_key, division_key, current_page, max_page)
        if max_page > 1
        else None
    )

    return file, content, view, None


class LeaderboardView(discord.ui.View):
    """1-10位 / 11-20位 を切り替えるボタン付きView。"""

    def __init__(
        self, country_key: str, division_key: str, current_page: int, max_page: int
    ):
        super().__init__(timeout=600)
        self.country_key = country_key
        self.division_key = division_key
        self.current_page = current_page
        self.max_page = max_page

        self._update_buttons()

    def _update_buttons(self) -> None:
        self.clear_items()
        for p in range(1, self.max_page + 1):
            range_start = (p - 1) * config.ROWS_PER_PAGE + 1
            range_end = p * config.ROWS_PER_PAGE
            self.add_item(
                _PageButton(
                    label=f"{range_start}-{range_end}位",
                    target_page=p,
                    is_current=(self.current_page == p),
                    view_ref=self,
                )
            )

    async def switch_page(
        self, interaction: discord.Interaction, target_page: int
    ) -> None:
        file, content, new_view, error = _build_message_payload(
            self.country_key, self.division_key, target_page
        )

        if error:
            if not interaction.response.is_done():
                await interaction.response.send_message(error, ephemeral=True)
            else:
                await interaction.followup.send(error, ephemeral=True)
            return

        # response.edit_message を使用して1回のAPIコールで画像・テキスト・ボタンを更新
        await interaction.response.edit_message(
            content=content, attachments=[file], view=new_view
        )


class _PageButton(discord.ui.Button):

    def __init__(
        self,
        label: str,
        target_page: int,
        is_current: bool,
        view_ref: LeaderboardView,
    ):
        super().__init__(
            label=label,
            style=(
                discord.ButtonStyle.primary
                if is_current
                else discord.ButtonStyle.secondary
            ),
            disabled=is_current,
        )
        self.target_page = target_page
        self.view_ref = view_ref
        self.last_clicked = 0.0  # 最終押下タイムスタンプ

    async def callback(self, interaction: discord.Interaction) -> None:
        now = time.time()
        cooldown_seconds = 1.5  # クールダウン時間（秒）

        # 連打判定
        if now - self.last_clicked < cooldown_seconds:
            await interaction.response.send_message(
                "⚠️ ボタンの連打防止中です。少し待ってから再度押してください。",
                ephemeral=True,
            )
            return

        self.last_clicked = now
        await self.view_ref.switch_page(interaction, self.target_page)


@bot.event
async def on_ready() -> None:
    logger.info(
        "Botとしてログインしました: %s (ID: %s)",
        bot.user,
        bot.user.id if bot.user else "?",
    )

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching, name=config.BOT_ACTIVITY_TEXT
        )
    )

    # スラッシュコマンドの同期
    try:
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=int(config.DEV_GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info(
                "スラッシュコマンドをギルド限定で同期しました (%d件, guild=%s)",
                len(synced),
                config.DEV_GUILD_ID,
            )
        else:
            synced = await bot.tree.sync()
            logger.info("スラッシュコマンドをグローバル同期しました (%d件)", len(synced))
    except discord.DiscordException:
        logger.exception("スラッシュコマンドの同期に失敗しました。")

    # 初回キャッシュ取得 & 定期更新ループの開始
    if not cache_refresh_loop.is_running():
        await run_initial_refresh()
        cache_refresh_loop.start()
        logger.info("定期キャッシュ更新ループを開始しました（毎時00分・30分, UTC基準）。")


# ------------------------------------------------------------
# スラッシュコマンドのエラーハンドラ（レート制限の秒数をログ出力）
# ------------------------------------------------------------
@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    original = getattr(error, "original", error)

    if isinstance(original, discord.HTTPException) and original.status == 429:
        retry_after = getattr(original, "retry_after", 5.0)
        logger.warning(
            f"【レート制限検知】APIの制限に達しました。あと {retry_after:.2f}"
            f" 秒待つ必要があります。 (パス: {original.path})"
        )

        message = (
            f"⚠️ リクエストが多すぎたため、一時的に制限されています。"
            f"約 **{int(retry_after) + 1}秒後** に再度お試しください。"
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    else:
        logger.exception("スラッシュコマンド実行中にエラーが発生しました。", exc_info=error)
        message = "予期しないエラーが発生しました。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(
    name="speedrun", description="The Hive Gravityカテゴリのリーダーボードを表示します。"
)
@app_commands.describe(
    country="対象プレイヤー（world=全プレイヤー / jp=日本人プレイヤーのみ）",
    division="部門（5maps / nocustom）",
)
@app_commands.choices(country=COUNTRY_CHOICES, division=DIVISION_CHOICES)
@app_commands.checks.cooldown(1, 5.0)  # コマンド全体の連打対策クールダウン（5秒に1回）
async def speedrun_command(
    interaction: discord.Interaction,
    country: app_commands.Choice[str],
    division: app_commands.Choice[str],
) -> None:
    await interaction.response.defer(thinking=True)

    country_key = country.value
    division_key = division.value

    if division_key not in config.DIVISIONS:
        await interaction.followup.send("不明な部門が指定されました。")
        return

    file, content, view, error = _build_message_payload(
        country_key, division_key, page=1
    )

    if error:
        await interaction.followup.send(error)
        return

    if view is not None:
        await interaction.followup.send(content=content, file=file, view=view)
    else:
        await interaction.followup.send(content=content, file=file)


# クールダウン中のエラーメッセージ処理
@speedrun_command.error
async def speedrun_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"このコマンドはクールダウン中です。あと **{error.retry_after:.1f}秒**"
            "後にお試しください。",
            ephemeral=True,
        )


@bot.tree.command(
    name="speedrun_refresh",
    description="（管理者向け）speedrun.comから即時再取得し、キャッシュを更新します。",
)
@app_commands.checks.has_permissions(administrator=True)
async def speedrun_refresh_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        cache_manager.trigger_gas_refresh()
        await cache_manager.refresh_all()
    except GasClientError as e:
        logger.error("手動更新中にGASエラーが発生しました: %s", e)
        await interaction.followup.send(
            f"GAS側でエラーが発生しました: {e}", ephemeral=True
        )
        return
    except Exception:
        logger.exception("手動キャッシュ更新中にエラーが発生しました。")
        await interaction.followup.send(
            "キャッシュ更新中にエラーが発生しました。", ephemeral=True
        )
        return
    await interaction.followup.send(
        "speedrun.comから再取得し、キャッシュを更新しました。", ephemeral=True
    )


@speedrun_refresh_command.error
async def speedrun_refresh_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "このコマンドは管理者のみ使用できます。", ephemeral=True
        )
    else:
        logger.exception(
            "speedrun_refresh コマンドでエラーが発生しました。", exc_info=error
        )
        if interaction.response.is_done():
            await interaction.followup.send(
                "予期しないエラーが発生しました。", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "予期しないエラーが発生しました。", ephemeral=True
            )


def main() -> None:
    if not config.DISCORD_TOKEN:
        logger.error(
            "環境変数 DISCORD_TOKEN が設定されていません。Botを起動できません。"
        )
        sys.exit(1)

    if not config.GAS_WEBAPP_URL:
        logger.error(
            "環境変数 GAS_WEBAPP_URL が設定されていません。Botを起動できません。"
        )
        sys.exit(1)

    if not config.GAS_API_SECRET:
        logger.error(
            "環境変数 GAS_API_SECRET が設定されていません。Botを起動できません。"
        )
        sys.exit(1)

    keep_alive()

    logger.info("%s v%s を起動します。", config.BOT_NAME, config.BOT_VERSION)
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
