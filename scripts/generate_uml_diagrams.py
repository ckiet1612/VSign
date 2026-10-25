# -*- coding: utf-8 -*-
"""
Generate Standard Black & White UML Diagrams for VSign Academic Report:
1. Sơ đồ 5.1: UML Deployment & Component Diagram (Kiến trúc hệ thống)
2. Sơ đồ 5.2: UML Sequence Diagram (Luồng nhận dạng & giao tiếp hai chiều)
3. Sơ đồ 5.3: UML Sequence Diagram (Quy trình ghép nối quầy & bắt tay WebRTC)
4. Sơ đồ 5.4: UML Activity Diagram (Đường ống MLOps & Vòng đời mô hình)

Strict constraints:
- Strictly Black & White / Grayscale (White #ffffff, Black #000000, Gray #f0f0f0)
- Minimal text, concise UML naming conventions
- Professional engineering typography and clean UML shapes
"""

import os
import math
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = "artifacts/report_diagrams"
os.makedirs(OUTPUT_DIR, exist_ok=True)

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if os.path.exists("/System/Library/Fonts/Supplemental/Arial Bold.ttf") else FONT_PATH

def get_font(size, bold=False):
    path = FONT_BOLD_PATH if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except:
        return ImageFont.load_default()

def draw_arrow(draw, start, end, width=2, arrow_size=9, dashed=False):
    x1, y1 = start
    x2, y2 = end
    if dashed:
        # Draw dashed line
        total_dist = math.hypot(x2 - x1, y2 - y1)
        dash_len = 8
        gap_len = 5
        curr_dist = 0
        angle = math.atan2(y2 - y1, x2 - x1)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        while curr_dist < total_dist - arrow_size:
            start_seg = curr_dist
            end_seg = min(curr_dist + dash_len, total_dist - arrow_size)
            draw.line([(x1 + start_seg * cos_a, y1 + start_seg * sin_a),
                       (x1 + end_seg * cos_a, y1 + end_seg * sin_a)], fill="#000000", width=width)
            curr_dist += dash_len + gap_len
    else:
        draw.line([start, end], fill="#000000", width=width)
    
    # Solid black arrowhead
    angle = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - arrow_size * math.cos(angle - math.pi / 6), y2 - arrow_size * math.sin(angle - math.pi / 6))
    p2 = (x2 - arrow_size * math.cos(angle + math.pi / 6), y2 - arrow_size * math.sin(angle + math.pi / 6))
    draw.polygon([end, p1, p2], fill="#000000")

def draw_open_arrow(draw, start, end, width=2, arrow_size=9, dashed=True):
    x1, y1 = start
    x2, y2 = end
    total_dist = math.hypot(x2 - x1, y2 - y1)
    dash_len = 8
    gap_len = 5
    curr_dist = 0
    angle = math.atan2(y2 - y1, x2 - x1)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    while curr_dist < total_dist:
        start_seg = curr_dist
        end_seg = min(curr_dist + dash_len, total_dist)
        draw.line([(x1 + start_seg * cos_a, y1 + start_seg * sin_a),
                   (x1 + end_seg * cos_a, y1 + end_seg * sin_a)], fill="#000000", width=width)
        curr_dist += dash_len + gap_len
    
    # Open arrowhead
    p1 = (x2 - arrow_size * math.cos(angle - math.pi / 6), y2 - arrow_size * math.sin(angle - math.pi / 6))
    p2 = (x2 - arrow_size * math.cos(angle + math.pi / 6), y2 - arrow_size * math.sin(angle + math.pi / 6))
    draw.line([end, p1], fill="#000000", width=width)
    draw.line([end, p2], fill="#000000", width=width)

