# app_delivery_quote.py — Modern UI (small map + purple primary button + bullet summary)
import streamlit as st
import pandas as pd
import pydeck as pdk
import requests
import time, hmac, hashlib, uuid, json, re
from urllib.parse import urlparse, parse_qs, unquote

# =========================
# CONFIG
# =========================
API_KEY    = st.secrets["LALAMOVE_API_KEY"]
API_SECRET = st.secrets["LALAMOVE_API_SECRET"]
MARKET     = st.secrets.get("LALAMOVE_MARKET", "TH").strip()
ENV        = st.secrets.get("LALAMOVE_ENV", "prod").strip()
BASE_URL   = "https://rest.lalamove.com" if ENV == "prod" else "https://rest.sandbox.lalamove.com"

SHOP_NAME = "Sugar Shade"
SHOP_ADDR = "Metro park สาทร"
SHOP_LAT  = 13.709679
SHOP_LNG  = 100.449409

# =========================
# LALAMOVE HELPERS (v3)
# =========================
def _now_ms(): return str(int(time.time()*1000))
def _compact(o): return json.dumps(o, separators=(",", ":"), ensure_ascii=False)
def _sig(secret, method, url, body, ts_ms):
    path = urlparse(url).path
    payload = _compact(body) if body else ""
    raw = f"{ts_ms}\r\n{method.upper()}\r\n{path}\r\n\r\n{payload}"
    return hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
def _headers(method, url, body):
    ts = _now_ms()
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json",
        "Authorization": f"hmac {API_KEY}:{ts}:{_sig(API_SECRET, method, url, body, ts)}",
        "Market": MARKET,
        "Request-ID": str(uuid.uuid4()),
    }
def llm(method, path, body=None, timeout=20):
    url = f"{BASE_URL}{path}"
    r = requests.request(method.upper(), url, headers=_headers(method, url, body),
                         data=_compact(body) if body else None, timeout=timeout)
    try: data = r.json()
    except Exception: data = {"raw": r.text}
    if not r.ok: raise RuntimeError(_compact({"status": r.status_code, "error": data}))
    return data
def get_quotation(stops, service_type, language="th_TH", item=None, scheduleAt=None, isRouteOptimized=None):
    payload = {"data": {"serviceType": service_type, "language": language, "stops": stops}}
    if item is not None: payload["data"]["item"] = item
    if scheduleAt is not None: payload["data"]["scheduleAt"] = scheduleAt
    if isRouteOptimized is not None: payload["data"]["isRouteOptimized"] = isRouteOptimized
    return llm("POST", "/v3/quotations", payload).get("data", {})

# =========================
# SMART PARSER (GMAPS + COORDS) + OSM
# =========================
SHORT_GMAP_HOSTS = ("maps.app.goo.gl", "goo.gl", "g.page", "g.co", "goo.gl/maps")
COORD_RE = re.compile(r"(?P<lat>[-+]?\d{1,3}\.\d+)[ ,]+(?P<lng>[-+]?\d{1,3}\.\d+)")

def parse_coords(text: str):
    if not text: return None
    m = COORD_RE.search(text)
    if not m: return None
    try:
        lat = float(m.group("lat")); lng = float(m.group("lng"))
        if -90 <= lat <= 90 and -180 <= lng <= 180: return lat, lng
    except Exception: pass
    return None

def expand_gmaps_shortlink(url: str) -> str:
    try:
        resp = requests.get(url, headers={"User-Agent":"Mozilla/5.0 (SugarShade-LLM Hybrid)"},
                            timeout=10, allow_redirects=True)
        return resp.url or url
    except Exception:
        return url

def extract_coords_and_name_from_gmaps(url: str):
    if not url: return None, None, None
    try: netloc = urlparse(url).netloc.lower()
    except Exception: netloc = ""
    if any(host in netloc for host in SHORT_GMAP_HOSTS):
        url = expand_gmaps_shortlink(url)

    lat = lng = None
    m = re.search(r"@([-+]?\d{1,3}\.\d+),([-+]?\d{1,3}\.\d+)", url)
    if m: lat, lng = float(m.group(1)), float(m.group(2))
    if lat is None:
        for key in ("q=", "query=", "center="):
            m = re.search(key + r"([-+]?\d{1,3}\.\d+),([-+]?\d{1,3}\.\d+)", url)
            if m: lat, lng = float(m.group(1)), float(m.group(2)); break

    name = None
    parsed = urlparse(url)
    if "/maps/place/" in parsed.path:
        name = parsed.path.split("/maps/place/")[1].split("/")[0]
        name = unquote(name.replace("+"," ")).strip()
    if not name:
        qs = parse_qs(parsed.query)
        for k in ("q","query","destination"):
            if k in qs:
                val = qs[k][0]
                if not re.match(r"^[-+]?\d{1,3}\.\d+,\s*[-+]?\d{1,3}\.\d+$", val):
                    name = unquote(val.replace("+"," ")).strip(); break
    return lat, lng, name

