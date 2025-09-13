# === Standard imports ===
import os, csv, random, datetime, sqlite3, uuid
from pathlib import Path
from contextlib import contextmanager
from math import radians, sin, cos, asin, sqrt

# === FastAPI / Pydantic ===
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, conint

# --- App ---
app = FastAPI(title="Geoguessr - The Nabo Way (API)")

# --- Paths ---
APP_DIR = Path(__file__).parent.resolve()
SQLITE_PATH = APP_DIR / "app.db"
STATIC_DIR = APP_DIR / "static"
IMG_DIR = APP_DIR / "img"
TEMPLATES_DIR = APP_DIR / "templates"
DATA_DIR = APP_DIR / "data"

# --- DB setup ---
DB_URL = os.getenv("DATABASE_URL", "").strip()
USE_PG = bool(DB_URL)
if USE_PG:
    import psycopg  # psycopg v3

def _connect():
    if USE_PG:
        return psycopg.connect(DB_URL, autocommit=True)
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def _db():
    conn = _connect()
    try:
        cur = conn.cursor()
        yield cur
        if not USE_PG:
            conn.commit()
    finally:
        try: cur.close()
        except Exception: pass
        conn.close()

def _exec(sql: str, params: tuple = ()):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        if not USE_PG:
            conn.commit()
        if getattr(cur, "description", None):
            return cur.fetchall()
        return []