def draw_uml_component(draw, box, name, stereotype="component", subtext=""):
    x1, y1, x2, y2 = box
    draw.rectangle(box, fill="#ffffff", outline="#000000", width=2)
    # UML component icon on top-right
    icon_w, icon_h = 24, 16
    ix, iy = x2 - icon_w - 8, y1 + 8
    draw.rectangle([ix, iy, ix + icon_w, iy + icon_h], fill="#ffffff", outline="#000000", width=1)
    draw.rectangle([ix - 4, iy + 3, ix + 2, iy + 6], fill="#ffffff", outline="#000000", width=1)
    draw.rectangle([ix - 4, iy + 9, ix + 2, iy + 12], fill="#ffffff", outline="#000000", width=1)
    
    # Text
    draw.text((x1 + 12, y1 + 10), f"«{stereotype}»", font=get_font(12, False), fill="#000000")
    draw.text((x1 + 12, y1 + 28), name, font=get_font(15, bold=True), fill="#000000")
    if subtext:
        draw.text((x1 + 12, y1 + 52), subtext, font=get_font(13), fill="#333333")

def draw_uml_node(draw, box, title, stereotype="device"):
    x1, y1, x2, y2 = box
    depth = 12
    # Front rect
    draw.rectangle([x1, y1 + depth, x2 - depth, y2], fill="#ffffff", outline="#000000", width=2)
    # Top face
    draw.polygon([(x1, y1 + depth), (x1 + depth, y1), (x2, y1), (x2 - depth, y1 + depth)], fill="#f0f0f0", outline="#000000")
    # Right face
    draw.polygon([(x2 - depth, y1 + depth), (x2, y1), (x2, y2 - depth), (x2 - depth, y2)], fill="#e4e4e4", outline="#000000")
    # Title
    draw.text((x1 + 14, y1 + depth + 8), f"«{stereotype}»", font=get_font(12), fill="#000000")
    draw.text((x1 + 14, y1 + depth + 26), title, font=get_font(15, bold=True), fill="#000000")

