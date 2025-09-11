from __future__ import annotations
import csv
import random
from math import radians, sin, cos, asin, sqrt
from pathlib import Path
from typing import Dict, List, Tuple

import streamlit as st
from streamlit_folium import st_folium
import folium

APP_DIR = Path(__file__).parent

# =================== Brand / Tema ===================
BRAND_GREEN = "#0f7b6c"   # byt vid behov
BG_LIGHT     = "#f7f8f5"  # ljus bakgrundston

st.set_page_config(page_title="Geoguessr - The Nabo Way", page_icon="🧭", layout="wide")
st.markdown(
    f"""
    <style>
      /* knappar */
      .stButton > button {{ background:{BRAND_GREEN}; color:white; border:0; border-radius:10px; }}
      .stButton > button:hover {{ filter:brightness(0.95); }}
      /* högerspalt rubrikfärg */
      h1, h2, h3, h4 {{ color: {BRAND_GREEN}; }}
      /* sidopanel bakgrund */
      section[data-testid="stSidebar"] {{ background:{BG_LIGHT}; }}
      /* info/alert-kort rundade hörn */
      .stAlert {{ border-radius:12px; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# =================== Städer & filer ===================
DATAFILES: Dict[str, Path] = {
    "Stockholm": APP_DIR / "places_stockholm.csv",
    "Göteborg":  APP_DIR / "places_goteborg.csv",
    "Malmö":     APP_DIR / "places_malmo.csv",
}

CITY_CENTERS: Dict[str, Tuple[float, float]] = {
    "Stockholm": (59.334, 18.063),
    "Göteborg":  (57.707, 11.967),
    "Malmö":     (55.605, 13.003),
}

REQUIRED = [
    "id","display_name","alt_names","street","postnummer","ort","kommun","lan","lat","lon","svardighet"
]

# =================== Laddning & cache ===================
@st.cache_data
def load_places(csv_path: Path) -> List[Dict]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Saknar fil: {csv_path.name}")
    rows: List[Dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        cols = [c.strip() for c in (rdr.fieldnames or [])]
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            raise ValueError(f"Fel kolumner i {csv_path.name}, saknas: {missing}")
        for r in rdr:
            try:
                rows.append({
                    "id": int((r.get("id") or "").strip()),
                    "display_name": (r.get("display_name") or "").strip(),
                    "alt_names": (r.get("alt_names") or "").strip(),
                    "street": (r.get("street") or "").strip(),
                    "postnummer": (r.get("postnummer") or "").replace(" ", "").strip(),
                    "ort": (r.get("ort") or "").strip(),
                    "kommun": (r.get("kommun") or "").strip(),
                    "lan": (r.get("lan") or "").strip(),
                    "lat": float((r.get("lat") or "").strip()),
                    "lon": float((r.get("lon") or "").strip()),
                    "svardighet": int((r.get("svardighet") or 2)),
                })
            except Exception:
                continue
    if not rows:
        raise ValueError(f"Inga giltiga rader i {csv_path.name}")
    return rows

# =================== Geo & Poäng ===================
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1); dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(p1) * cos(p2) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def distance_score_km(distance_km: float) -> int:
    return int(round(distance_km * 100))  # 1.2 km -> 120 p

# =================== State init ===================
if "city" not in st.session_state: st.session_state.city = "Stockholm"
if "place" not in st.session_state: st.session_state.place = None        # dict
if "guess" not in st.session_state: st.session_state.guess = None        # (lat, lon)
if "clue_step" not in st.session_state: st.session_state.clue_step = 0   # hur många ledtrådar visas

# =================== Sidebar: alltid synlig ledtrådsbox ===================
with st.sidebar:
    st.header("📦 Instruktioner")
    st.markdown(
        "- Välj stad\n"
        "- Klicka **Ny plats**\n"
        "- Klicka på kartan för gissning\n"
        "- Klicka **Ny ledtråd** vid behov\n"
        "- **Gissa!** för poäng"
    )
    st.divider()
    st.subheader("🔎 Ledtråd")
    if st.session_state.place:
        p = st.session_state.place
        # Definiera ordning för ledtrådar (visa INTE display_name förrän efter gissning)
        clues = [
            ("Ort", p["ort"]),
            ("Kommun", p["kommun"]),
            ("Län", p["lan"]),
            # Lätt maskad gata – tar bort siffror så inte exakta adressen avslöjas
            ("Gata", "".join(ch for ch in p["street"] if not ch.isdigit())),
            ("Alt namn", p["alt_names"]),
        ]
        # Visa upp till clue_step ledtrådar
        shown = clues[: max(1, st.session_state.clue_step)]
        for k, v in shown:
            st.write(f"**{k}:** {v if v else '—'}")
    else:
        st.info("Ingen plats vald ännu.")

# =================== Header ===================
st.title("🧭 Geoguessr - The Nabo Way")

# =================== Toppkontroller ===================
c1, c2, c3, c4 = st.columns([2, 1.2, 1.2, 1])
with c1:
    st.session_state.city = st.selectbox("Välj stad", list(DATAFILES.keys()),
                                         index=list(DATAFILES.keys()).index(st.session_state.city))
with c2:
    if st.button("Ny plats", use_container_width=True):
        rows = load_places(DATAFILES[st.session_state.city])
        st.session_state.place = random.choice(rows)
        st.session_state.guess = None
        st.session_state.clue_step = 1  # börja med en ledtråd synlig
with c3:
    st.button("Ny ledtråd", use_container_width=True,
              on_click=lambda: st.session_state.__setitem__("clue_step", st.session_state.clue_step + 1),
              disabled=st.session_state.place is None)
with c4:
    if st.button("Återställ", use_container_width=True):
        st.session_state.place = None
        st.session_state.guess = None
        st.session_state.clue_step = 0

st.divider()

# =================== Karta & gissning ===================
if not st.session_state.place:
    st.warning("Klicka **Ny plats** för att starta.")
    st.stop()

city_center = CITY_CENTERS[st.session_state.city]
place = st.session_state.place

left, right = st.columns([3, 2])

with left:
    # Folium med CartoDB Positron (ren ljus karta)
    m = folium.Map(location=city_center, zoom_start=12, control_scale=True, tiles="CartoDB Positron")
    # Visa användarens klick/gissning
    if st.session_state.guess:
        glat, glon = st.session_state.guess
        folium.Marker(location=(glat, glon), tooltip="Din gissning").add_to(m)

    # Interaktiv karta
    ev = st_folium(m, height=560, use_container_width=True, returned_objects=["last_clicked"])
    if ev and ev.get("last_clicked"):
        st.session_state.guess = (float(ev["last_clicked"]["lat"]), float(ev["last_clicked"]["lng"]))

with right:
    st.markdown("### Din gissning")
    if st.session_state.guess:
        glat, glon = st.session_state.guess
        st.write(f"Lat: **{glat:.6f}**, Lon: **{glon:.6f}**")
    else:
        st.info("Klicka på kartan för att sätta din gissning.")

    can_guess = st.session_state.guess is not None
    if st.button("Gissa!", type="primary", use_container_width=True, disabled=not can_guess):
        glat, glon = st.session_state.guess
        d_km = haversine_km(glat, glon, place["lat"], place["lon"])
        score = distance_score_km(d_km)

        st.success(f"Avstånd: **{d_km:.3f} km**  →  Poäng: **{score}**")

        # Efter gissning: visa facit och båda markörer
        res_map = folium.Map(location=city_center, zoom_start=12, control_scale=True, tiles="CartoDB Positron")
        folium.Marker(
            location=(place["lat"], place["lon"]),
            tooltip=f"Rätt plats: {place['display_name']}",
            icon=folium.Icon(color="green", icon="ok-sign"),
        ).add_to(res_map)
        folium.Marker(
            location=(glat, glon),
            tooltip=f"Din gissning ({d_km:.2f} km)",
            icon=folium.Icon(color="red"),
        ).add_to(res_map)
        folium.PolyLine([(glat, glon), (place["lat"], place["lon"])], weight=3, color=BRAND_GREEN).add_to(res_map)
        st_folium(res_map, height=360, use_container_width=True)

        # Visa full facittext separat
        st.info(
            f"**Facit**: {place['display_name']}, "
            f"{place['street']} {place['postnummer']} {place['ort']}."
        )

st.caption("Inga namn/adresser visas innan gissning. Klicka ‘Ny ledtråd’ för fler ledtrådar.")
