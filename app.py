from __future__ import annotations

import csv, os, re, random, datetime, threading, sqlite3
from math import radians, sin, cos, asin, sqrt
from pathlib import Path
from typing import Dict, List, Tuple

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, constr, conint

# =========================================================
# DB settings (env variabel)
# =========================================================
DB_URL = os.getenv("DATABASE_URL", "").strip()
USE_PG = DB_URL != ""  # True = Postgres, False = SQLite

# =========================================================
# Paths & app
# =========================================================
APP_DIR = Path(__file__).parent.resolve()

STATIC_DIR = APP_DIR / "static"
IMG_DIR = APP_DIR / "img"             # fallback: om bilder ligger här
TEMPLATES_DIR = APP_DIR / "templates"

app = FastAPI(title="Geoguessr - The Nabo Way")

# Skapa mappar lokalt om de saknas
STATIC_DIR.mkdir(exist_ok=True)
(STATIC_DIR / "img").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "fonts").mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(exist_ok=True)  # fallback
TEMPLATES_DIR.mkdir(exist_ok=True)

# Mounta /static (primärt)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mounta även /img → ./img (fallback för dina gamla filer)
app.mount("/img", StaticFiles(directory=str(IMG_DIR)), name="img")

# Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Debug endpoint för att kolla mapparna
@app.get("/debug/static")
def debug_static():
    return {
        "cwd": str(APP_DIR),
        "static_dir": str(STATIC_DIR.resolve()),
        "img_dir": str(IMG_DIR.resolve()),
        "templates_dir": str(TEMPLATES_DIR.resolve()),
        "has_stockholm_static": (STATIC_DIR / "img" / "stockholm.png").exists(),
        "has_stockholm_img": (IMG_DIR / "stockholm.png").exists(),
    }