def geocode_osm(query, country="th", limit=8):
    if not query or len(query.strip()) < 3: return []
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params={"q":query,"format":"json","limit":limit,"countrycodes":country},
                     headers={"User-Agent":"SugarShade-Lalamove-Helper"}, timeout=10)
    r.raise_for_status()
    return [{"label":it.get("display_name",""),"lat":float(it["lat"]),"lng":float(it["lon"])} for it in r.json()]

def resolve_destination(text: str, country="th"):
    c = parse_coords(text)
    if c:
        lat, lng = c
        return {"lat": lat, "lng": lng, "label": f"พิกัด: {lat:.6f}, {lng:.6f}", "source": "coords"}
    lat, lng, name = extract_coords_and_name_from_gmaps(text)
    if lat is not None and lng is not None:
        return {"lat": lat, "lng": lng, "label": name or f"พิกัด: {lat:.6f}, {lng:.6f}", "source": "gmaps"}
    res = geocode_osm(text, country=country, limit=8)
    if not res: return None
    first = res[0]
    return {"lat": first["lat"], "lng": first["lng"], "label": first["label"], "source": "osm"}

# =========================
# UI
# =========================
st.set_page_config(page_title="เช็คค่าส่ง", page_icon="🛵🚗", layout="wide")

# Styling (purple primary button + compact map area)
st.markdown("""
<style>
:root { --card-bg:#fff; --muted:#6b7280; --accent:#7c3aed; --border:#e5e7eb; }
html, body, [class*="css"] { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; }
.card{ background:var(--card-bg); border:1px solid var(--border); border-radius:14px; padding:16px 18px; box-shadow:0 2px 12px rgba(0,0,0,0.05); }
.headline{ font-size:22px; font-weight:800; margin-bottom:4px; }
.subtle{ color:var(--muted); font-size:13px; }
.result-card{ border:1px solid var(--border); border-radius:12px; padding:14px 16px; background:#fafafa; }
div.stButton > button[kind="primary"]{ background:#7c3aed; color:#fff; border:0; border-radius:12px; padding:14px 18px; font-weight:800; }
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="card">
  <div class="headline">เช็คค่าส่ง🛵🚗</div>
  <div class="subtle">จุดรับจาก <b>{SHOP_NAME}</b> — {SHOP_ADDR}</div>
</div>
""", unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("search_results", [])
ss.setdefault("selected_idx", 0)
ss.setdefault("last_quote", None)
ss.setdefault("vehicle", "MOTORCYCLE")
ss.setdefault("dest", None)

colL, colR = st.columns([7,5])

with colL:
    q = st.text_input("📍 ปลายทาง", placeholder="วางลิงก์ Google Maps / ใส่พิกัด / หรือชื่อสถานที่")

    vehicle_display = st.selectbox("ประเภทรถ", ["🛵 มอเตอร์ไซค์", "🚗 รถยนต์"], index=0)
    ss.vehicle = "MOTORCYCLE" if vehicle_display.startswith("🛵") else "CAR"

    if st.button("🔎 ค้นหา", use_container_width=True):
        try:
            with st.spinner("กำลังค้นหา/แปลงพิกัด…"):
                resolved = resolve_destination(q.strip())
                ss.last_quote = None
                if not resolved:
                    ss.search_results = []
                    ss.dest = None
                    st.warning("ไม่พบพิกัดจากลิงก์/ข้อความ")
                else:
                    ss.dest = {"label": resolved["label"], "lat": resolved["lat"], "lng": resolved["lng"]}
                    ss.search_results = [ss.dest]
                    ss.selected_idx = 0
                    st.success(f"ปลายทาง: {ss.dest['label'][:120]}")
        except Exception as e:
            st.error("เกิดข้อผิดพลาดในการค้นหา/แปลงพิกัด")
            st.caption(str(e))

with colR:
    if ss.get("dest"):
        # Small preview map with a path line (height ~ 200px)
        shop = [SHOP_LAT, SHOP_LNG]
        dst  = [ss["dest"]["lat"], ss["dest"]["lng"]]
        view = pdk.ViewState(latitude=(shop[0]+dst[0])/2, longitude=(shop[1]+dst[1])/2, zoom=11)
        layers = [
            pdk.Layer("ScatterplotLayer",
                      data=[{"lat":shop[0],"lon":shop[1]},{"lat":dst[0],"lon":dst[1]}],
                      get_position='[lon, lat]', get_radius=100, pickable=False),
            pdk.Layer("PathLayer",
                      data=[{"path":[[shop[1],shop[0]],[dst[1],dst[0]]]}],
                      get_path="path", width_scale=2, width_min_pixels=2)
        ]
        st.pydeck_chart(pdk.Deck(map_style="light", initial_view_state=view, layers=layers), use_container_width=True, height=200)
    else:
        st.caption("ยังไม่มีปลายทางที่เลือก")

# Primary purple button (big)
quote_clicked = st.button("เช็คค่าส่ง", type="primary", use_container_width=True, disabled=not bool(ss.get("dest")))

if quote_clicked and ss.get("dest"):
    try:
        sel = ss["dest"]
        stops = [
            {"coordinates":{"lat":f"{SHOP_LAT}","lng":f"{SHOP_LNG}"},"address":SHOP_ADDR},
            {"coordinates":{"lat":f"{sel['lat']}","lng":f"{sel['lng']}"},"address":sel["label"][:120]},
        ]
        item = {"quantity":"1","weight":"LESS_THAN_3_KG","categories":["FOOD_DELIVERY"],"handlingInstructions":["KEEP_UPRIGHT"]}
        with st.spinner("กำลังคำนวณราคา…"):
            ss.last_quote = get_quotation(stops=stops, service_type=ss.vehicle, language="th_TH", item=item, isRouteOptimized=False)
    except Exception as e:
        ss.last_quote = None
        st.error("คำนวณราคาไม่สำเร็จ")
        with st.expander("รายละเอียดข้อผิดพลาด", expanded=False):
            st.code(str(e))

# ===== Result + Bullet Summary =====
if ss.get("last_quote"):
    data = ss["last_quote"]
    pb = data.get("priceBreakdown") or {}
    total = pb.get("total")
    currency = pb.get("currency","THB")
    dist_m = (data.get("distance") or {}).get("value")
    km_txt = f"{(int(dist_m)/1000):.1f} กม." if dist_m else "—"
    dest_label = ss["dest"]["label"] if ss.get("dest") else "—"
    vehicle_th = "มอเตอร์ไซค์" if ss.vehicle=="MOTORCYCLE" else "รถยนต์"


    st.markdown(
        f"""
        <div style="display:flex;align-items:baseline;gap:10px;margin-top:8px;">
        <div style="font-size:40px;font-weight:900;letter-spacing:-.02em;">
            ฿{total if total else '—'}
        </div>
        <div style="color:#6b7280;">{currency}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Bullets สรุปรายการ (ไม่ใส่ราคาซ้ำ เพราะแสดงไว้ข้างบนแล้ว)
    st.markdown(
        f"- **ปลายทาง:** {dest_label[:140]}\n"
        f"- **ระยะทาง:** {km_txt}\n"
        f"- **วิธีจัดส่ง:** {vehicle_th}\n"
    )

    st.markdown("""
<div class="card" style="margin-top:10px;">
เป็นราคาจากแอพ Lalamove ณ วันที่สั่ง วันส่งอาจมีเปลี่ยนแปลงได้ ขึ้นอยู่กับการจราจร/ฝนตก

📍 ทางร้านเพียงอำนวยความสะดวกในการเรียกรถ ไม่ใช่คนขับของทางร้าน  
❌ ทั้งนี้หากเกิดความล่าช้าหรือความเสียหายในระหว่างการจัดส่ง ทางร้านขอสงวนสิทธิ์ไม่รับผิดชอบในทุกกรณี

🩵 โปรดเลือกวิธีจัดส่งให้เหมาะสมกับระยะทาง ขนาดและแบบเค้ก
</div>
""", unsafe_allow_html=True)