from __future__ import annotations
import csv
import random
from math import radians, sin, cos, asin, sqrt
from pathlib import Path
from typing import Dict, List, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

APP_DIR = Path(__file__).parent

app = FastAPI(title="Geoguessr - The Nabo Way")

# ---------- Städer & filer ----------
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

# In-memory cache
PLACES: Dict[str, List[Dict]] = {}             # city -> list of places
PLACE_INDEX: Dict[Tuple[str, int], Dict] = {}  # (city, id) -> place row


def load_city(city: str) -> None:
    """Läs in stadens CSV till minnet (en gång)."""
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
                # hoppa över trasiga rader
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


# ---------- Geo & Poäng ----------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(p1) * cos(p2) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def distance_score_km(distance_km: float) -> int:
    # Straffpoäng: 1.2 km -> 120 p
    return int(round(distance_km * 100))


# ---------- API ----------
@app.get("/api/cities")
def api_cities():
    """Frontenden använder denna för start-menyn."""
    return {"cities": [{"key": k, "center": CITY_CENTERS[k]} for k in DATAFILES.keys()]}

@app.get("/api/round")
def api_round(city: str = Query(..., description="stockholm | goteborg | malmo")):
    """Hämta en slumpad plats för vald stad."""
    c = norm_city(city)
    load_city(c)
    row = random.choice(PLACES[c])
    # Skicka bara det som frontenden behöver
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
def api_guess_map(
    city: str = Query(..., description="stockholm | goteborg | malmo"),
    payload: dict = {},
):
    """Beräkna avstånd + straffpoäng för gissning."""
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
    return {
        "distance_km": round(d_km, 3),
        "score": score,
        "solution": {"lat": row["lat"], "lon": row["lon"]},
    }


# ---------- Frontend & hälsa ----------
@app.get("/", response_class=HTMLResponse)
def index():
    html_path = APP_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))

@app.get("/healthz")
def healthz():
    return {"status": "ok"}
