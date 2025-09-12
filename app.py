from __future__ import annotations

import csv, os, random, datetime, sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# =========================================================
# DB settings (Render: Postgres via DATABASE_URL, annars SQLite)
# =========================================================
DB_URL = os.getenv("DATABASE_URL", "").strip()
USE_PG = DB_URL != ""  # True = Postgres, False = SQLite

# Paths
APP_DIR = Path(__file__).parent.resolve()
STATIC_DIR = APP_DIR / "static"
IMG_DIR = APP_DIR / "img"
TEMPLATES_DIR = APP_DIR / "templates"
SQLITE_PATH = APP_DIR / "app.db"


# ===== Platser från CSV (riktiga speldata) =====
# ===== Platser från CSV (riktiga speldata) =====
import csv

DATA_DIR = APP_DIR / "data"
CITY_FILES = {
    "stockholm": DATA_DIR / "places_stockholm.csv",
    "goteborg":  DATA_DIR / "places_goteborg.csv",
    "malmo":     DATA_DIR / "places_malmo.csv",
}

CITY_PLACES: dict[str, list[dict]] = {}

def _to_float(s: str | None):
    try:
        return float(str(s).replace(",", "."))
    except Exception:
        return None

def load_places():
    for city, path in CITY_FILES.items():
        rows: list[dict] = []
        if path.exists():
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    lat = _to_float(r.get("lat"))
                    lon = _to_float(r.get("lon"))
                    if lat is None or lon is None:
                        continue
                    street = (r.get("street") or "").strip()
                    postnr = (r.get("postnummer") or "").strip()
                    ort    = (r.get("ort") or "").strip()
                    address_full = ", ".join(p for p in [street, postnr, ort] if p)

                    rows.append({
                        "id": (r.get("id") or "").strip(),
                        "display_name": (r.get("display_name") or "").strip(),
                        "alt_names": (r.get("alt_names") or "").strip(),
                        "street": street,
                        "postnummer": postnr,
                        "ort": ort,
                        "kommun": (r.get("kommun") or "").strip(),
                        "lan": (r.get("lan") or "").strip(),
                        "lat": lat,
                        "lon": lon,
                        "svardighet": (r.get("svardighet") or "").strip(),
                        "address_full": address_full,   # ⬅️ viktig
                    })
        CITY_PLACES[city] = rows

# Ladda CSV:erna vid start
load_places()


# App
app = FastAPI(title="Geoguessr - The Nabo Way")

# Skapa mappar lokalt om de saknas
STATIC_DIR.mkdir(exist_ok=True)
(STATIC_DIR / "img").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "fonts").mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

# Mounta statiska mappar
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/img", StaticFiles(directory=str(IMG_DIR)), name="img")

# Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# =========================================================
# DB helpers
# =========================================================
try:
    if USE_PG:
        import psycopg
except Exception:
    USE_PG = False

SQLITE_PATH = APP_DIR / "app.db"

def _connect():
    if USE_PG:
        return psycopg.connect(DB_URL, autocommit=True)
    else:
        conn = sqlite3.connect(str(SQLITE_PATH))
        conn.row_factory = sqlite3.Row
        return conn

def _exec(sql: str, params: tuple = ()):
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        if not USE_PG:
            conn.commit()
        # Endast SELECT har resultatschema
        if getattr(cur, "description", None):
            return cur.fetchall()
        return []



# ========= Feedback table =========
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

# ========= Leaderboard table =========
if USE_PG:
    _exec("""
    CREATE TABLE IF NOT EXISTS leaderboard (
      id          BIGSERIAL PRIMARY KEY,
      created_at  TIMESTAMPTZ NOT NULL,
      name        TEXT NOT NULL,
      score       INTEGER NOT NULL,     -- lägre = bättre
      rounds      INTEGER NOT NULL,
      city        TEXT
    )""")
