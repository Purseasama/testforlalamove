import streamlit as st
import pandas as pd
import requests
import time
import hmac
import hashlib
import uuid
import json
import re
from urllib.parse import urlparse

# ============================================
# CONFIGURATION - EDIT THESE
# ============================================

# Lalamove credentials (get from https://developers.lalamove.com)
LALAMOVE_API_KEY = st.secrets.get("LALAMOVE_API_KEY", "YOUR_API_KEY_HERE")
LALAMOVE_API_SECRET = st.secrets.get("LALAMOVE_API_SECRET", "YOUR_API_SECRET_HERE")
LALAMOVE_COUNTRY = "TH"
LALAMOVE_MARKET  = "TH-BKK" 
LALAMOVE_BASE_URL = "https://rest.sandbox.lalamove.com"  # Use sandbox for testing

# Your shop details
SHOP_NAME = "Sugar Shade"
SHOP_ADDR = "เทอดไท 77, กรุงเทพมหานคร"
SHOP_LAT = 13.709679
SHOP_LNG = 100.441462

# ============================================
# FUNCTIONS
# ============================================

# OpenStreetMap Geocoding (FREE - No API key needed!)
def geocode_address_nominatim(address):
    """Convert address to lat/lng using free OpenStreetMap Nominatim"""
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": address,
        "format": "json",
        "limit": 5,
        "countrycodes": "th",
        "addressdetails": 1
    }
    headers = {
        "User-Agent": "SugarShade-Delivery-Test-App"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if len(data) > 0:
            results = []
            for item in data:
                results.append({
                    "lat": float(item["lat"]),
                    "lng": float(item["lon"]),
                    "address": item["display_name"],
                    "name": item.get("name", "")
                })
            return {"success": True, "results": results}
        else:
            return {"success": False, "error": "ไม่พบที่อยู่"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Parse coordinates from text
def parse_coords_from_text(text: str):
    if not text:
        return (None, None)
    m = re.search(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", text)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)

# Lalamove API functions
def _now_ms():
    return str(int(time.time() * 1000))

def _build_signature(secret, method, url, body, ts_ms):
    parsed = urlparse(url)
    path = parsed.path
    payload = json.dumps(body, separators=(",", ":")) if body else ""
    to_sign = f"{ts_ms}\r\n{method.upper()}\r\n{path}\r\n\r\n{payload}"
    return hmac.new(secret.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

def _headers(method, url, body):
    ts = _now_ms()
    sig = _build_signature(LALAMOVE_API_SECRET, method, url, body, ts)
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json",
        "X-Request-ID": str(uuid.uuid4()),
        # Keep country if you like (harmless), but MARKET is the key to fix the 422.
        "X-LLM-Country": LALAMOVE_COUNTRY,
        "X-LLM-Market": LALAMOVE_MARKET,  # <-- add this line
        "Authorization": f"hmac {LALAMOVE_API_KEY}:{ts}:{sig}",
    }

def lalamove_request(method, path, body=None):
    url = f"{LALAMOVE_BASE_URL}{path}"
    resp = requests.request(method, url, headers=_headers(method, url, body),
                            data=json.dumps(body) if body else None, timeout=30)
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        return None
    if not resp.ok:
        raise RuntimeError(json.dumps({"status": resp.status_code, "error": data}, ensure_ascii=False))
    return data

def lalamove_get_quotation(stops, service_type):
    payload = {
        "serviceType": service_type,
        "stops": stops,
    }
    return lalamove_request("POST", "/v3/quotations", payload)

# ============================================
# STREAMLIT APP
# ============================================

st.set_page_config(page_title="Lalamove Test", page_icon="🚚", layout="wide")

st.title("🚚 Lalamove + OpenStreetMap Test")
st.write("ทดสอบระบบค้นหาที่อยู่และคำนวณค่าส่ง")

# Show configuration status
with st.expander("⚙️ ตรวจสอบการตั้งค่า"):
    if LALAMOVE_API_KEY == "YOUR_API_KEY_HERE":
        st.error("❌ กรุณาใส่ Lalamove API Key")
    else:
        st.success(f"✅ API Key: {LALAMOVE_API_KEY[:10]}...")
    
    if LALAMOVE_API_SECRET == "YOUR_API_SECRET_HERE":
        st.error("❌ กรุณาใส่ Lalamove API Secret")
    else:
        st.success(f"✅ API Secret: {LALAMOVE_API_SECRET[:10]}...")
    
    st.info(f"🏪 ร้าน: {SHOP_NAME}")
    st.info(f"📍 พิกัดร้าน: {SHOP_LAT}, {SHOP_LNG}")
    st.info(f"🌐 Lalamove URL: {LALAMOVE_BASE_URL}")

st.divider()

# ============================================
# SECTION 1: ADDRESS SEARCH TEST
# ============================================

st.header("1️⃣ ทดสอบค้นหาที่อยู่ (OpenStreetMap)")

search_method = st.radio(
    "เลือกวิธีค้นหา:",
    ["🗺️ ค้นหาที่อยู่ (ฟรี)", "🎯 ใส่พิกัดเอง"],
    horizontal=True
)

if search_method == "🗺️ ค้นหาที่อยู่ (ฟรี)":
    search_address = st.text_input(
        "ค้นหาที่อยู่",
        placeholder="เช่น สยามพารากอน กรุงเทพ, MBK Center, เซ็นทรัลเวิลด์",
        help="พิมพ์ชื่อสถานที่หรือที่อยู่"
    )
    
    if search_address and len(search_address) > 3:
        if st.button("🔍 ค้นหา", type="primary"):
            with st.spinner("🔍 กำลังค้นหา..."):
                time.sleep(1)  # Rate limiting
                geocode_result = geocode_address_nominatim(search_address)
            
            if geocode_result["success"]:
                st.success(f"✅ พบ {len(geocode_result['results'])} ผลลัพธ์")
                
                # Show results
                result_options = []
                for i, result in enumerate(geocode_result["results"]):
                    display_text = result['address']
                    if result.get('name'):
                        display_text = f"{result['name']} - {result['address']}"
                    result_options.append(display_text)
                
                selected_index = st.radio(
                    "เลือกที่อยู่ที่ถูกต้อง:",
                    range(len(result_options)),
                    format_func=lambda x: result_options[x]
                )
                
                # Store selected location
                selected_result = geocode_result["results"][selected_index]
                st.session_state.selected_location = {
                    "lat": selected_result["lat"],
                    "lng": selected_result["lng"],
                    "address": selected_result["address"]
                }
                
                # Show map
                st.map(pd.DataFrame({
                    'lat': [SHOP_LAT, selected_result["lat"]],
                    'lon': [SHOP_LNG, selected_result["lng"]]
                }))
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("🏪 จุดรับ (ร้าน)", f"{SHOP_LAT:.6f}, {SHOP_LNG:.6f}")
                with col2:
                    st.metric("📍 จุดส่ง", f"{selected_result['lat']:.6f}, {selected_result['lng']:.6f}")
                
            else:
                st.error(f"❌ {geocode_result['error']}")
                st.info("💡 ลองใส่ที่อยู่ให้ละเอียดขึ้น เช่น เพิ่มชื่อถนน, แขวง, เขต")

elif search_method == "🎯 ใส่พิกัดเอง":
    st.info("💡 วิธีหาพิกัด: เปิด Google Maps → คลิกขวาที่ตำแหน่ง → คัดลอกตัวเลข")
    manual_coords = st.text_input(
        "พิกัด (latitude, longitude)",
        placeholder="13.756331, 100.501762"
    )
    
    if manual_coords:
        parsed_lat, parsed_lng = parse_coords_from_text(manual_coords)
        if parsed_lat and parsed_lng:
            st.session_state.selected_location = {
                "lat": parsed_lat,
                "lng": parsed_lng,
                "address": f"พิกัด: {parsed_lat}, {parsed_lng}"
            }
            st.success("✅ พิกัดถูกต้อง")
            st.map(pd.DataFrame({
                'lat': [SHOP_LAT, parsed_lat],
                'lon': [SHOP_LNG, parsed_lng]
            }))
        else:
            st.error("❌ รูปแบบพิกัดไม่ถูกต้อง ใส่เป็น latitude, longitude")

st.divider()

# ============================================
# SECTION 2: LALAMOVE QUOTATION TEST
# ============================================

st.header("2️⃣ ทดสอบคำนวณค่าส่ง Lalamove")

if "selected_location" in st.session_state:
    st.success("✅ มีที่อยู่ปลายทางแล้ว")
    st.write(f"📍 **ปลายทาง:** {st.session_state.selected_location['address'][:100]}")
    
    # Select vehicle type
    service_type = st.selectbox(
        "เลือกประเภทรถ:",
        ["MOTORCYCLE", "CAR", "VAN", "TRUCK"]
    )
    
    if st.button("💰 คำนวณค่าส่ง", type="primary", use_container_width=True):
        if LALAMOVE_API_KEY == "YOUR_API_KEY_HERE" or LALAMOVE_API_SECRET == "YOUR_API_SECRET_HERE":
            st.error("❌ กรุณาใส่ Lalamove API credentials ก่อน")
        else:
            location = st.session_state.selected_location
            
            try:
                # Prepare stops
                stops = [
                    {
                        "location": {"lat": str(SHOP_LAT), "lng": str(SHOP_LNG)},
                        "addresses": {
                            "th_TH": {
                                "displayString": SHOP_ADDR,
                                "country": "TH"
                            }
                        }
                    },
                    {
                        "location": {"lat": str(location["lat"]), "lng": str(location["lng"])},
                        "addresses": {
                            "th_TH": {
                                "displayString": location["address"][:100],
                                "country": "TH"
                            }
                        }
                    }
                ]
                
                # Get quotation
                with st.spinner("⏳ กำลังคำนวณค่าขนส่ง..."):
                    quote_result = lalamove_get_quotation(stops, service_type)
                
                if quote_result and "priceBreakdown" in quote_result:
                    st.success("✅ คำนวณค่าขนส่งสำเร็จ!")
                    
                    # Display metrics
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        total_fee = quote_result.get("priceBreakdown", {}).get("total", "N/A")
                        st.metric("💵 ค่าส่งทั้งหมด", f"฿{total_fee}")
                    
                    with col2:
                        distance = quote_result.get("distance", {}).get("value", "N/A")
                        st.metric("📏 ระยะทาง", f"{distance} กม.")
                    
                    with col3:
                        base_fee = quote_result.get("priceBreakdown", {}).get("base", "N/A")
                        st.metric("💰 ค่าบริการพื้นฐาน", f"฿{base_fee}")
                    
                    # Show detailed breakdown
                    with st.expander("📊 รายละเอียดทั้งหมด"):
                        st.json(quote_result)
                    
                    st.info(f"🚗 ประเภทรถ: {service_type}")
                    st.warning("⚠️ ค่าขนส่งนี้เป็นการประเมินเบื้องต้น ราคาจริงอาจแตกต่างขึ้นกับสภาพจราจร")
                    
                else:
                    st.error("❌ ไม่สามารถคำนวณค่าขนส่งได้")
                    if quote_result:
                        with st.expander("ดูรายละเอียด Error"):
                            st.json(quote_result)
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {str(e)}")
                st.info("💡 ตรวจสอบว่า API credentials ถูกต้องหรือไม่")

else:
    st.warning("⚠️ กรุณาค้นหาและเลือกที่อยู่ปลายทางก่อน (ในส่วน 1)")

st.divider()

# ============================================
# HELP SECTION
# ============================================

with st.expander("❓ วิธีใช้"):
    st.markdown("""
    ### 📝 ขั้นตอนการทดสอบ:
    
    **1. ตั้งค่า Lalamove API:**
    - สมัครที่ https://developers.lalamove.com
    - สร้าง Application (เลือก Sandbox สำหรับทดสอบ)
    - ได้ API Key และ Secret
    - ใส่ใน `.streamlit/secrets.toml`:
    ```toml
    LALAMOVE_API_KEY = "pk_test_xxxxx"
    LALAMOVE_API_SECRET = "sk_test_xxxxx"
    ```
    
    **2. ทดสอบค้นหาที่อยู่:**
    - พิมพ์ชื่อสถานที่ เช่น "สยามพารากอน กรุงเทพ"
    - คลิก "🔍 ค้นหา"
    - เลือกที่อยู่ที่ถูกต้อง
    
    **3. ทดสอบคำนวณค่าส่ง:**
    - เลือกประเภทรถ
    - คลิก "💰 คำนวณค่าส่ง"
    - ดูราคาและระยะทาง
    
    ### ✅ เมื่อทดสอบสำเร็จ:
    - คัดลอกโค้ดไปใส่ในแอปหลักของคุณ
    - เปลี่ยนจาก Sandbox เป็น Production URL เมื่อพร้อม
    """)

with st.expander("🔧 Troubleshooting"):
    st.markdown("""
    **ถ้าค้นหาที่อยู่ไม่พบ:**
    - ใส่ชื่อสถานที่ให้ละเอียดขึ้น
    - เพิ่ม "กรุงเทพ" หรือชื่อจังหวัด
    - ลองใช้ภาษาอังกฤษ เช่น "Siam Paragon Bangkok"
    
    **ถ้า Lalamove ไม่ทำงาน:**
    - ตรวจสอบว่าใส่ API Key และ Secret ถูกต้อง
    - ตรวจสอบว่าใช้ Sandbox URL หรือไม่
    - ดู Error message ใน "ดูรายละเอียด Error"
    
    **Rate Limiting:**
    - OpenStreetMap: ไม่เกิน 1 request ต่อวินาที (มี delay ในโค้ดแล้ว)
    - Lalamove Sandbox: ตรวจสอบ limit ในเอกสาร API
    """)
