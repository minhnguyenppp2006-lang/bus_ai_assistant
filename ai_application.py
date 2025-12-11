import streamlit as st
import googlemaps
import google.generativeai as genai
from datetime import datetime
import speech_recognition as sr
from gtts import gTTS
from streamlit_mic_recorder import mic_recorder
import io
import tempfile
import os

# --- CẤU HÌNH TRANG ---
st.set_page_config(page_title="Bus AI Pro", page_icon="🚌", layout="wide")

# --- QUẢN LÝ API KEY (MỚI) ---
# Code sẽ tự động tìm key trong file secrets hệ thống
try:
    GOOGLE_MAPS_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except FileNotFoundError:
    st.error("⚠️ Lỗi cấu hình: Chưa tìm thấy file secrets.toml (Nếu chạy local) hoặc Secrets (Nếu chạy trên Cloud).")
    st.stop()
except KeyError:
    st.error("⚠️ Lỗi cấu hình: Thiếu API Key trong file secrets.")
    st.stop()

# --- SIDEBAR (Chỉ còn các tùy chọn cho User) ---
with st.sidebar:
    st.header("⚙️ Tùy chọn")
    auto_speak = st.checkbox("Tự động đọc (TTS)", value=True)
    st.divider()
    st.header("🎯 Tiêu chí tối ưu")
    optimize_mode = st.radio("Ưu tiên:", ["Thời gian ngắn nhất", "Ít đi bộ nhất", "Ít chuyển tuyến nhất"])

# --- CÁC HÀM LOGIC (GIỮ NGUYÊN) ---

def get_routes(start, end, api_key):
    # Logic cũ nhưng dùng api_key được truyền vào từ secrets
    if not api_key: return "Thiếu API Key"
    gmaps = googlemaps.Client(key=api_key)
    now = datetime.now()
    try:
        directions_result = gmaps.directions(
            start, end, mode="transit", transit_mode="bus", departure_time=now, alternatives=True, language="vi"
        )
        return directions_result
    except Exception as e:
        return f"Lỗi: {str(e)}"

def analyze_routes(routes_data, mode):
    # (Giữ nguyên logic phân tích như bài trước)
    if not routes_data or isinstance(routes_data, str): return []
    processed_routes = []
    for route in routes_data:
        leg = route['legs'][0]
        duration_value = leg['duration']['value']
        walking_distance = 0
        transfers = 0
        bus_names = []
        next_bus_time = 0
        
        for step in leg['steps']:
            if step['travel_mode'] == 'WALKING': walking_distance += step['distance']['value']
            elif step['travel_mode'] == 'TRANSIT':
                transfers += 1
                bus_names.append(step['transit_details']['line'].get('short_name', 'Bus'))
                if next_bus_time == 0: # Lấy chặng bus đầu
                    dep = step['transit_details']['departure_time']['value']
                    next_bus_time = max(0, int((datetime.fromtimestamp(dep) - datetime.now()).total_seconds() / 60))

        processed_routes.append({
            "summary": f"Xe {', '.join(bus_names)}",
            "duration_text": leg['duration']['text'],
            "duration_val": duration_value,
            "walking_text": f"{walking_distance}m đi bộ",
            "walking_val": walking_distance,
            "transfers": transfers,
            "wait_time": next_bus_time,
            "raw_steps": leg['steps']
        })

    if mode == "Thời gian ngắn nhất": processed_routes.sort(key=lambda x: x['duration_val'])
    elif mode == "Ít đi bộ nhất": processed_routes.sort(key=lambda x: x['walking_val'])
    elif mode == "Ít chuyển tuyến nhất": processed_routes.sort(key=lambda x: x['transfers'])
    return processed_routes

def text_to_speech(text):
    try:
        tts = gTTS(text=text, lang='vi')
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        return fp
    except: return None

def process_audio(audio_bytes):
    r = sr.Recognizer()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_bytes)
            name = tmp.name
        with sr.AudioFile(name) as src:
            audio = r.record(src)
            text = r.recognize_google(audio, language="vi-VN")
        os.remove(name)
        return text
    except: return None

# --- GIAO DIỆN CHÍNH ---

st.title("🚌 Bus Assistant (Public Version)")

# Khởi tạo Gemini từ Secrets
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-pro')

col1, col2 = st.columns([1.2, 0.8])

with col1:
    with st.form("search_form"):
        c1, c2 = st.columns(2)
        origin = c1.text_input("Điểm đi")
        destination = c2.text_input("Điểm đến")
        submitted = st.form_submit_button("Tìm đường 🚀")

    if submitted and origin and destination:
        with st.spinner("Đang xử lý..."):
            # Gọi hàm với KEY lấy từ secrets
            raw_data = get_routes(origin, destination, GOOGLE_MAPS_KEY)
            
            if isinstance(raw_data, str) and "Lỗi" in raw_data:
                st.error(f"Hệ thống đang bảo trì hoặc quá tải. ({raw_data})")
            elif raw_data:
                routes = analyze_routes(raw_data, optimize_mode)
                best = routes[0]
                
                st.success(f"Nên đi: {best['summary']}")
                st.metric("Thời gian chờ xe", f"{best['wait_time']} phút")
                
                context = f"Lộ trình: {best['summary']}, hết {best['duration_text']}. Đi bộ {best['walking_text']}."
                st.session_state['route_context'] = context
                
                if auto_speak:
                    aud = text_to_speech(f"Hãy đón {best['summary']}. Xe đến trong {best['wait_time']} phút.")
                    if aud: st.audio(aud, format='audio/mp3', start_time=0)
            else:
                st.warning("Không tìm thấy tuyến xe nào.")

with col2:
    st.subheader("💬 Trợ lý ảo")
    chat_box = st.container(height=400)
    
    if "messages" not in st.session_state: st.session_state.messages = []
    
    with chat_box:
        for m in st.session_state.messages: st.chat_message(m["role"]).write(m["content"])
        
    text_in = st.chat_input("Hỏi tôi...")
    mic_in = mic_recorder(start_prompt="🎤", stop_prompt="⏹️", key='mic')
    
    final_in = text_in
    if mic_in and ('last_audio' not in st.session_state or st.session_state.last_audio != mic_in['id']):
        st.session_state.last_audio = mic_in['id']
        t = process_audio(mic_in['audio']['bytes'])
        if t: final_in = t
        
    if final_in:
        st.session_state.messages.append({"role":"user", "content":final_in})
        st.chat_message("user").write(final_in)
        
        ctx = st.session_state.get('route_context', '')
        # Prompt đơn giản hóa để tiết kiệm token
        res = model.generate_content(f"Context: {ctx}. User: {final_in}. Answer short in Vietnamese.").text
        
        st.session_state.messages.append({"role":"assistant", "content":res})
        st.chat_message("assistant").write(res)
        if auto_speak:
            a = text_to_speech(res)

            if a: st.audio(a, format='audio/mp3')