else:
    _exec("""
    CREATE TABLE IF NOT EXISTS leaderboard (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at  TEXT NOT NULL,
      name        TEXT NOT NULL,
      score       INTEGER NOT NULL,     -- lägre = bättre
      rounds      INTEGER NOT NULL,
      city        TEXT
    )""")



# =========================================================
# Modeller
# =========================================================
class Feedback(BaseModel):
    name: str | None = ""
    email: str | None = ""
    category: str = "Feedback"
    message: str

@app.post("/api/feedback")
async def save_feedback(fb: Feedback):
    msg = (fb.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Tomt meddelande")
    ts = datetime.datetime.utcnow().isoformat(timespec="seconds")
    _exec(
        "INSERT INTO feedback (created_at, name, email, category, message) VALUES (?, ?, ?, ?, ?)"
        if not USE_PG else
        "INSERT INTO feedback (created_at, name, email, category, message) VALUES (%s, %s, %s, %s, %s)",
        (ts, (fb.name or "").strip(), (fb.email or "").strip(), (fb.category or "Feedback").strip(), msg)
    )
    return {"ok": True}


@app.get("/api/feedbacks")
def list_feedbacks():
    rows = _exec("SELECT id, created_at, name, email, category, message FROM feedback ORDER BY id DESC")
    out = []
    if USE_PG:
        for r in rows:
            out.append({
                "id": r[0], "created_at": r[1], "name": r[2],
                "email": r[3], "category": r[4], "message": r[5]
            })
    else:
        for r in rows:
            out.append(dict(r))
    return {"feedbacks": out}

# Debug endpoint
@app.get("/debug/static")
def debug_static():
    return {"static_dir": str(STATIC_DIR), "templates_dir": str(TEMPLATES_DIR)}

# Root – servera index.html
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Index.html saknas i /static</h1>")

# ===================== Simple game endpoints (stubbar för test) =====================

from math import radians, sin, cos, asin, sqrt
import uuid, random

# stad → centrum (lat, lon)  (kan bytas till dina riktiga centers)
CITY_CENTERS = {
    "stockholm": (59.334, 18.063),
    "goteborg":  (57.707, 11.967),
    "malmo":     (55.605, 13.003),
}

from pydantic import BaseModel, conint
import sys, traceback

class ScoreIn(BaseModel):
    name: str | None = ""
    score: conint(ge=0)
    rounds: conint(ge=1, le=50)
    city: str | None = ""

@app.post("/api/leaderboard")
def save_score(s: ScoreIn):
    try:
        ts = datetime.datetime.utcnow().isoformat(timespec="seconds")
        name = (s.name or "").strip() or "Anon"
        city = (s.city or "").strip()
        score = int(s.score)
        rounds = int(s.rounds)

        sql_sqlite = "INSERT INTO leaderboard (created_at, name, score, rounds, city) VALUES (?, ?, ?, ?, ?)"
        sql_pg     = "INSERT INTO leaderboard (created_at, name, score, rounds, city) VALUES (%s, %s, %s, %s, %s)"
        _exec(sql_pg if USE_PG else sql_sqlite, (ts, name, score, rounds, city))
        return {"ok": True}
    except Exception as e:
        print("ERROR save_score:", repr(e))
        raise HTTPException(status_code=500, detail="DB insert failed")


@app.get("/api/leaderboard")
def get_leaderboard(limit: int = 50, order: str = "best", city: str | None = None):
    """
    Hämta leaderboard med toppresultat.
    - limit: max antal rader (default 50)
    - order: "best" = sortera på score, "latest" = sortera på senaste spel
    - city: filtrera på stad (stockholm, malmo, goteborg)
    """
    limit = max(1, min(limit, 200))

    if order == "latest":
        order_sql = "created_at DESC"
    else:
        order_sql = "score ASC"   # lägre score = bättre

    params: list = []
    where_sql = ""
    if city:
        key = city.lower().strip()
        if key not in ("stockholm", "malmo", "goteborg"):
            raise HTTPException(status_code=400, detail=f"Ogiltig stad: {city}")
        where_sql = "WHERE city = ?"
        params.append(key)

    sql = f"""
        SELECT id, created_at, name, score, rounds, city
        FROM leaderboard
        {where_sql}
        ORDER BY {order_sql}
        LIMIT ?
    """
    params.append(limit)
    rows = _exec(sql, tuple(params))

    out = []
    if USE_PG:
        for r in rows:
            out.append({
                "id": r[0], "created_at": r[1],
                "name": r[2], "score": r[3],
                "rounds": r[4], "city": r[5],
            })
    else:
        for r in rows:
            out.append(dict(r))

    return {"items": out}






# minneskarta: place_id -> {lat,lon,display_name,city}
PLACES: dict[str, dict] = {}

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2-lat1)
    dlon = radians(lon2-lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    c = 2*asin(sqrt(a))
    return R*c

def random_point_near(lat, lon, radius_km=6.0):
    # enkel "cirkel" i km runt centrum
    # 1 grad lat ≈ 111 km. justera lon med cos(lat)
    dx = (random.random()*2 - 1) * radius_km
    dy = (random.random()*2 - 1) * radius_km
    dlat = dy / 111.0
    dlon = dx / (111.0 * max(0.2, cos(radians(lat))))  # skydda nära poler
    return lat + dlat, lon + dlon

@app.get("/api/cities")
def api_cities():
    return {"cities":[{"key":k,"center":{"lat":v[0],"lon":v[1]}} for k,v in CITY_CENTERS.items()]}

@app.get("/api/round")
def api_round(city: str):
    """
    Returnerar en plats från CSV för given stad.
    Ledtråd = display_name (precis som i filen).
    Skickar även street + address_full om de finns.
    Faller tillbaka snällt om något saknas.
    """
    key = (city or "").lower().strip()
    rows = CITY_PLACES.get(key) or []
    if not rows:
        raise HTTPException(status_code=400, detail=f"Ingen data för staden: {city!r}")

    # Slumpa en rad från CSV
    row = random.choice(rows)

    # Plocka fält robust
    try:
        lat = float(row["lat"])
        lon = float(row["lon"])
    except Exception:
        raise HTTPException(status_code=500, detail="Trasig rad i CSV (lat/lon)")

    display = (row.get("display_name") or "").strip() or "Okänd plats"
    street  = (row.get("street") or "").strip()
    postnr  = (row.get("postnummer") or "").strip()
    ort     = (row.get("ort") or "").strip()
    address = row.get("address_full") or ", ".join(p for p in [street, postnr, ort] if p) or street or display

    pid = uuid.uuid4().hex

    # Spara facit i minnet för /api/guess/map
    PLACES[pid] = {
        "lat": lat, "lon": lon,
        "display_name": display,   # <- Ledtråd ska vara display_name
        "clue": display,           # <- clue = display_name
        "street": street,
        "address": address,
        "city": key,
        "row": row,
    }

    return {
        "place": {
            "id": pid,
            "lat": lat, "lon": lon,
            "display_name": display,
            "clue": display,       # <- frontend kan läsa place.clue
            "street": street,
            "address": address
        }
    }



class MapGuess(BaseModel):
    place_id: str
    lat: float
    lon: float

@app.post("/api/guess/map")
def api_guess_map(guess: MapGuess, city: str = ""):
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
            "street": p.get("street", ""),
            "address": p.get("address", p.get("street", "")),
        }
    }



