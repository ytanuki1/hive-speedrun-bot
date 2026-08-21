from speedrun_api import PlayerEntry, fetch_leaderboard, SpeedrunAPIError as GasClientError
import datetime

def fetch_division_data(division_key: str):
    entries = fetch_leaderboard(division_key, 60)
    return entries, datetime.datetime.now(datetime.timezone.utc).isoformat()

def refresh_division(division_key=None):
    pass