# =========================================================
# Leaderboard – Postgres i prod, SQLite lokalt
# =========================================================
_db_lock = threading.Lock()
DB_PATH = str(APP_DIR / "leaderboard.sqlite3")  # fallback

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row

    def _pg_exec(sql: str, args: tuple = ()):
        with _db_lock:
            with psycopg.connect(DB_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, args)
                conn.commit()

    def _pg_query(sql: str, args: tuple = ()):
        with _db_lock:
            with psycopg.connect(DB_URL) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(sql, args)
                    return cur.fetchall()

    def _ensure_table():
        _pg_exec("""
        CREATE TABLE IF NOT EXISTS leaderboard (
          id BIGSERIAL PRIMARY KEY,
          name TEXT NOT NULL,
          score INTEGER NOT NULL,
          rounds INTEGER NOT NULL,
          city TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
    _ensure_table()

else:
    def _sq_exec(sql: str, args: tuple = ()):
        with _db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(sql, args)
                conn.commit()

    def _sq_query(sql: str, args: tuple = ()):
        with _db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(sql, args)
                return [dict(r) for r in cur.fetchall()]

    def _ensure_table():
        _sq_exec("""
        CREATE TABLE IF NOT EXISTS leaderboard (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          score INTEGER NOT NULL,
          rounds INTEGER NOT NULL,
          city TEXT,
          created_at TEXT NOT NULL
        )
        """)
    _ensure_table()

def db_exec(sql: str, args: tuple = ()):
    return _pg_exec(sql, args) if USE_PG else _sq_exec(sql, args)

def db_query(sql: str, args: tuple = ()):
    return _pg_query(sql, args) if USE_PG else _sq_query(sql, args)

class ScoreIn(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=40)
    score: conint(ge=0, le=10_000_000)
    rounds: conint(ge=1, le=100)
    city: str | None = None

@app.post("/api/leaderboard")
def api_leaderboard_post(payload: ScoreIn):
    if USE_PG:
        db_exec(
            "INSERT INTO leaderboard(name,score,rounds,city) VALUES (%s,%s,%s,%s)",
            (payload.name, int(payload.score), int(payload.rounds), payload.city),
        )
    else:
        now = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
        db_exec(
            "INSERT INTO leaderboard(name,score,rounds,city,created_at) VALUES (?,?,?,?,?)",
            (payload.name, int(payload.score), int(payload.rounds), payload.city, now),
        )
    return {"ok": True}

@app.get("/api/leaderboard")
def api_leaderboard_get(limit: int = 50, order: str = "best"):
    order_sql = "score ASC, created_at ASC" if order == "best" else "created_at DESC"
    if USE_PG:
        rows = db_query(
            f"SELECT name,score,rounds,city,created_at FROM leaderboard "
            f"ORDER BY {order_sql} LIMIT %s",
            (int(limit),),
        )
    else:
        rows = db_query(
            f"SELECT name,score,rounds,city,created_at FROM leaderboard "
            f"ORDER BY {order_sql} LIMIT ?",
            (int(limit),),
        )
    return {"items": rows, "order": order}

# =========================================================
# Städer & CSV-laddning
# =========================================================
def norm_city(s: str) -> str:
    s = (s or "").lower()
    for a, b in {"ö": "o", "ä": "a", "å": "a", " ": ""}.items():
        s = s.replace(a, b)
    return s

DATAFILES: Dict[str, Path] = {
    "stockholm": APP_DIR / "places_stockholm.csv",
    "goteborg":  APP_DIR / "places_goteborg.csv",
    "malmo":     APP_DIR / "places_malmo.csv",
}

CITY_CENTERS: Dict[str, Tuple[float, float]] = {
    "stockholm": (59.334, 18.063),
    "goteborg":  (57.707, 11.967),
    "malmo":     (55.605, 13.003),
}

REQUIRED = [
    "id","display_name","alt_names","street","postnummer","ort","kommun","lan","lat","lon","svardighet"
]

PLACES: Dict[str, List[Dict]] = {}             # city -> list of places
PLACE_INDEX: Dict[Tuple[str, int], Dict] = {}  # (city, id) -> place row

def load_city(city: str) -> None:
    city = norm_city(city)
    if city in PLACES:
        return
    csv_path = DATAFILES.get(city)
    if csv_path is None:
        raise HTTPException(400, detail=f"Ogiltig stad: {city}")
    if not csv_path.exists():
        raise HTTPException(400, detail=f"Saknar fil: {csv_path.name} (lägg den bredvid app.py)")

    rows: List[Dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        cols = [c.strip() for c in (rdr.fieldnames or [])]
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            raise HTTPException(500, detail=f"Fel kolumner i {csv_path.name}, saknas: {missing}")

        for r in rdr:
            try:
                rid = int((r.get("id") or "").strip())
                lat = float((r.get("lat") or "").strip())
                lon = float((r.get("lon") or "").strip())
            except Exception:
                continue

            item = {
                "id": rid,
                "display_name": (r.get("display_name") or "").strip(),
                "alt_names": (r.get("alt_names") or "").strip(),
                "street": (r.get("street") or "").strip(),
                "postnummer": (r.get("postnummer") or "").replace(" ", "").strip(),
                "ort": (r.get("ort") or "").strip(),
                "kommun": (r.get("kommun") or "").strip(),
                "lan": (r.get("lan") or "").strip(),
                "lat": lat,
                "lon": lon,
                "svardighet": int((r.get("svardighet") or 2)),
            }
            rows.append(item)
            PLACE_INDEX[(city, rid)] = item

    if not rows:
        raise HTTPException(500, detail=f"Inga giltiga rader i {csv_path.name}")

    PLACES[city] = rows

# =========================================================
# Geo & poäng
# =========================================================
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(p1) * cos(p2) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def distance_score_km(distance_km: float) -> int:
    return int(round(distance_km * 100))  # 1.2 km -> 120 p (lägre är bättre)

# =========================================================
# API (spel)
# =========================================================
@app.get("/api/cities")
def api_cities():
    return {"cities": [{"key": k, "center": CITY_CENTERS[k]} for k in DATAFILES.keys()]}

@app.get("/api/round")
def api_round(city: str = Query(..., description="stockholm | goteborg | malmo")):
    c = norm_city(city)
    load_city(c)
    row = random.choice(PLACES[c])
    return {"place": {
        "id": row["id"],
        "display_name": row["display_name"],
        "street": row["street"],
        "postnummer": row["postnummer"],
        "ort": row["ort"],
        "kommun": row["kommun"],
        "lan": row["lan"],
        "lat": row["lat"],
        "lon": row["lon"],
    }}

@app.post("/api/guess/map")
def api_guess_map(city: str = Query(..., description="stockholm | goteborg | malmo"), payload: dict = {}):
    c = norm_city(city)
    load_city(c)
    try:
        pid = int(payload.get("place_id"))
        glat = float(payload.get("lat"))
        glon = float(payload.get("lon"))
    except Exception:
        raise HTTPException(400, detail="place_id, lat, lon måste finnas och vara numeriska")

    row = PLACE_INDEX.get((c, pid))
    if not row:
        raise HTTPException(400, detail="Ogiltigt place_id för staden")

    d_km = haversine_km(glat, glon, row["lat"], row["lon"])
    score = distance_score_km(d_km)
    return {"distance_km": round(d_km, 3), "score": score,
            "solution": {"lat": row["lat"], "lon": row["lon"]}}

# =========================================================
# Frontend: rendera index.html via templates/
# =========================================================
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