# =========================================================
# Spel-endpoints (enkla stubbar så spelet funkar)
# =========================================================
from math import radians, sin, cos, asin, sqrt
import uuid, random

CITY_CENTERS = {
    "stockholm": (59.334, 18.063),
    "goteborg":  (57.707, 11.967),
    "malmo":     (55.605, 13.003),
}

PLACES: dict[str, dict] = {}

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def random_point_near(lat, lon, radius_km=6.0):
    dx = (random.random()*2 - 1) * radius_km
    dy = (random.random()*2 - 1) * radius_km
    dlat = dy / 111.0
    dlon = dx / (111.0 * max(0.2, cos(radians(lat))))
    return lat + dlat, lon + dlon

@app.get("/api/cities")
def api_cities():
    return {"cities":[{"key":k,"center":{"lat":v[0],"lon":v[1]}} for k,v in CITY_CENTERS.items()]}

@app.get("/api/round")
def api_round(city: str):
    key = city.lower().strip()
    if key not in CITY_PLACES or not CITY_PLACES[key]:
        raise HTTPException(status_code=400, detail="Ingen data för staden")

    row = random.choice(CITY_PLACES[key])
    lat = row["lat"]; lon = row["lon"]

    pid = uuid.uuid4().hex
    clue = build_clue(row)
    display = row.get("display_name") or clue
    street  = row.get("street") or ""
    address = row.get("address_full") or street or display  # säkra fallback

    PLACES[pid] = {
        "lat": lat, "lon": lon,
        "display_name": display,
        "clue": clue,
        "street": street,
        "address": address,
        "city": key,
        "row": row,
    }

    return {
        "place": {
            "id": pid,
            "lat": lat, "lon": lon,
            "display_name": display,
            "clue": clue,
            "street": street,
            "address": address
        }
    }