# ==============================================================================
# 1. Sơ đồ 5.1: UML Deployment & Component Diagram
# ==============================================================================
def generate_diagram_1():
    w, h = 1800, 950
    img = Image.new("RGB", (w, h), "#ffffff")
    draw = ImageDraw.Draw(img)

    # Outer border
    draw.rectangle([10, 10, w - 10, h - 10], outline="#000000", width=2)
    draw.text((30, 25), "UML Component & Deployment Diagram: Hệ thống VSign Commercial Platform", font=get_font(18, bold=True), fill="#000000")
    draw.line([10, 60, w - 10, 60], fill="#000000", width=1)

    # 1. Node: Customer Station
    draw_uml_node(draw, [40, 80, 560, 480], "Customer Workstation", stereotype="device")
    draw_uml_component(draw, [65, 160, 520, 245], "CustomerDisplay (/display)", stereotype="browser", subtext="Next-gen Web Kiosk, React 19")
    draw_uml_component(draw, [65, 265, 520, 350], "MediaPipeWorker", stereotype="web worker", subtext="@mediapipe/tasks-vision, trim-bodycrop-v1")
    draw_uml_component(draw, [65, 370, 520, 455], "WebRTCStreamer", stereotype="component", subtext="P2P MediaStream Producer")

    # 2. Node: Staff Station
    draw_uml_node(draw, [40, 520, 560, 910], "Staff Workstation", stereotype="device")
    draw_uml_component(draw, [65, 600, 520, 685], "StaffConsole (/recognize)", stereotype="browser", subtext="Operator Workspace, Web Speech STT/TTS")
    draw_uml_component(draw, [65, 705, 520, 790], "SentenceComposer", stereotype="component", subtext="Heuristic debouncer & Vietnamese grammar")
    draw_uml_component(draw, [65, 810, 520, 895], "WebRTCReceiver", stereotype="component", subtext="P2P MediaStream Consumer")

    # 3. Node: Application Server
    draw_uml_node(draw, [640, 80, 1160, 910], "Application Server (api.vsign.io.vn)", stereotype="server")
    draw_uml_component(draw, [670, 160, 1120, 255], "FastAPIGateway", stereotype="component", subtext="ASGI Router, Uvicorn, Python 3.11")
    draw_uml_component(draw, [670, 280, 1120, 375], "WebSocketHub (/ws/inference)", stereotype="component", subtext="Binary frame intake & session multiplexer")
    draw_uml_component(draw, [670, 400, 1120, 495], "CounterPairingManager", stereotype="component", subtext="PIN-6, QR generator & cookie authenticator")
    draw_uml_component(draw, [670, 520, 1120, 615], "Auth & SecurityService", stereotype="component", subtext="Argon2id hashing, HttpOnly session, HMAC-SHA256")
    draw_uml_component(draw, [670, 640, 1120, 735], "FailoverDispatcher", stereotype="component", subtext="Dynamic router: Modal GPU vs Local Core ML")
    draw_uml_component(draw, [670, 760, 1120, 855], "Persistence & AuditStore", stereotype="component", subtext="SQLite / PostgreSQL, telemetry without video")

    # 4. Node: Cloud GPU
    draw_uml_node(draw, [1240, 80, 1760, 480], "Modal Asia GPU Cluster", stereotype="cloud execution")
    draw_uml_component(draw, [1270, 170, 1720, 275], "MViTv2_S_InferenceEngine", stereotype="execution environment", subtext="PyTorch 2.4, CUDA 12, NVIDIA L4 24GB")
    draw_uml_component(draw, [1270, 310, 1720, 415], "SpatiotemporalModelCheckpoint", stereotype="artifact", subtext="sales30-mvitv2s-epoch36, 16 RGB frames")

    # 5. Node: Local Fallback
    draw_uml_node(draw, [1240, 520, 1760, 910], "Local Mac Counter Unit", stereotype="device")
    draw_uml_component(draw, [1270, 610, 1720, 715], "CoreML_InferenceEngine", stereotype="execution environment", subtext="Apple Silicon Neural Engine (port 8000)")
    draw_uml_component(draw, [1270, 750, 1720, 855], "CompiledCoreMLPackage", stereotype="artifact", subtext="MViTv2-S.mlpackage (< 15 ms latency)")

    # Connectors & Relationships
    # WebRTC P2P
    draw_arrow(draw, (520, 412), (520, 852), width=2)
    draw.text((530, 495), "«WebRTC P2P (LAN)»", font=get_font(12, bold=True), fill="#000000")
    draw.text((530, 515), "Direct Video Stream", font=get_font(12), fill="#000000")

    # Customer -> Backend WS
    draw_arrow(draw, (520, 202), (670, 327), width=2)
    draw.text((540, 245), "«WebSocket» 16 frames", font=get_font(12, bold=True), fill="#000000")

    # Staff -> Backend WS
    draw_arrow(draw, (520, 642), (670, 340), width=2)
    draw.text((535, 600), "«WebSocket» 2-way sync", font=get_font(12, bold=True), fill="#000000")

    # Backend -> Modal GPU
    draw_arrow(draw, (1120, 327), (1270, 222), width=2)
    draw.text((1135, 255), "«wss / gRPC» (Primary)", font=get_font(12, bold=True), fill="#000000")

    # Backend -> Core ML Fallback
    draw_open_arrow(draw, (1120, 677), (1270, 662), width=2, dashed=True)
    draw.text((1135, 690), "«HTTP / IPC» (Fallback 6s)", font=get_font(12, bold=True), fill="#000000")

    out_path = os.path.join(OUTPUT_DIR, "diagram_5_1_system_architecture.png")
    img.save(out_path, dpi=(300, 300))
    print(f"Generated B&W UML 5.1: {out_path}")

