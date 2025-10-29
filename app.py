# app.py
import streamlit as st
import pandas as pd
import requests
import time, hmac, hashlib, uuid, json
from urllib.parse import urlparse

# =========================
# CONFIG (from secrets)
# =========================
API_KEY    = st.secrets["LALAMOVE_API_KEY"]          # pk_prod_xxx or pk_test_xxx
API_SECRET = st.secrets["LALAMOVE_API_SECRET"]       # sk_prod_xxx or sk_test_xxx
MARKET     = st.secrets.get("LALAMOVE_MARKET", "TH").strip()
ENV        = st.secrets.get("LALAMOVE_ENV", "prod").strip()   # "prod" or "sandbox"
BASE_URL   = "https://rest.lalamove.com" if ENV == "prod" else "https://rest.sandbox.lalamove.com"

# Pickup (Bangkok)
SHOP_NAME = "Sugar Shade"
SHOP_ADDR = "เทอดไท 77, กรุงเทพมหานคร"
SHOP_LAT  = 13.709679
SHOP_LNG  = 100.441462

# =========================
# Lalamove helpers (v3)
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
        "Market": MARKET,                 # e.g., "TH"
        "Request-ID": str(uuid.uuid4()),
    }

def llm(method, path, body=None, timeout=20):
    url = f"{BASE_URL}{path}"
    r = requests.request(method.upper(), url, headers=_headers(method, url, body),
                         data=_compact(body) if body else None, timeout=timeout)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    if not r.ok:
        raise RuntimeError(_compact({"status": r.status_code, "error": data}))
    return data

def get_quotation(stops, service_type, language="th_TH"):
    payload = {"data": {"serviceType": service_type, "language": language, "stops": stops}}
    return llm("POST", "/v3/quotations", payload).get("data", {})

# =========================
# Geocoding (Nominatim)
# =========================
def geocode(query, country="th", limit=8):
    if not query or len(query.strip()) < 3:
        return []
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "json", "limit": limit, "countrycodes": country},
        headers={"User-Agent": "SugarShade-Lalamove-Helper"},
        timeout=10,
    )
    resp.raise_for_status()
    out = []
    for it in resp.json():
        out.append({
            "label": it.get("display_name", ""),
            "lat": float(it["lat"]),
            "lng": float(it["lon"]),
        })
    return out

# =========================
# UI
# =========================
st.set_page_config(page_title="Lalamove TH Quote", page_icon="🚚", layout="centered")
st.title("🚚 ค่าขนส่ง Lalamove (TH)")
st.caption(f"รับของ: {SHOP_NAME} — {SHOP_ADDR}")

# --- Session state ---
if "search_results" not in st.session_state: st.session_state.search_results = []
if "selected_idx"  not in st.session_state: st.session_state.selected_idx  = 0
if "last_quote"    not in st.session_state: st.session_state.last_quote    = None

# Search by place name
with st.container():
    q = st.text_input("ปลายทาง (ชื่อสถานที่/ที่อยู่)", placeholder="เช่น Siam Paragon, CentralWorld, รพ.ศิริราช …")
    colA, colB = st.columns([1,1])
    if colA.button("ค้นหา"):
        try:
            st.session_state.search_results = geocode(q)
            st.session_state.selected_idx = 0
            st.session_state.last_quote = None
            if not st.session_state.search_results:
                st.warning("ไม่พบสถานที่ ลองระบุให้ละเอียดขึ้น")
        except Exception as e:
            st.error("ค้นหาสถานที่ไม่สำเร็จ")
            st.caption(str(e))

    results = st.session_state.search_results
    if results:
        labels = [r["label"][:80] for r in results]
        st.session_state.selected_idx = st.selectbox(
            "เลือกปลายทาง", options=range(len(results)),
            format_func=lambda i: labels[i], index=st.session_state.selected_idx
        )

        sel = results[st.session_state.selected_idx]

        # vehicle selector (ONLY motorcycle and car)
        service_type = colB.selectbox("ประเภทรถ", ["MOTORCYCLE", "CAR"], index=0)

        # quick map preview
        st.map(pd.DataFrame({"lat":[SHOP_LAT, sel["lat"]], "lon":[SHOP_LNG, sel["lng"]]}))

        # compute price
        if st.button("คำนวณค่าส่ง 💰", use_container_width=True):
            try:
                stops = [
                    {"coordinates": {"lat": f"{SHOP_LAT}", "lng": f"{SHOP_LNG}"}, "address": SHOP_ADDR},
                    {"coordinates": {"lat": f"{sel['lat']}", "lng": f"{sel['lng']}"}, "address": sel["label"][:120]},
                ]
                data = get_quotation(stops=stops, service_type=service_type, language="th_TH")
                st.session_state.last_quote = data
            except Exception as e:
                st.session_state.last_quote = None
                st.error("คำนวณราคาไม่สำเร็จ")
                with st.expander("รายละเอียดข้อผิดพลาด"):
                    st.code(str(e))

# show compact card if have quote
if st.session_state.last_quote:
    data = st.session_state.last_quote
    pb = data.get("priceBreakdown") or {}
    total = pb.get("total")
    currency = pb.get("currency", "")
    dist_m = (data.get("distance") or {}).get("value")

    st.success("ได้ราคาแล้ว")
    c1, c2, c3 = st.columns(3)
    c1.metric("ราคา", f"{total} {currency}" if total else "—")
    c2.metric("ระยะทาง", f"{(int(dist_m)/1000):.1f} กม." if dist_m else "—")
    c3.metric("รถ", data.get("serviceType", "—"))

    st.caption(f"ปลายทาง: { (st.session_state.search_results[st.session_state.selected_idx]['label'])[:90] }")

# footer info (tiny)
with st.expander("ข้อมูลระบบ"):
    st.write(f"ENV: {'Production' if ENV=='prod' else 'Sandbox'} | Market: {MARKET} | Base: {BASE_URL}")