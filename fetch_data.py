"""
Busca os jogos do dia, odds (Bet365 / Betano / Superbet, quando disponíveis)
e estatísticas históricas dos times na API-Football (plano free).

Configuração necessária:
- Variável de ambiente APIFOOTBALL_KEY com sua chave gratuita
  (crie em https://dashboard.api-football.com -> Free plan)

Saída: data.json (consumido pelo index.html)
"""

import os
import json
import time
import datetime
import urllib.request
import urllib.parse

API_KEY = os.environ.get("APIFOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"

# Ligas prioritárias (aparecem primeiro na lista). Não é mais um filtro rígido —
# o script pega TODOS os jogos do dia e só usa isso pra ordenar.
# 71 = Brasileirão A | 72 = Brasileirão B | 73 = Copa do Brasil | 13 = Libertadores
# 11 = Sul-Americana | 253 = MLS | 39 = Premier League | 2 = Champions League
PRIORITY_LEAGUE_IDS = {71, 72, 73, 13, 11, 253, 39, 2, 140, 135, 61, 78}

# Quantidade máxima de jogos processados por dia (cada jogo consome ~3
# requisições: odds + stats dos 2 times). Ajuste conforme sua cota diária
# da API-Football (free = 100 requisições/dia, 10 requisições/minuto).
MAX_MATCHES = 10

# Nomes (parciais, case-insensitive) das casas de apostas que você quer ver
BOOKMAKER_NAMES = ["bet365", "betano", "superbet"]

# Nomes (parciais) dos mercados de odds que você quer capturar
MARKET_KEYWORDS = [
    "match winner", "win", "double chance",
    "goals over/under", "over/under", "both teams",
    "corners", "cards", "fouls", "shots", "handicap"
]

REQUEST_DELAY = 6.5  # segundos entre chamadas (plano free = 10 requisições/minuto)


def api_get(path, params=None, retries=3):
    if not API_KEY:
        raise RuntimeError("Defina a variável de ambiente APIFOOTBALL_KEY antes de rodar.")
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": API_KEY})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
            time.sleep(REQUEST_DELAY)
            if data.get("errors"):
                print(f"  [aviso] {path} -> {data['errors']}")
            return data.get("response", [])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 20 * (attempt + 1)
                print(f"  [rate limit] esperando {wait}s antes de tentar de novo...")
                time.sleep(wait)
                continue
            raise


def get_today_fixtures():
    today = datetime.date.today().isoformat()
    fixtures = api_get("/fixtures", {"date": today})

    def sort_key(f):
        # Ligas prioritárias primeiro, depois ordem cronológica
        is_priority = f["league"]["id"] not in PRIORITY_LEAGUE_IDS
        return (is_priority, f["fixture"]["date"])

    fixtures.sort(key=sort_key)
    return fixtures[:MAX_MATCHES]


def get_odds_for_fixture(fixture_id):
    raw = api_get("/odds", {"fixture": fixture_id})
    result = {}
    for entry in raw:
        for bookmaker in entry.get("bookmakers", []):
            bname = bookmaker["name"]
            if not any(k in bname.lower() for k in BOOKMAKER_NAMES):
                continue
            markets = {}
            for bet in bookmaker.get("bets", []):
                bet_name = bet["name"]
                if not any(k in bet_name.lower() for k in MARKET_KEYWORDS):
                    continue
                markets[bet_name] = [
                    {"outcome": v["value"], "odd": v["odd"]} for v in bet["values"]
                ]
            if markets:
                result[bname] = markets
    return result


def get_team_season_stats(team_id, league_id, season):
    raw = api_get("/teams/statistics", {
        "team": team_id, "league": league_id, "season": season
    })
    if not raw:
        return None
    goals = raw.get("goals", {})
    cards = raw.get("cards", {})
    return {
        "jogos": raw.get("fixtures", {}).get("played", {}).get("total"),
        "gols_marcados_media": goals.get("for", {}).get("average", {}).get("total"),
        "gols_sofridos_media": goals.get("against", {}).get("average", {}).get("total"),
        "cartoes_amarelos_total": sum(
            v.get("total") or 0 for v in cards.get("yellow", {}).values()
        ),
        "cartoes_vermelhos_total": sum(
            v.get("total") or 0 for v in cards.get("red", {}).values()
        ),
    }


def main():
    print("Buscando jogos de hoje...")
    fixtures = get_today_fixtures()
    print(f"  {len(fixtures)} jogos encontrados nas ligas configuradas.")

    matches_out = []
    for f in fixtures:
        fid = f["fixture"]["id"]
        league_id = f["league"]["id"]
        season = f["league"]["season"]
        home = f["teams"]["home"]
        away = f["teams"]["away"]

        print(f"  -> {home['name']} x {away['name']}")

        odds = get_odds_for_fixture(fid)
        home_stats = get_team_season_stats(home["id"], league_id, season)
        away_stats = get_team_season_stats(away["id"], league_id, season)

        matches_out.append({
            "fixture_id": fid,
            "liga": f["league"]["name"],
            "data_hora": f["fixture"]["date"],
            "time_casa": home["name"],
            "time_fora": away["name"],
            "odds": odds,
            "stats_casa": home_stats,
            "stats_fora": away_stats,
        })

    output = {
        "gerado_em": datetime.datetime.now().isoformat(),
        "jogos": matches_out,
    }

    with open("data.json", "w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False, indent=2)

    print(f"\nOK — data.json gerado com {len(matches_out)} jogos.")


if __name__ == "__main__":
    main()
