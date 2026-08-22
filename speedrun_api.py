From __future__ import annotations
import logging, time, requests
from dataclasses import dataclass, field
from typing import Optional
import config

logger = logging.getLogger("speedrun_api")
API_BASE = "https://www.speedrun.com/api/v1"
USER_AGENT = f"{config.BOT_NAME.replace(' ', '-')}/{config.BOT_VERSION}"
REQUEST_TIMEOUT = 15

class SpeedrunAPIError(Exception): pass

@dataclass
class PlayerEntry:
    place: int
    player_name: str
    player_is_guest: bool
    time_str: str
    time_seconds: float
    date_str: str
    platform_name: str
    weblink: str = ""
    country_code: Optional[str] = None

@dataclass
class ResolvedDivision:
    category_id: str
    category_name: str
    variable_id: Optional[str] = None
    value_id: Optional[str] = None
    resolved_at: float = field(default_factory=time.time)

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_resolved_cache: dict[str, ResolvedDivision] = {}

def _get(path: str, params: Optional[dict] = None) -> dict:
    url = f"{API_BASE}{path}"
    logger.info(f"APIリクエスト送信: {url} (params={params})")
    resp = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)

    if resp.status_code != 200:
        logger.error(
            f"API Error! Status: {resp.status_code}, Response: {resp.text}"
        )
        raise SpeedrunAPIError(f"API Error: {resp.status_code}")

    return resp.json()

def resolve_division(division_key: str, force: bool = False) -> ResolvedDivision:
    if not force and division_key in _resolved_cache: return _resolved_cache[division_key]
    div_conf = config.DIVISIONS[division_key]
    data = _get(f"/games/{config.GAME_ID}/categories", params={"embed": "variables"})
    cat = next((c for c in data.get("data", []) if c["name"].lower() == config.CATEGORY_NAME.lower()), None)
    
    var_id, val_id = None, None
    for var in cat.get("variables", {}).get("data", []):
        for vid, vinfo in var.get("values", {}).get("values", {}).items():
            if vinfo["label"].lower() == div_conf["variable_value_name"].lower():
                var_id, val_id = var["id"], vid
                break
    resolved = ResolvedDivision(cat["id"], cat["name"], var_id, val_id)
    _resolved_cache[division_key] = resolved
    return resolved

def fetch_leaderboard(division_key: str, max_entries: int = 150) -> list[PlayerEntry]:
    resolved = resolve_division(division_key)
    # maxパラメータに取得したい件数を指定（最大100〜200程度まで指定可能）
    params = {"embed": "players,platforms", "max": max_entries}
    if resolved.variable_id and resolved.value_id:
        params[f"var-{resolved.variable_id}"] = resolved.value_id
    
    data = _get(f"/leaderboards/{config.GAME_ID}/category/{resolved.category_id}", params=params)
    runs = data.get("data", {}).get("runs", [])
    players_by_id = {p.get("id"): p for p in data.get("data", {}).get("players", {}).get("data", []) if p.get("id")}
    platforms_by_id = {p.get("id"): p for p in data.get("data", {}).get("platforms", {}).get("data", []) if p.get("id")}
    
    entries = []
    for item in runs[:max_entries]:
        run = item.get("run", {})
        p_data = run.get("players", [])[0] if run.get("players") else {}
        p_name, c_code = "Unknown", None
        
        if p_data.get("rel") == "user":
            pid = p_data.get("id")
            p_info = players_by_id.get(pid, {})
            p_name = p_info.get("names", {}).get("international", "Unknown")
            
            # location -> country -> code を安全に取得
            loc = p_info.get("location")
            if isinstance(loc, dict):
                country = loc.get("country")
                if isinstance(country, dict):
                    c_code = country.get("code")

        else:
            p_name = p_data.get("name", "Unknown")
            
        t_sec = run.get("times", {}).get("primary_t", 0.0)
        m, s = divmod(t_sec, 60)
        entries.append(PlayerEntry(
            place=item.get("place", 0),
            player_name=p_name,
            player_is_guest=p_data.get("rel") != "user",
            time_str=f"{int(m)}:{s:06.3f}" if m else f"{s:.3f}",
            time_seconds=t_sec,
            date_str=run.get("date") or "----/--/--",
            platform_name=platforms_by_id.get(run.get("system", {}).get("platform"), {}).get("name", "-"),
            country_code=c_code
        ))
    return entries