# ==============================================================================
# 2. Sơ đồ 5.2: UML Sequence Diagram (Sign Recognition & 2-Way Dialog)
# ==============================================================================
def generate_diagram_2():
    w, h = 1800, 900
    img = Image.new("RGB", (w, h), "#ffffff")
    draw = ImageDraw.Draw(img)

    draw.rectangle([10, 10, w - 10, h - 10], outline="#000000", width=2)
    draw.text((30, 25), "UML Sequence Diagram: Nhận dạng cử chỉ và điều phối hội thoại hai chiều", font=get_font(18, bold=True), fill="#000000")
    draw.line([10, 60, w - 10, 60], fill="#000000", width=1)

    # Lifelines
    actors = [
        ("Khách hàng", ":CustomerDisplay", 160),
        ("WebWorker", ":MediaPipeWorker", 440),
        ("Máy chủ GPU", ":InferenceServer", 760),
        ("Bộ ghép câu", ":SentenceComposer", 1080),
        ("Nhân viên", ":StaffConsole", 1400),
        ("Âm thanh / TTS", ":WebSpeechAPI", 1660)
    ]

    top_y = 90
    bottom_y = 860

    for role, name, x in actors:
        # Header box
        box_w, box_h = 180, 50
        draw.rectangle([x - box_w//2, top_y, x + box_w//2, top_y + box_h], fill="#f5f5f5", outline="#000000", width=2)
        draw.text((x - box_w//2 + 10, top_y + 8), role, font=get_font(13), fill="#000000")
        draw.text((x - box_w//2 + 10, top_y + 26), name, font=get_font(14, bold=True), fill="#000000")
        
        # Dashed lifeline
        cur_y = top_y + box_h
        while cur_y < bottom_y:
            draw.line([(x, cur_y), (x, min(cur_y + 8, bottom_y))], fill="#888888", width=1)
            cur_y += 14

    # Sequence Messages
    y = 175
    step_y = 58

    # 1. performSign
    draw_arrow(draw, (160, y), (440, y), width=2)
    draw.text((180, y - 22), "1: performSign() -> captureFrames(30fps)", font=get_font(13, bold=True), fill="#000000")
    
    # 2. extractLandmarks
    y += step_y
    draw_arrow(draw, (440, y), (440, y + 30), width=2)
    draw.text((455, y - 5), "2: extractLandmarks(21 hand + 11 body)", font=get_font(13), fill="#000000")
    
    # 3. cropBodyROI
    y += step_y
    draw_open_arrow(draw, (440, y), (160, y), width=2, dashed=True)
    draw.text((180, y - 22), "3: return 16_RGB_frames (trim-bodycrop-v1)", font=get_font(13), fill="#000000")

    # 4. sendWebSocket
    y += step_y
    draw_arrow(draw, (160, y), (760, y), width=2)
    draw.text((280, y - 22), "4: sendBinaryFrames(16 x 224 x 224) [WebSocket]", font=get_font(13, bold=True), fill="#000000")

    # 5. predictWord
    y += step_y
    draw_arrow(draw, (760, y), (1080, y), width=2)
    draw.text((780, y - 22), "5: emitProbDistribution() [prob >= 0.40, margin=0.0]", font=get_font(13, bold=True), fill="#000000")

    # 6. debounce & concat
    y += step_y
    draw_arrow(draw, (1080, y), (1080, y + 30), width=2)
    draw.text((1095, y - 5), "6: debounce(1000ms) & composeSentence()", font=get_font(13), fill="#000000")

    # 7. emitSentence to Staff
    y += step_y
    draw_arrow(draw, (1080, y), (1400, y), width=2)
    draw.text((1110, y - 22), "7: renderSentence(draft_text, raw_tokens)", font=get_font(13, bold=True), fill="#000000")

    # 8. speakTTS
    y += step_y
    draw_arrow(draw, (1400, y), (1660, y), width=2)
    draw.text((1420, y - 22), "8: speakSpeech(VietnameseText)", font=get_font(13), fill="#000000")

    # 9. staffReply
    y += step_y
    draw_arrow(draw, (1400, y), (160, y), width=2)
    draw.text((620, y - 22), "9: sendOperatorReply(STT_voice / KeyboardText) [WebSocket]", font=get_font(13, bold=True), fill="#000000")

    # 10. displayCustomer
    y += step_y
    draw_arrow(draw, (160, y), (160, y + 25), width=2)
    draw.text((175, y - 5), "10: renderLargeCustomerText()", font=get_font(13), fill="#000000")

    out_path = os.path.join(OUTPUT_DIR, "diagram_5_2_sequence_data_flow.png")
    img.save(out_path, dpi=(300, 300))
    print(f"Generated B&W UML 5.2: {out_path}")

# ==============================================================================
# 3. Sơ đồ 5.3: UML Sequence Diagram (Counter Pairing & WebRTC Handshake)
# ==============================================================================
def generate_diagram_3():
    w, h = 1800, 850
    img = Image.new("RGB", (w, h), "#ffffff")
    draw = ImageDraw.Draw(img)

    draw.rectangle([10, 10, w - 10, h - 10], outline="#000000", width=2)
    draw.text((30, 25), "UML Sequence Diagram: Quy trình ghép nối quầy giao dịch và thiết lập WebRTC", font=get_font(18, bold=True), fill="#000000")
    draw.line([10, 60, w - 10, 60], fill="#000000", width=1)

    actors = [
        ("Nhân viên quầy", ":StaffConsole", 200),
        ("Máy chủ API", ":FastAPIBackend", 650),
        ("Màn hình khách", ":CustomerDisplay", 1150),
        ("Máy chủ STUN", ":GoogleSTUN", 1600)
    ]

    top_y = 90
    bottom_y = 810

    for role, name, x in actors:
        box_w, box_h = 200, 50
        draw.rectangle([x - box_w//2, top_y, x + box_w//2, top_y + box_h], fill="#f5f5f5", outline="#000000", width=2)
        draw.text((x - box_w//2 + 15, top_y + 8), role, font=get_font(13), fill="#000000")
        draw.text((x - box_w//2 + 15, top_y + 26), name, font=get_font(14, bold=True), fill="#000000")
        
        cur_y = top_y + box_h
        while cur_y < bottom_y:
            draw.line([(x, cur_y), (x, min(cur_y + 8, bottom_y))], fill="#888888", width=1)
            cur_y += 14

    y = 175
    step_y = 58

    # 1. requestPairing
    draw_arrow(draw, (200, y), (650, y), width=2)
    draw.text((250, y - 22), "1: requestNewCounterPairing(counter_id)", font=get_font(13, bold=True), fill="#000000")

    # 2. returnPIN
    y += step_y
    draw_open_arrow(draw, (650, y), (200, y), width=2, dashed=True)
    draw.text((250, y - 22), "2: returnPairingPayload(PIN_6_digits, QR_token, TTL=10m)", font=get_font(13), fill="#000000")

    # 3. submitPairing
    y += step_y
    draw_arrow(draw, (1150, y), (650, y), width=2)
    draw.text((720, y - 22), "3: submitPairingRequest(PIN_input / QR_scan)", font=get_font(13, bold=True), fill="#000000")

    # 4. showConfirmCode to both
    y += step_y
    draw_arrow(draw, (650, y), (200, y), width=2)
    draw.text((280, y - 22), "4a: notifyAttempt(confirm_code_2_chars)", font=get_font(13), fill="#000000")
    draw_arrow(draw, (650, y), (1150, y), width=2)
    draw.text((750, y - 22), "4b: displayConfirmCode(confirm_code_2_chars)", font=get_font(13), fill="#000000")

    # 5. confirmPairing
    y += step_y
    draw_arrow(draw, (200, y), (650, y), width=2)
    draw.text((280, y - 22), "5: confirmMatchingCode(status=VERIFIED)", font=get_font(13, bold=True), fill="#000000")

    # 6. setPermanentCookie
    y += step_y
    draw_open_arrow(draw, (650, y), (1150, y), width=2, dashed=True)
    draw.text((720, y - 22), "6: setCookie('vsign_display', permanent=true) -> enterKioskMode()", font=get_font(13), fill="#000000")

    # 7. queryICE
    y += step_y
    draw_arrow(draw, (1150, y), (1600, y), width=2)
    draw.text((1200, y - 22), "7: queryIceCandidates() [Google STUN]", font=get_font(13), fill="#000000")

    # 8. exchangeSDP
    y += step_y
    draw_arrow(draw, (1150, y), (200, y), width=2)
    draw.text((500, y - 22), "8: exchangeSDPOfferAnswer() [via WebSocket Hub]", font=get_font(13, bold=True), fill="#000000")

    # 9. P2P video stream
    y += step_y
    draw_arrow(draw, (1150, y), (200, y), width=3)
    draw.text((450, y - 22), "9: streamWebRTCVideo(DTLS/SRTP, Peer-to-Peer in LAN)", font=get_font(13, bold=True), fill="#000000")

    out_path = os.path.join(OUTPUT_DIR, "diagram_5_3_counter_pairing_webrtc.png")
    img.save(out_path, dpi=(300, 300))
    print(f"Generated B&W UML 5.3: {out_path}")

# ==============================================================================
# 4. Sơ đồ 5.4: UML Activity Diagram (MLOps Lifecycle)
# ==============================================================================
def generate_diagram_4():
    w, h = 1800, 850
    img = Image.new("RGB", (w, h), "#ffffff")
    draw = ImageDraw.Draw(img)

    draw.rectangle([10, 10, w - 10, h - 10], outline="#000000", width=2)
    draw.text((30, 25), "UML Activity Diagram: Vòng đời dữ liệu, huấn luyện và quản lý mô hình MViTv2-S", font=get_font(18, bold=True), fill="#000000")
    draw.line([10, 60, w - 10, 60], fill="#000000", width=1)

    # Activity Helper
    def draw_activity(box, title, subtitle=""):
        draw.rounded_rectangle(box, radius=12, fill="#ffffff", outline="#000000", width=2)
        x1, y1, x2, y2 = box
        draw.text((x1 + 15, y1 + 12), title, font=get_font(14, bold=True), fill="#000000")
        if subtitle:
            draw.text((x1 + 15, y1 + 32), subtitle, font=get_font(12), fill="#444444")

    # Decision Diamond Helper
    def draw_decision(center, size, label):
        cx, cy = center
        pts = [(cx, cy - size), (cx + size, cy), (cx, cy + size), (cx - size, cy)]
        draw.polygon(pts, fill="#ffffff", outline="#000000")
        draw.text((cx - size + 10, cy - 8), label, font=get_font(11, bold=True), fill="#000000")

    # Start Node (Solid circle)
    draw.ellipse([60, 230, 90, 260], fill="#000000")
    draw_arrow(draw, (90, 245), (140, 245), width=2)

    # Activity 1: Collect Data
    draw_activity([140, 215, 380, 275], "1. Thu thập dữ liệu đa nguồn", "Kaggle VSL v2, Webcam quầy")
    draw_arrow(draw, (380, 245), (430, 245), width=2)

    # Activity 2: Filter Sales-30 & Body Crop
    draw_activity([430, 215, 680, 275], "2. Tiền xử lý & Cắt ROI", "trim-bodycrop-v1, 16 RGB 224x224")
    draw_arrow(draw, (680, 245), (730, 245), width=2)

    # Activity 3: Signer-independent Split
    draw_activity([730, 215, 970, 275], "3. Phân chia độc lập người ký", "Train / Val / Held-out Test")
    draw_arrow(draw, (970, 245), (1020, 245), width=2)

    # Activity 4: Train GPU
    draw_activity([1020, 215, 1270, 275], "4. Huấn luyện mô hình GPU", "MViTv2-S Spatiotemporal (PyTorch)")
    draw_arrow(draw, (1270, 245), (1320, 245), width=2)

    # Activity 5: Independent Evaluation
    draw_activity([1320, 215, 1570, 275], "5. Đánh giá đối chuẩn độc lập", "Test standing (N=351 clip)")
    draw_arrow(draw, (1570, 245), (1630, 245), width=2)

    # Decision Node
    draw_decision((1670, 245), 40, "Đạt chuẩn?")

    # Branch NO: Loop back to train
    draw.line([(1670, 205), (1670, 130), (1145, 130)], fill="#000000", width=2)
    draw_arrow(draw, (1145, 130), (1145, 215), width=2)
    draw.text((1680, 160), "[Không: Acc < 95% / FA > 2%]", font=get_font(12, bold=True), fill="#000000")

    # Branch YES: Proceed to packaging
    draw_arrow(draw, (1670, 285), (1670, 420), width=2)
    draw.text((1680, 340), "[Có: Acc >= 95%]", font=get_font(12, bold=True), fill="#000000")

    # Activity 6: Package Multi-Runtime
    draw_activity([1480, 420, 1750, 480], "6. Đóng gói đa môi trường", "Modal GPU & Apple Core ML")
    draw_arrow(draw, (1480, 450), (1280, 450), width=2)

    # Activity 7: Approval Gate
    draw_activity([1020, 420, 1280, 480], "7. Cổng duyệt độc lập (Approval)", "Admin phê duyệt thủ công")
    draw_arrow(draw, (1020, 450), (820, 450), width=2)

    # Activity 8: Active Pointer
    draw_activity([560, 420, 820, 480], "8. Chuyển Active Pointer 0s", "Production Serving + Rollback")
    draw_arrow(draw, (560, 450), (380, 450), width=2)

    # Final Node (Bullseye)
    draw.ellipse([340, 435, 370, 465], fill="#ffffff", outline="#000000", width=2)
    draw.ellipse([347, 442, 363, 458], fill="#000000")
    draw.text((250, 442), "Hoàn tất triển khai", font=get_font(12, bold=True), fill="#000000")

    # Governance rule notes
    box_n = [40, 580, w - 40, 810]
    draw.rectangle(box_n, fill="#fbfbfb", outline="#000000", width=1)
    draw.text((60, 600), "RÀNG BUỘC KIỂM TOÁN CHUẨN UML CHO ĐƯỜNG ỐNG AI (AI GOVERNANCE CONSTRAINTS):", font=get_font(15, bold=True), fill="#000000")
    rules = [
        "«precondition» Dữ liệu tập kiểm thử Held-out Test hoàn toàn bất biến (Frozen Snapshot), người ký không lặp lại giữa Train và Test.",
        "«invariant» Không tự động triển khai (Zero Unattended Deploy): Bắt buộc kiểm tra độ chính xác trên tập Test trước khi mở Approval Gate.",
        "«postcondition» Đóng gói sẵn sàng trên cả 2 runtime: Container Modal GPU (PyTorch CUDA) và Apple Silicon Core ML Package (.mlpackage).",
        "«rollback» Cơ chế Active Pointer cho phép chuyển đổi ngay lập tức (0 giây) và hoàn tác về checkpoint trước đó nếu phát hiện lỗi tại quầy."
    ]
    y_r = 635
    for r in rules:
        draw.text((60, y_r), r, font=get_font(13), fill="#222222")
        y_r += 40

    out_path = os.path.join(OUTPUT_DIR, "diagram_5_4_ml_pipeline_lifecycle.png")
    img.save(out_path, dpi=(300, 300))
    print(f"Generated B&W UML 5.4: {out_path}")

if __name__ == "__main__":
    generate_diagram_1()
    generate_diagram_2()
    generate_diagram_3()
    generate_diagram_4()
    print("All 4 B&W UML diagrams generated successfully!")