class MapGuess(BaseModel):
    place_id: str
    lat: float
    lon: float

@app.post("/api/guess/map")
def api_guess_map(guess: MapGuess, city: str = ""):
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
            "street": p.get("street", ""),
            "address": p.get("address", p.get("street",""))
        }
    }



# =========================================================
# Spel-endpoints (CSV-källor)
# =========================================================
from math import radians, sin, cos, asin, sqrt
import uuid, random

# Stad -> center för mapview (kan justeras)
CITY_CENTERS = {
    "stockholm": (59.334, 18.063),
    "goteborg":  (57.707, 11.967),
    "malmo":     (55.605, 13.003),
}

# Minneskarta: place_id -> facit
PLACES: dict[str, dict] = {}

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def build_clue(row: dict) -> str:
    """
    Bygg en kort ledtråd av CSV-fält:
    - street + ort, annars display_name, annars alt_names, annars kommun
    """
    street = (row.get("street") or "").strip()
    ort = (row.get("ort") or "").strip()
    dn = (row.get("display_name") or "").strip()
    alt = (row.get("alt_names") or "").strip()
    kommun = (row.get("kommun") or "").strip()

    if street and ort:
        return f"Nära {street}, {ort}"
    if dn:
        return dn.split(",")[0]
    if alt:
        return alt.split(",")[0]
    if kommun:
        return f"I {kommun}"
    return "Okänd plats"

@app.get("/api/cities")
def api_cities():
    # Visa bara städer som faktiskt har data
    items = []
    for key, rows in CITY_PLACES.items():
        if rows:
            c = CITY_CENTERS.get(key, (62.0, 15.0))
            items.append({"key": key, "center": {"lat": c[0], "lon": c[1]}})
    return {"cities": items}

@app.get("/api/round")
def api_round(city: str):
    key = city.lower().strip()
    if key not in CITY_PLACES or not CITY_PLACES[key]:
        raise HTTPException(status_code=400, detail="Ingen data för staden")

    row = random.choice(CITY_PLACES[key])
    lat = row["lat"]; lon = row["lon"]

    pid = uuid.uuid4().hex
    clue = build_clue(row)
    display = row.get("display_name") or clue
    street = (row.get("street") or "").strip()

    PLACES[pid] = {
        "lat": lat, "lon": lon,
        "display_name": display,
        "clue": clue,
        "street": street,          # ⬅️ spara street
        "city": key,
        "row": row,
    }

    return {
        "place": {
            "id": pid,
            "lat": lat, "lon": lon,
            "display_name": display,
            "clue": clue,
            "street": street       # ⬅️ skicka street
        }
    }


class MapGuess(BaseModel):
    place_id: str
    lat: float
    lon: float

