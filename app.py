from __future__ import annotations
import csv
import random
from math import radians, sin, cos, asin, sqrt
from pathlib import Path
from typing import Dict, List

import streamlit as st
from streamlit_folium import st_folium
import folium

APP_DIR = Path(__file__).parent

# ---------- Städer & filer (behåll dina CSV-filer med samma namn) ----------
DATAFILES: Dict[str, Path] = {
    "Stockholm": APP_DIR / "places_stockholm.csv",
    "Göteborg":  APP_DIR / "places_goteborg.csv",
    "Malmö":     APP_DIR / "places_malmo.csv",
}

CITY_CENTERS: Dict[str, tuple[float, float]] = {
    "Stockholm": (59.334, 18.063),
    "Göteborg":  (57.707, 11.967),
    "Malmö":     (55.605, 13.003),
}

REQUIRED = [
    "id","display_name","alt_names","street","postnummer","ort","kommun","lan","lat","lon","svardighet"
]

# ---------- Cache & laddning ----------
@st.cache_data
def load_places(csv_path: Path) -> List[Dict]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Saknar fil: {csv_path.name} (lägg den bredvid app.py)")
    rows: List[Dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        cols = [c.strip() for c in (rdr.fieldnames or [])]
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            raise ValueError(f"Fel kolumner i {csv_path.name}, saknas: {missing}")

        for r in rdr:
            try:
                rid = int((r.get("id") or "").strip())
                lat = float((r.get("lat") or "").strip())
                lon = float((r.get("lon") or "").strip())
            except Exception:
                # hoppa över rader med trasiga värden
                continue

            rows.append({
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
            })
    if not rows:
        raise ValueError(f"Inga giltiga rader i {csv_path.name}")
    return rows

# ---------- Geo & Poäng ----------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(p1) * cos(p2) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def distance_score_km(distance_km: float) -> int:
    # samma logik som tidigare: 1.2 km -> 120 p
    return int(round(distance_km * 100))

# ---------- UI / State ----------
st.set_page_config(page_title="Geoguessr - The Nabo Way", page_icon="🧭", layout="wide")
st.title("🧭 Geoguessr - The Nabo Way (Streamlit)")

if "city" not in st.session_state:
    st.session_state.city = "Stockholm"
if "place" not in st.session_state:
    st.session_state.place = None  # dict med vald plats
if "guess" not in st.session_state:
    st.session_state.guess = None  # (lat, lon)

# Sidopanel med instruktioner och ledtråd
with st.sidebar:
    st.header("🎯 Instruktioner")
    st.markdown(
        "- Välj stad\n"
        "- Klicka **Ny plats**\n"
        "- Klicka på kartan för att gissa plats\n"
        "- Tryck **Gissa!** för poäng"
    )
    st.divider()
    if st.session_state.place:
        p = st.session_state.place
        st.subheader("Ledtråd")
        # Visa något från dina CSV-fält som hint:
        st.write(
            f"**Ort:** {p['ort']}  \n"
            f"**Kommun:** {p['kommun']}  \n"
            f"**Län:** {p['lan']}"
        )
    else:
        st.info("Ingen plats vald ännu.")

# Toppkontroller
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    st.session_state.city = st.selectbox("Välj stad", list(DATAFILES.keys()), index=list(DATAFILES.keys()).index(st.session_state.city))
with col2:
    if st.button("Ny plats", use_container_width=True):
        try:
            rows = load_places(DATAFILES[st.session_state.city])
            st.session_state.place = random.choice(rows)
            st.session_state.guess = None
        except Exception as e:
            st.error(str(e))
with col3:
    if st.button("Återställ", use_container_width=True):
        st.session_state.place = None
        st.session_state.guess = None

st.divider()

# Visa karta och gissning
if not st.session_state.place:
    st.warning("Klicka **Ny plats** för att starta.")
    st.stop()

city_center = CITY_CENTERS[st.session_state.city]
place = st.session_state.place

left, right = st.columns([3, 2])

with left:
    # Folium-karta där användaren kan klicka för att sätta gissning
    m = folium.Map(location=city_center, zoom_start=12, control_scale=True)
    # Visa användarens gissning (om finns)
    if st.session_state.guess:
        glat, glon = st.session_state.guess
        folium.Marker(location=(glat, glon), tooltip="Din gissning").add_to(m)
    # (Avslöja INTE mål-punkten förrän efter gissning)

    map_event = st_folium(m, height=550, use_container_width=True, returned_objects=["last_clicked"])

    # Läs av klick
    if map_event and map_event.get("last_clicked"):
        lat = map_event["last_clicked"]["lat"]
        lon = map_event["last_clicked"]["lng"]
        st.session_state.guess = (float(lat), float(lon))

with right:
    st.markdown("### Din gissning")
    if st.session_state.guess:
        glat, glon = st.session_state.guess
        st.write(f"Lat: **{glat:.6f}**, Lon: **{glon:.6f}**")
    else:
        st.info("Klicka på kartan för att sätta din gissning.")

    if st.button("Gissa!", type="primary", use_container_width=True, disabled=st.session_state.guess is None):
        if st.session_state.guess is None:
            st.warning("Gör en gissning genom att klicka på kartan.")
        else:
            glat, glon = st.session_state.guess
            d_km = haversine_km(glat, glon, place["lat"], place["lon"])
            score = distance_score_km(d_km)

            # Visa resultat + lösning
            st.success(f"Avstånd: **{d_km:.3f} km**  →  Poäng: **{score}**")
            st.info(
                f"Rätt plats var **{place['display_name']}**, "
                f"{place['street']} {place['postnummer']} {place['ort']}."
            )

            # Visa målmarkör på separat karta efter gissning
            res_map = folium.Map(location=city_center, zoom_start=12, control_scale=True)
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
            folium.PolyLine([(glat, glon), (place["lat"], place["lon"])], weight=3).add_to(res_map)

            st_folium(res_map, height=350, use_container_width=True)

    st.caption("Tips: Om du vill visa fler ledtrådar, använd fälten i dina CSV-filer (t.ex. alt_names, street, svårighet).")