def _table_exists(cur, table_name: str) -> bool:
    if USE_PG:
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema='public' AND table_name=%s LIMIT 1
        """, (table_name,))
        return cur.fetchone() is not None
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;", (table_name,))
    return cur.fetchone() is not None

# --- Ping ---
@app.get("/ping")
def ping():
    return {"ok": True, "msg": "pong", "use_pg": USE_PG, "has_db_url": bool(DB_URL)}

# --- Init DB (tillfällig, kör EN gång) ---
@app.post("/__admin/init_db_once")
async def init_db_once(request: Request):
    token_env = os.environ.get("INIT_TOKEN", "")
    token_req = request.headers.get("X-Init-Token") or request.query_params.get("token")
    if not token_env or token_req != token_env:
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)

    with _db() as cur:
        if _table_exists(cur, "games"):
            return {"ok": True, "message": "Tabeller verkar redan finnas."}

    sql_path = APP_DIR / "db" / "create_multiplayer.sql"
    if not sql_path.exists():
        return JSONResponse({"ok": False, "error": f"Saknar {sql_path}"}, status_code=500)

    try:
        sql = sql_path.read_text(encoding="utf-8")
        with _db() as cur:
            cur.execute(sql)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"SQL-exec fel: {e}"}, status_code=500)

    return {"ok": True, "message": "Multiplayer-tabeller skapade."}

# --- Skapa mappar och mounta statiskt ---
STATIC_DIR.mkdir(exist_ok=True)
(IMG_DIR).mkdir(parents=True, exist_ok=True)
(TEMPLATES_DIR).mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/img", StaticFiles(directory=str(IMG_DIR)), name="img")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# --- CSV-data ---
CITY_FILES = {
    "stockholm": DATA_DIR / "places_stockholm.csv",
    "goteborg":  DATA_DIR / "places_goteborg.csv",
    "malmo":     DATA_DIR / "places_malmo.csv",
}
CITY_PLACES: dict[str, list[dict]] = {}

def _to_float(s: str | None):
    try: return float(str(s).replace(",", "."))
    except Exception: return None

def load_places():
    for city, path in CITY_FILES.items():
        rows: list[dict] = []
        if path.exists():
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    lat = _to_float(r.get("lat")); lon = _to_float(r.get("lon"))
                    if lat is None or lon is None: continue
                    street = (r.get("street") or "").strip()
                    postnr = (r.get("postnummer") or "").strip()
                    ort    = (r.get("ort") or "").strip()
                    address_full = ", ".join(p for p in [street, postnr, ort] if p)
                    rows.append({
                        "id": (r.get("id") or "").strip(),
                        "display_name": (r.get("display_name") or "").strip(),
                        "alt_names": (r.get("alt_names") or "").strip(),
                        "street": street, "postnummer": postnr, "ort": ort,
                        "kommun": (r.get("kommun") or "").strip(),
                        "lan": (r.get("lan") or "").strip(),
                        "lat": lat, "lon": lon,
                        "svardighet": (r.get("svardighet") or "").strip(),
                        "address_full": address_full,
                    })
        CITY_PLACES[city] = rows

load_places()

# --- Root (servera /static/index.html) ---
@app.get("/", response_class=HTMLResponse)
def root(_req: Request):
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Index.html saknas i /static</h1>")

# --- Skapa bas-tabeller om de saknas ---
if USE_PG:
    _exec("""
    CREATE TABLE IF NOT EXISTS feedback (
      id          BIGSERIAL PRIMARY KEY,
      created_at  TIMESTAMPTZ NOT NULL,
      name        TEXT,
      email       TEXT,
      category    TEXT,
      message     TEXT NOT NULL
    )""")
    _exec("""
    CREATE TABLE IF NOT EXISTS leaderboard (
      id          BIGSERIAL PRIMARY KEY,
      created_at  TIMESTAMPTZ NOT NULL,
      name        TEXT NOT NULL,
      score       INTEGER NOT NULL,
      rounds      INTEGER NOT NULL,
      city        TEXT
    )""")
else:
    _exec("""
    CREATE TABLE IF NOT EXISTS feedback (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at  TEXT NOT NULL,
      name        TEXT,
      email       TEXT,
      category    TEXT,
      message     TEXT NOT NULL
    )""")
    _exec("""
    CREATE TABLE IF NOT EXISTS leaderboard (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at  TEXT NOT NULL,
      name        TEXT NOT NULL,
      score       INTEGER NOT NULL,
      rounds      INTEGER NOT NULL,
      city        TEXT
    )""")

# --- Feedback API ---
class Feedback(BaseModel):
    name: str | None = ""
    email: str | None = ""
    category: str = "Feedback"
    message: str

@app.post("/api/feedback")
def save_feedback(fb: Feedback):
    msg = (fb.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Tomt meddelande")
    ts = datetime.datetime.utcnow().isoformat(timespec="seconds")
    sql_sqlite = "INSERT INTO feedback (created_at, name, email, category, message) VALUES (?, ?, ?, ?, ?)"
    sql_pg     = "INSERT INTO feedback (created_at, name, email, category, message) VALUES (%s, %s, %s, %s, %s)"
    _exec(sql_pg if USE_PG else sql_sqlite,
          (ts, (fb.name or "").strip(), (fb.email or "").strip(), (fb.category or 'Feedback').strip(), msg))
    return {"ok": True}

@app.get("/api/feedbacks")
def list_feedbacks():
    rows = _exec("SELECT id, created_at, name, email, category, message FROM feedback ORDER BY id DESC")
    if USE_PG:
        items = [{"id": r[0], "created_at": r[1], "name": r[2], "email": r[3], "category": r[4], "message": r[5]} for r in rows]
    else:
        items = [dict(r) for r in rows]
    return {"feedbacks": items}

# --- Leaderboard API ---
class ScoreIn(BaseModel):
    name: str | None = ""
    score: conint(ge=0)
    rounds: conint(ge=1, le=50)
    city: str | None = ""

@app.post("/api/leaderboard")
def save_score(s: ScoreIn):
    ts = datetime.datetime.utcnow().isoformat(timespec="seconds")
    name = (s.name or "").strip() or "Anon"
    city = (s.city or "").strip()
    sql_sqlite = "INSERT INTO leaderboard (created_at, name, score, rounds, city) VALUES (?, ?, ?, ?, ?)"
    sql_pg     = "INSERT INTO leaderboard (created_at, name, score, rounds, city) VALUES (%s, %s, %s, %s, %s)"
    _exec(sql_pg if USE_PG else sql_sqlite, (ts, name, int(s.score), int(s.rounds), city))
    return {"ok": True}

@app.get("/api/leaderboard")
def get_leaderboard(limit: int = 50, order: str = "best", city: str | None = None):
    limit = max(1, min(limit, 200))
    order_sql = "created_at DESC" if order == "latest" else "score ASC"
    params = []
    where_sql = ""
    if city:
        key = city.lower().strip()
        if key not in ("stockholm", "malmo", "goteborg"):
            raise HTTPException(status_code=400, detail=f"Ogiltig stad: {city}")
        where_sql = f"WHERE city = {'%s' if USE_PG else '?'}"
        params.append(key)
    limit_ph = "%s" if USE_PG else "?"
    sql = f"SELECT id, created_at, name, score, rounds, city FROM leaderboard {where_sql} ORDER BY {order_sql} LIMIT {limit_ph}"
    params.append(limit)
    rows = _exec(sql, tuple(params))
    city_map = {"stockholm": "Stockholm", "malmo": "Malmö", "goteborg": "Göteborg"}
    if USE_PG:
        items = [{"id": r[0], "created_at": r[1], "name": r[2], "score": r[3], "rounds": r[4],
                  "city": city_map.get((r[5] or "").lower(), r[5])} for r in rows]
    else:
        items = []
        for r in rows:
            d = dict(r)
            d["city"] = city_map.get((d.get("city") or "").lower(), d.get("city"))
            items.append(d)
    return {"items": items}

# --- Spel: CSV-källor ---
CITY_CENTERS = {
    "stockholm": (59.334, 18.063),
    "goteborg":  (57.707, 11.967),
    "malmo":     (55.605, 13.003),
}
PLACES: dict[str, dict] = {}

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2 - lat1); dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def build_clue(row: dict) -> str:
    street = (row.get("street") or "").strip()
    ort = (row.get("ort") or "").strip()
    dn = (row.get("display_name") or "").strip()
    alt = (row.get("alt_names") or "").strip()
    kommun = (row.get("kommun") or "").strip()
    if street and ort: return f"Nära {street}, {ort}"
    if dn: return dn.split(",")[0]
    if alt: return alt.split(",")[0]
    if kommun: return f"I {kommun}"
    return "Okänd plats"

@app.get("/api/cities")
def api_cities():
    items = []
    for key, rows in CITY_PLACES.items():
        if rows:
            c = CITY_CENTERS.get(key, (62.0, 15.0))
            items.append({"key": key, "center": {"lat": c[0], "lon": c[1]}})
    return {"cities": items}

@app.get("/api/round")
def api_round(city: str):
    key = (city or "").lower().strip()
    rows = CITY_PLACES.get(key) or []
    if not rows:
        raise HTTPException(status_code=400, detail=f"Ingen data för staden: {city!r}")
    row = random.choice(rows)
    lat = float(row["lat"]); lon = float(row["lon"])
    pid = uuid.uuid4().hex
    clue = build_clue(row)
    display = (row.get("display_name") or "").strip() or clue
    street  = (row.get("street") or "").strip()
    address = row.get("address_full") or street or display
    PLACES[pid] = {"lat": lat, "lon": lon, "display_name": display, "clue": clue, "street": street, "address": address, "city": key, "row": row}
    return {"place": {"id": pid, "lat": lat, "lon": lon, "display_name": display, "clue": clue, "street": street, "address": address}}

class MapGuess(BaseModel):
    place_id: str
    lat: float
    lon: float

@app.post("/api/guess/map")
def api_guess_map(guess: MapGuess):
    p = PLACES.get(guess.place_id)
    if not p:
        raise HTTPException(status_code=404, detail="Place not found")
    dist_km = haversine_km(guess.lat, guess.lon, p["lat"], p["lon"])
    score = int(dist_km * 1000 // 1)
    return {
        "distance_km": dist_km,
        "score": score,
        "solution": {"lat": p["lat"], "lon": p["lon"]},
        "place": {
            "id": guess.place_id,
            "display_name": p["display_name"],
            "clue": p["clue"],
            "street": p.get("street",""),
            "address": p.get("address", p.get("street",""))
        }
    }

# =========================
# ===== MULTIPLAYER =======
# =========================
from pydantic import BaseModel
from typing import List, Tuple

# --- helpers ---
def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2 - lat1); dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def _gen_code(n=3) -> str:
    return "".join(random.choice("0123456789") for _ in range(n))

def _unique_code(cur, n=3) -> str:
    while True:
        c = _gen_code(n)
        if USE_PG:
            cur.execute("SELECT 1 FROM games WHERE code=%s LIMIT 1", (c,))
        else:
            cur.execute("SELECT 1 FROM games WHERE code=? LIMIT 1", (c,))
        if not cur.fetchone():
            return c

def pick_random_places(city: str, n: int) -> List[Tuple[str, float, float]]:
    """Returnera n slumpade (place_id,lat,lon) från CSV-datan för given stad."""
    key = (city or "").lower().strip()
    rows = CITY_PLACES.get(key) or []
    if not rows:
        raise HTTPException(status_code=400, detail=f"Ingen data för staden: {city!r}")
    chosen = random.sample(rows, k=min(n, len(rows)))
    out = []
    for r in chosen:
        try:
            lat = float(r["lat"]); lon = float(r["lon"])
        except Exception:
            continue
        pid = (r.get("id") or uuid.uuid4().hex)
        out.append((pid, lat, lon))
    if len(out) < n:
        # toppa upp med duplicering om CSV är för kort
        while len(out) < n:
            out.append(out[len(out) % max(1, len(out))])
    return out[:n]

# --- request models ---
class CreateMatchIn(BaseModel):
    host_name: str
    city: str
    rounds: int = 5  # 1..10 rekommenderat

class JoinMatchIn(BaseModel):
    code: str
    nickname: str

class GuessIn(BaseModel):
    code: str
    nickname: str
    lat: float
    lon: float

# --- endpoints ---

@app.post("/api/match/create")
def api_match_create(payload: CreateMatchIn):
    city = (payload.city or "").lower().strip()
    if city not in CITY_PLACES or not CITY_PLACES[city]:
        raise HTTPException(status_code=400, detail="Ogiltig stad eller ingen CSV-data")
    rounds = max(1, min(int(payload.rounds), 20))
    host = (payload.host_name or "Host").strip()[:40]

    with _db() as cur:
        code = _unique_code(cur, 3)
        if USE_PG:
            cur.execute(
                "INSERT INTO games (code, host_name, city, rounds, status) VALUES (%s,%s,%s,%s,'lobby') RETURNING id",
                (code, host, city, rounds),
            )
            game_id = cur.fetchone()[0]
        else:
            cur.execute(
                "INSERT INTO games (code, host_name, city, rounds, status) VALUES (?,?,?,?, 'lobby')",
                (code, host, city, rounds),
            )
            # SQLite last insert id
            cur.execute("SELECT last_insert_rowid()")
            game_id = cur.fetchone()[0]

        # hosten auto-joinas
        if USE_PG:
            cur.execute(
                "INSERT INTO game_players (game_id,nickname) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (game_id, host),
            )
        else:
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO game_players (game_id,nickname) VALUES (?,?)",
                    (game_id, host),
                )
            except Exception:
                pass

    return {"ok": True, "code": code, "game_id": game_id, "city": city, "rounds": rounds, "status": "lobby"}

@app.post("/api/match/join")
def api_match_join(payload: JoinMatchIn):
    code = (payload.code or "").strip()
    nick = (payload.nickname or "").strip()[:40]
    with _db() as cur:
        if USE_PG:
            cur.execute("SELECT id,status FROM games WHERE code=%s", (code,))
        else:
            cur.execute("SELECT id,status FROM games WHERE code=?", (code,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Spel hittas inte")
        game_id, status = (row[0], row[1])
        if status not in ("lobby", "active"):
            raise HTTPException(status_code=400, detail=f"Spelet är {status}")

        # lägg till spelare
        try:
            if USE_PG:
                cur.execute(
                    "INSERT INTO game_players (game_id,nickname) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (game_id, nick),
                )
            else:
                cur.execute(
                    "INSERT OR IGNORE INTO game_players (game_id,nickname) VALUES (?,?)",
                    (game_id, nick),
                )
        except Exception as e:
            raise HTTPException(status_code=400, detail="Kunde inte ansluta spelare")

    return {"ok": True, "code": code, "nickname": nick}

@app.get("/api/match/lobby")
def api_match_lobby(code: str):
    code = (code or "").strip()
    with _db() as cur:
        if USE_PG:
            cur.execute("SELECT id, city, rounds, status FROM games WHERE code=%s", (code,))
        else:
            cur.execute("SELECT id, city, rounds, status FROM games WHERE code=?", (code,))
        g = cur.fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="Spel hittas inte")
        game_id, city, rounds, status = g[0], g[1], g[2], g[3]

        if USE_PG:
            cur.execute("SELECT nickname FROM game_players WHERE game_id=%s ORDER BY joined_at", (game_id,))
        else:
            cur.execute("SELECT nickname FROM game_players WHERE game_id=? ORDER BY joined_at", (game_id,))
        players = [r[0] for r in cur.fetchall()]

    return {"code": code, "city": city, "rounds": rounds, "status": status, "players": players}

@app.post("/api/match/start")
def api_match_start(code: str):
    code = (code or "").strip()
    with _db() as cur:
        if USE_PG:
            cur.execute("SELECT id, city, rounds, status FROM games WHERE code=%s", (code,))
        else:
            cur.execute("SELECT id, city, rounds, status FROM games WHERE code=?", (code,))
        g = cur.fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="Spel hittas inte")
        game_id, city, rounds, status = g[0], g[1], g[2], g[3]

        # skapa rundor om inte redan finns
        if USE_PG:
            cur.execute("SELECT COUNT(*) FROM game_rounds WHERE game_id=%s", (game_id,))
        else:
            cur.execute("SELECT COUNT(*) FROM game_rounds WHERE game_id=?", (game_id,))
        has = (cur.fetchone() or [0])[0]

        if not has:
            places = pick_random_places(city, rounds)
            for i, (pid, lat, lon) in enumerate(places, start=1):
                if USE_PG:
                    cur.execute(
                        "INSERT INTO game_rounds (game_id, round_no, place_id, lat, lon, started_at) VALUES (%s,%s,%s,%s,%s, CURRENT_TIMESTAMP)",
                        (game_id, i, pid, lat, lon),
                    )
                else:
                    cur.execute(
                        "INSERT INTO game_rounds (game_id, round_no, place_id, lat, lon, started_at) VALUES (?,?,?,?,?, datetime('now'))",
                        (game_id, i, pid, lat, lon),
                    )

        # sätt status active
        if USE_PG:
            cur.execute("UPDATE games SET status='active' WHERE id=%s", (game_id,))
        else:
            cur.execute("UPDATE games SET status='active' WHERE id=?", (game_id,))

    return {"ok": True}

@app.get("/api/match/round")
def api_match_round(code: str, round_no: int):
    code = (code or "").strip()
    with _db() as cur:
        if USE_PG:
            cur.execute("SELECT id, status FROM games WHERE code=%s", (code,))
        else:
            cur.execute("SELECT id, status FROM games WHERE code=?", (code,))
        g = cur.fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="Spel hittas inte")
        game_id, status = g[0], g[1]

        if USE_PG:
            cur.execute("SELECT id, place_id, lat, lon FROM game_rounds WHERE game_id=%s AND round_no=%s",
                        (game_id, int(round_no)))
        else:
            cur.execute("SELECT id, place_id, lat, lon FROM game_rounds WHERE game_id=? AND round_no=?",
                        (game_id, int(round_no)))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Rundan finns inte")
        round_id, place_id, lat, lon = r

    # Vi skickar bara lat/lon efter gissning normalt, men för ditt spel behövs lat/lon på klienten.
    return {"round": {"round_no": int(round_no), "place_id": place_id, "lat": float(lat), "lon": float(lon)}, "status": status}

@app.post("/api/match/guess")
def api_match_guess(payload: GuessIn, round_no: int):
    code = (payload.code or "").strip()
    nick = (payload.nickname or "").strip()

    with _db() as cur:
        # hämta game + player + round
        if USE_PG:
            cur.execute("SELECT id FROM games WHERE code=%s", (code,))
        else:
            cur.execute("SELECT id FROM games WHERE code=?", (code,))
        g = cur.fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="Spel hittas inte")
        game_id = g[0]

        if USE_PG:
            cur.execute("SELECT id FROM game_players WHERE game_id=%s AND nickname=%s", (game_id, nick))
        else:
            cur.execute("SELECT id FROM game_players WHERE game_id=? AND nickname=?", (game_id, nick))
        p = cur.fetchone()
        if not p:
            raise HTTPException(status_code=404, detail="Spelare finns inte i detta spel")
        player_id = p[0]

        if USE_PG:
            cur.execute("SELECT id, lat, lon FROM game_rounds WHERE game_id=%s AND round_no=%s", (game_id, int(round_no)))
        else:
            cur.execute("SELECT id, lat, lon FROM game_rounds WHERE game_id=? AND round_no=?", (game_id, int(round_no)))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Rundan finns inte")
        round_id, lat, lon = r
        dist_m = int(_haversine_km(payload.lat, payload.lon, float(lat), float(lon)) * 1000)

        # spara gissning (en per spelare/runda)
        if USE_PG:
            cur.execute("""
                INSERT INTO guesses (game_id, round_id, player_id, guess_lat, guess_lon, distance_m)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (round_id, player_id) DO UPDATE SET
                  guess_lat=EXCLUDED.guess_lat, guess_lon=EXCLUDED.guess_lon, distance_m=EXCLUDED.distance_m, created_at=CURRENT_TIMESTAMP
            """, (game_id, round_id, player_id, payload.lat, payload.lon, dist_m))
        else:
            # SQLite saknar ON CONFLICT target (partial). Gör UPSERT via REPLACE trick:
            try:
                cur.execute("""
                    INSERT OR REPLACE INTO guesses (id, game_id, round_id, player_id, guess_lat, guess_lon, distance_m, created_at)
                    VALUES (
                      (SELECT id FROM guesses WHERE round_id=? AND player_id=?),
                      ?,?,?,?,?,?, datetime('now')
                    )
                """, (round_id, player_id, game_id, round_id, player_id, payload.lat, payload.lon, dist_m))
            except Exception:
                pass

    return {"ok": True, "distance_m": dist_m}

@app.get("/api/match/round_result")
def api_match_round_result(code: str, round_no: int):
    code = (code or "").strip()
    with _db() as cur:
        if USE_PG:
            cur.execute("SELECT id FROM games WHERE code=%s", (code,))
        else:
            cur.execute("SELECT id FROM games WHERE code=?", (code,))
        g = cur.fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="Spel hittas inte")
        game_id = g[0]

        if USE_PG:
            cur.execute("SELECT id, lat, lon FROM game_rounds WHERE game_id=%s AND round_no=%s",
                        (game_id, int(round_no)))
        else:
            cur.execute("SELECT id, lat, lon FROM game_rounds WHERE game_id=? AND round_no=?",
                        (game_id, int(round_no)))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Rundan finns inte")
        round_id, lat, lon = r

        if USE_PG:
            cur.execute("""
                SELECT gp.nickname, gu.distance_m
                FROM guesses gu
                JOIN game_players gp ON gp.id = gu.player_id
                WHERE gu.round_id=%s
                ORDER BY gu.distance_m ASC
            """, (round_id,))
        else:
            cur.execute("""
                SELECT gp.nickname, gu.distance_m
                FROM guesses gu
                JOIN game_players gp ON gp.id = gu.player_id
                WHERE gu.round_id=?
                ORDER BY gu.distance_m ASC
            """, (round_id,))
        board = [{"nickname": row[0], "distance_m": row[1]} for row in cur.fetchall()]

    return {"round_no": int(round_no), "solution": {"lat": float(lat), "lon": float(lon)}, "leaderboard": board}

@app.get("/api/match/final")
def api_match_final(code: str):
    code = (code or "").strip()
    with _db() as cur:
        if USE_PG:
            cur.execute("SELECT id, rounds FROM games WHERE code=%s", (code,))
        else:
            cur.execute("SELECT id, rounds FROM games WHERE code=?", (code,))
        g = cur.fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="Spel hittas inte")
        game_id, rounds = g[0], g[1]

        # summera distans per spelare
        if USE_PG:
            cur.execute("""
                SELECT gp.nickname, COALESCE(SUM(gu.distance_m), 0) AS total_m, COUNT(gu.id) AS cnt
                FROM game_players gp
                LEFT JOIN guesses gu ON gu.player_id = gp.id AND gu.game_id = %s
                WHERE gp.game_id = %s
                GROUP BY gp.nickname
                ORDER BY total_m ASC
            """, (game_id, game_id))
        else:
            cur.execute("""
                SELECT gp.nickname, IFNULL(SUM(gu.distance_m), 0) AS total_m, COUNT(gu.id) AS cnt
                FROM game_players gp
                LEFT JOIN guesses gu ON gu.player_id = gp.id AND gu.game_id = ?
                WHERE gp.game_id = ?
                GROUP BY gp.nickname
                ORDER BY total_m ASC
            """, (game_id, game_id))
        board = [{"nickname": r[0], "total_m": int(r[1]), "guesses": int(r[2])} for r in cur.fetchall()]

        # markera spelet som finished
        if USE_PG:
            cur.execute("UPDATE games SET status='finished' WHERE id=%s", (game_id,))
        else:
            cur.execute("UPDATE games SET status='finished' WHERE id=?", (game_id,))

    return {"rounds": rounds, "final": board}
