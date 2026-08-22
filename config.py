import os

BOT_NAME = "Hive Speedrun Leaderboard"
BOT_VERSION = "1.0.0"
BOT_ACTIVITY_TEXT = "/speedrun | Gravity Leaderboard"

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
DEV_GUILD_ID = os.environ.get("DEV_GUILD_ID", "")

# GAS環境変数は不要になりましたが、互換性のため残しています
GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL", "")
GAS_API_SECRET = os.environ.get("GAS_API_SECRET", "")

DIVISIONS = {
    "5maps": {
        "label": "5 Maps",
        "background_url": "https://i.imgur.com/1gY2pA4.png",
        "variable_value_name": "5 maps",
    },
    "nocustom": {
        "label": "5 Maps No Custom Server",
        "background_url": "https://i.imgur.com/xfFhLxa.png",
        "variable_value_name": "5 maps (no custom server)",
    },
}

GAME_NAME = "The Hive"
GAME_ID = "hive"
CATEGORY_NAME = "Gravity"

_jp_whitelist_raw = os.environ.get("JP_WHITELIST", "tanukiYy,AmonHive,AlmondCellar,Suriipu,StoodBird84586,MintGamesYT,maikuragenzin,spring861,TouTubeTomaTV,iroha0515")
JP_WHITELIST = {name.strip().lower() for name in _jp_whitelist_raw.split(",") if name.strip()}
JP_COUNTRY_CODE = "JP"

CACHE_DIR = os.environ.get("CACHE_DIR", "cache")
CACHE_TTL_MINUTES = 30

FONT_DIR = os.environ.get("FONT_DIR", "fonts")
FONT_MOJANGLES = os.path.join(FONT_DIR, "Mojangles.ttf")
FONT_UNIFONT = os.path.join(FONT_DIR, "Unifont.ttf")

IMAGE_WIDTH = 1010
ROW_HEIGHT = 68
HEADER_HEIGHT = 170
FOOTER_HEIGHT = 30
PADDING = 14
ROWS_PER_PAGE = 10
MAX_ROWS_WORLD_DISPLAY = 40
MAX_ROWS_JP_DISPLAY = 20

LOGO_URL = os.environ.get("LOGO_URL", "https://playhive.com/_next/static/media/Hive.9ce7fa58.png")
LOGO_HEIGHT = 34
BACKGROUND_BLUR_RADIUS = 4
BACKGROUND_DARKEN_ALPHA = 130

COLORS = {
    "panel_bg": (14, 18, 28, 235),
    "panel_border": (40, 46, 58, 255),
    "row_bg_a": (30, 38, 52, 200),
    "row_bg_b": (22, 28, 40, 200),
    "header_tab_bg": (18, 22, 32, 255),
    "header_tab_border": (60, 66, 80, 255),
    "title_cyan": (85, 210, 235, 255),
    "title_green": (85, 220, 100, 255),
    "col_header_pos": (240, 140, 130, 255),
    "col_header_white": (255, 255, 255, 255),
    "col_header_green": (95, 220, 105, 255),
    "col_header_red": (225, 90, 90, 255),
    "text_white": (240, 240, 240, 255),
    "rank_gold": (255, 215, 60, 255),
    "rank_silver": (200, 205, 210, 255),
    "rank_bronze": (190, 120, 70, 255),
    "rank_other": (235, 140, 140, 255),
    "player_name": (230, 230, 235, 255),
    "time_lightgreen": (150, 230, 90, 255),
    "date_darkgreen": (60, 140, 75, 255),
    "platform_red": (215, 80, 80, 255),
    "shadow": (0, 0, 0, 160),
}
