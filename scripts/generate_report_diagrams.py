# -*- coding: utf-8 -*-
"""
Generate Academic Standard Technical Diagrams for VSign Report.
Pure white background, clean borders, professional typography, NO presentation banner headers.
Matches Vietnamese academic thesis standards (Sơ đồ kỹ thuật chuẩn luận văn).
"""

import os
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

def draw_rounded_card(draw, box, fill="#ffffff", outline="#94a3b8", width=2, radius=10):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

def draw_arrow(draw, start, end, color="#2563eb", width=3, arrow_size=10):
    import math
    x1, y1 = start
    x2, y2 = end
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - arrow_size * math.cos(angle - math.pi / 6), y2 - arrow_size * math.sin(angle - math.pi / 6))
    p2 = (x2 - arrow_size * math.cos(angle + math.pi / 6), y2 - arrow_size * math.sin(angle + math.pi / 6))
    draw.polygon([end, p1, p2], fill=color)

# ==============================================================================
# Diagram 1: System Architecture (Academic Standard)
# ==============================================================================
def generate_diagram_1():
    w, h = 1800, 950
    img = Image.new("RGB", (w, h), "#ffffff")
    draw = ImageDraw.Draw(img)

    # Outer border
    draw.rectangle([10, 10, w - 10, h - 10], outline="#cbd5e1", width=2)

    # Sub-header bar
    draw.rectangle([10, 10, w - 10, 55], fill="#f1f5f9", outline="#cbd5e1", width=1)
    draw.text((30, 20), "KIẾN TRÚC HỆ THỐNG VSIGN: PHÂN BỔ MÔ HÌNH DỊCH VỤ QUẦY VÀ SUY LUẬN AI MÁY CHỦ GPU", font=get_font(18, bold=True), fill="#0f172a")

    # Column 1: Client Devices
    col1 = [35, 75, 570, 920]
    draw_rounded_card(draw, col1, fill="#f8fafc", outline="#3b82f6", width=2, radius=12)
    # Header box
    draw_rounded_card(draw, [35, 75, 570, 125], fill="#eff6ff", outline="#3b82f6", width=2, radius=12)
    draw.rectangle([35, 110, 570, 125], fill="#eff6ff")
    draw.text((55, 90), "TẦNG THIẾT BỊ MÁY TRẠM QUẦY (CLIENT)", font=get_font(17, bold=True), fill="#1e3a8a")

    # Subcard 1A: Customer Display
    draw_rounded_card(draw, [55, 145, 550, 500], fill="#ffffff", outline="#60a5fa", width=2, radius=8)
    draw.text((75, 160), "Màn hình khách tại quầy (/display)", font=get_font(16, bold=True), fill="#1d4ed8")
    lines_1a = [
        "• Chế độ Kiosk toàn màn hình (không cần đăng nhập)",
        "• Camera 30 fps thu nhận chuyển động thân người",
        "• Web Worker: MediaPipe bám 21 mốc tay + 11 mốc thân",
        "• Thuật toán trim-bodycrop-v1: Căn 2 vai, cắt ROI",
        "• Đóng gói chuỗi 16 khung hình RGB (224 x 224 pixel)",
        "• WebRTC MediaStream: Gửi luồng video sang NV (LAN)",
        "• Hiển thị: Gương tự soi, từ nhận diện và phản hồi NV"
    ]
    y = 195
    for l in lines_1a:
        draw.text((75, y), l, font=get_font(14), fill="#1e293b")
        y += 38

    # Subcard 1B: Staff Console
    draw_rounded_card(draw, [55, 520, 550, 900], fill="#ffffff", outline="#4ade80", width=2, radius=8)
    draw.text((75, 535), "Bàn làm việc nhân viên (/recognize)", font=get_font(16, bold=True), fill="#15803d")
    lines_1b = [
        "• Xác thực tài khoản quầy (Operator / Admin)",
        "• Nhận luồng video khách qua WebRTC P2P nội bộ",
        "• BackendLocationBadge: Giám sát Modal GPU / Core ML",
        "• Sentence Composer rảnh tay: Tự động ngắt câu, nối 'và'",
        "• Web Speech API (TTS): Đọc to câu tiếng Việt qua loa",
        "• Web Speech API (STT) & Bàn phím: Nhập phản hồi",
        "• WebSocket: Đồng bộ câu trả lời sang màn hình khách"
    ]
    y = 570
    for l in lines_1b:
        draw.text((75, y), l, font=get_font(14), fill="#1e293b")
        y += 42

    # Column 2: Communications & Gateway
    col2 = [620, 75, 1180, 920]
    draw_rounded_card(draw, col2, fill="#f8fafc", outline="#64748b", width=2, radius=12)
    draw_rounded_card(draw, [620, 75, 1180, 125], fill="#f1f5f9", outline="#64748b", width=2, radius=12)
    draw.rectangle([620, 110, 1180, 125], fill="#f1f5f9")
    draw.text((640, 90), "TẦNG TRUYỀN THÔNG & MÁY CHỦ DỊCH VỤ", font=get_font(17, bold=True), fill="#0f172a")

    # Card 2A: Protocols
    draw_rounded_card(draw, [640, 145, 1160, 460], fill="#ffffff", outline="#94a3b8", width=2, radius=8)
    draw.text((660, 160), "Giao thức truyền thông thời gian thực", font=get_font(16, bold=True), fill="#334155")
    lines_2a = [
        "1. Kênh WebRTC P2P (Video Stream):",
        "   - Đi trực tiếp ngang hàng giữa 2 laptop trong mạng LAN",
        "   - Đàm phán ICE Candidate qua Google STUN",
        "   - Tuyệt đối không tiêu tốn băng thông máy chủ",
        "2. Kênh WebSocket bảo mật (wss://.../ws/inference):",
        "   - Truyền gói tin 16 frame RGB nhị phân lên server GPU",
        "   - Nhận nhãn dự đoán và xác suất tin cậy thời gian thực",
        "3. Tuyến bảo mật Cloudflare Tunnel (api.vsign.io.vn):",
        "   - Bảo vệ máy chủ nội bộ, không mở cổng router"
    ]
    y = 195
    for l in lines_2a:
        draw.text((660, y), l, font=get_font(14), fill="#1e293b")
        y += 28

    # Card 2B: FastAPI Backend
    draw_rounded_card(draw, [640, 480, 1160, 900], fill="#ffffff", outline="#c084fc", width=2, radius=8)
    draw.text((660, 495), "Máy chủ ứng dụng trung tâm (FastAPI Backend)", font=get_font(16, bold=True), fill="#7e22ce")
    lines_2b = [
        "• Quản lý phiên làm việc đa quầy & điều phối WebSocket Hub",
        "• Bộ điều phối luồng: Debounce 1.000 ms, Heuristic nghỉ 1.800 ms",
        "• Ghép đôi an toàn: Sinh mã PIN 6 số + QR (TTL 10 phút)",
        "• Phân quyền RBAC, băm mật khẩu Argon2id, Cookie HttpOnly",
        "• Ký số Webhook HMAC SHA-256 tích hợp hệ thống POS",
        "• Lưu trữ cơ sở dữ liệu quầy, tài khoản và audit telemetry",
        "• Dynamic Failover: Tự động chuyển đổi giữa Modal GPU",
        "  và Local Core ML trong 6s khi có sự cố mạng Internet"
    ]
    y = 530
    for l in lines_2b:
        draw.text((660, y), l, font=get_font(14), fill="#1e293b")
        y += 42

    # Column 3: AI Inference Server
    col3 = [1230, 75, 1765, 920]
    draw_rounded_card(draw, col3, fill="#f8fafc", outline="#f97316", width=2, radius=12)
    draw_rounded_card(draw, [1230, 75, 1765, 125], fill="#fff7ed", outline="#f97316", width=2, radius=12)
    draw.rectangle([1230, 110, 1765, 125], fill="#fff7ed")
    draw.text((1250, 90), "HẠ TẦNG SUY LUẬN AI MÁY CHỦ (SERVER GPU)", font=get_font(17, bold=True), fill="#c2410c")

    # Card 3A: Modal GPU
    draw_rounded_card(draw, [1250, 145, 1745, 520], fill="#ffffff", outline="#fb923c", width=2, radius=8)
    draw.text((1270, 160), "Cụm Cloud GPU Đông Nam Á (Asia Modal GPU)", font=get_font(16, bold=True), fill="#ea580c")
    lines_3a = [
        "• Trung tâm dữ liệu: Singapore / Đông Nam Á (ap-south)",
        "• Phần cứng: NVIDIA L4 / A10 Tensor Core GPU 24GB",
        "• Môi trường: Linux Container, PyTorch 2.4 CUDA 12",
        "• Mô hình: MViTv2-S Spatiotemporal Video Transformer",
        "• Checkpoint: sales30-mvitv2s-personal-v3-epoch36",
        "• Thời gian suy luận GPU thuần: 35 - 65 ms / 16 frame",
        "• Tổng độ trễ toàn chu trình khu vực: 150 - 220 ms",
        "• Riêng tư: 16 frame chỉ giải mã trong RAM GPU, KHÔNG lưu đĩa"
    ]
    y = 195
    for l in lines_3a:
        draw.text((1270, y), l, font=get_font(14), fill="#1e293b")
        y += 37

    # Card 3B: Apple Core ML
    draw_rounded_card(draw, [1250, 540, 1745, 900], fill="#ffffff", outline="#f472b6", width=2, radius=8)
    draw.text((1270, 555), "Dự phòng tại chỗ máy Mac (Apple Core ML)", font=get_font(16, bold=True), fill="#db2777")
    lines_3b = [
        "• Vị trí: Máy Mac quầy bán hàng POS (port 8000)",
        "• Phần cứng: Apple Silicon Neural Engine (ANE)",
        "• Định dạng mô hình: MViTv2-S Core ML (.mlpackage)",
        "• Thời gian suy luận cực nhanh: < 15 ms / mẫu 16 frame",
        "• Vận hành 100% Offline khi mất Internet quốc tế",
        "• Tự động đồng bộ telemetry khi mạng Internet phục hồi",
        "• Giữ vững trải nghiệm khách hàng tại quầy không gián đoạn"
    ]
    y = 590
    for l in lines_3b:
        draw.text((1270, y), l, font=get_font(14), fill="#1e293b")
        y += 40

    # Clean directional connectors
    draw_arrow(draw, (550, 240), (640, 240), color="#3b82f6", width=2)
    draw_arrow(draw, (640, 280), (550, 280), color="#22c55e", width=2)
    draw_arrow(draw, (550, 680), (640, 680), color="#8b5cf6", width=2)
    draw_arrow(draw, (1160, 310), (1250, 310), color="#ea580c", width=2)
    draw_arrow(draw, (1160, 720), (1250, 720), color="#db2777", width=2)

    out_path = os.path.join(OUTPUT_DIR, "diagram_5_1_system_architecture.png")
    img.save(out_path, dpi=(300, 300))
    print(f"Generated clean academic: {out_path}")

# ==============================================================================
# Diagram 2: Sequence Data Flow (Academic Standard)
# ==============================================================================
def generate_diagram_2():
    w, h = 1800, 800
    img = Image.new("RGB", (w, h), "#ffffff")
    draw = ImageDraw.Draw(img)

    draw.rectangle([10, 10, w - 10, h - 10], outline="#cbd5e1", width=2)
    draw.rectangle([10, 10, w - 10, 55], fill="#f1f5f9", outline="#cbd5e1", width=1)
    draw.text((30, 20), "QUY TRÌNH 8 BƯỚC XỬ LÝ NHẬN DẠNG CỬ CHỈ VIDEO VÀ ĐIỀU PHỐI HỘI THOẠI HAI CHIỀU", font=get_font(18, bold=True), fill="#0f172a")

    steps = [
        {"num": "1", "title": "Thu nhận video", "loc": "Camera quầy khách", "desc": "30 fps liên tục\nGóc bao quát từ\nthắt lưng lên đầu", "color": "#0284c7"},
        {"num": "2", "title": "Bám bắt mốc", "loc": "MediaPipe Worker", "desc": "21 mốc bàn tay\n11 mốc thân trên\nWeb Worker ngầm", "color": "#0369a1"},
        {"num": "3", "title": "Cắt & Lấy mẫu", "loc": "Thuật toán máy khách", "desc": "trim-bodycrop-v1\n16 khung hình RGB\n224 x 224 pixel", "color": "#0d9488"},
        {"num": "4", "title": "Suy luận AI GPU", "loc": "Asia Modal GPU", "desc": "MViTv2-S Video 3D\nNVIDIA L4 PyTorch\nNgưỡng tin cậy 40%", "color": "#d97706"},
        {"num": "5", "title": "Chống ghi lặp", "loc": "Backend Controller", "desc": "Debounce 1.000 ms\nNghỉ từ 1.800 ms\nNgắt câu sau 5.000 ms", "color": "#ea580c"},
        {"num": "6", "title": "Ghép câu tự động", "loc": "Sentence Composer", "desc": "Chuẩn hóa thứ tự\nNối từ 'và'\nTự động ngắt câu", "color": "#9333ea"},
        {"num": "7", "title": "Hiển thị & TTS", "loc": "Màn hình nhân viên", "desc": "Hiện từ gốc + câu\nWeb Speech API\nĐọc to qua loa NV", "color": "#16a34a"},
        {"num": "8", "title": "NV phản hồi", "loc": "Màn hình khách", "desc": "Nhân viên nói (STT)\nhoặc gõ bàn phím\nHiện chữ lớn /display", "color": "#2563eb"}
    ]

    card_w = 195
    card_h = 420
    start_x = 35
    y_top = 85

    for i, s in enumerate(steps):
        x = start_x + i * (card_w + 25)
        draw_rounded_card(draw, [x, y_top, x + card_w, y_top + card_h], fill="#ffffff", outline=s["color"], width=2, radius=8)
        
        # Step header bar
        draw_rounded_card(draw, [x, y_top, x + card_w, y_top + 50], fill="#f8fafc", outline=s["color"], width=1, radius=8)
        draw.rectangle([x, y_top + 30, x + card_w, y_top + 50], fill="#f8fafc")
        
        draw.ellipse([x + 12, y_top + 10, x + 42, y_top + 40], fill=s["color"])
        draw.text((x + 21, y_top + 14), s["num"], font=get_font(16, bold=True), fill="#ffffff")
        draw.text((x + 50, y_top + 16), f"BƯỚC {s['num']}", font=get_font(14, bold=True), fill=s["color"])

        draw.text((x + 12, y_top + 65), s["title"], font=get_font(16, bold=True), fill="#0f172a")
        draw.text((x + 12, y_top + 95), s["loc"], font=get_font(13, bold=True), fill="#64748b")
        draw.line([x + 12, y_top + 120, x + card_w - 12, y_top + 120], fill="#cbd5e1", width=1)

        y_d = y_top + 135
        for line in s["desc"].split("\n"):
            draw.text((x + 12, y_d), line, font=get_font(14), fill="#334155")
            y_d += 28

        if i < len(steps) - 1:
            draw_arrow(draw, (x + card_w + 3, y_top + card_h // 2), (x + card_w + 22, y_top + card_h // 2), color="#64748b", width=2, arrow_size=8)

    # Bottom Latency Box
    lat_box = [35, 540, w - 35, 765]
    draw_rounded_card(draw, lat_box, fill="#f8fafc", outline="#cbd5e1", width=2, radius=8)
    draw.text((60, 560), "PHÂN TÍCH ĐỘ TRỄ THỜI GIAN THỰC TOÀN CHU TRÌNH (END-TO-END LATENCY BREAKDOWN):", font=get_font(16, bold=True), fill="#0f172a")

    metrics = [
        ("Thu mẫu 16 frames", "533 ms (ở 30 fps)", "#0284c7"),
        ("MediaPipe & Cắt ROI", "15 - 25 ms", "#0d9488"),
        ("Truyền mạng WebSocket", "35 - 50 ms", "#d97706"),
        ("Suy luận GPU (MViTv2-S)", "35 - 65 ms (Modal) / <15 ms (Core ML)", "#ea580c"),
        ("Ghép câu tự động", "< 20 ms", "#9333ea"),
        ("Tổng độ trễ toàn luồng", "150 - 220 ms (sau khi dứt cử chỉ)", "#16a34a")
    ]
    x_m = 60
    y_m = 600
    for title, val, col in metrics:
        draw_rounded_card(draw, [x_m, y_m, x_m + 265, y_m + 135], fill="#ffffff", outline=col, width=2, radius=6)
        draw.text((x_m + 12, y_m + 15), title, font=get_font(13, bold=True), fill="#64748b")
        draw.text((x_m + 12, y_m + 45), val, font=get_font(14, bold=True), fill=col)
        x_m += 285

    out_path = os.path.join(OUTPUT_DIR, "diagram_5_2_sequence_data_flow.png")
    img.save(out_path, dpi=(300, 300))
    print(f"Generated clean academic: {out_path}")

# ==============================================================================
# Diagram 3: Counter Pairing & WebRTC Handshake (Academic Standard)
# ==============================================================================
def generate_diagram_3():
    w, h = 1800, 850
    img = Image.new("RGB", (w, h), "#ffffff")
    draw = ImageDraw.Draw(img)

    draw.rectangle([10, 10, w - 10, h - 10], outline="#cbd5e1", width=2)
    draw.rectangle([10, 10, w - 10, 55], fill="#f1f5f9", outline="#cbd5e1", width=1)
    draw.text((30, 20), "QUY TRÌNH GHÉP NỐI QUẦY GIAO DỊCH VÀ THIẾT LẬP KẾT NỐI WEBRTC NGANG HÀNG", font=get_font(18, bold=True), fill="#0f172a")

    phases = [
        {
            "num": "GIAI ĐOẠN 1",
            "title": "Khởi tạo yêu cầu quầy",
            "actor": "Máy nhân viên (/settings)",
            "points": [
                "1. Nhân viên nhấn 'Thêm màn hình quầy'",
                "2. Backend sinh mã counter_id",
                "3. Tạo mã PIN ngẫu nhiên 6 chữ số",
                "4. Tạo mã QR chứa link ghép đôi",
                "5. Thiết lập thời gian sống TTL = 10 phút"
            ],
            "color": "#2563eb"
        },
        {
            "num": "GIAI ĐOẠN 2",
            "title": "Kết nối máy khách",
            "actor": "Máy khách (/display)",
            "points": [
                "1. Máy khách mở trình duyệt /display",
                "2. Nhập mã PIN 6 số hoặc quét QR",
                "3. Gửi yêu cầu xác thực lên Backend",
                "4. Backend xác thực mã PIN và TTL",
                "5. Sinh mã đối chiếu an toàn 2 ký tự"
            ],
            "color": "#7c3aed"
        },
        {
            "num": "GIAI ĐOẠN 3",
            "title": "Xác nhận & Cấp Cookie",
            "actor": "Nhân viên & Khách hàng",
            "points": [
                "1. Hai máy hiển thị mã đối chiếu 2 ký tự",
                "2. Nhân viên kiểm tra và nhấn 'Xác nhận'",
                "3. Máy khách nhận cookie 'vsign_display'",
                "4. Cookie có giá trị vĩnh viễn cho quầy",
                "5. Chuyển sang chế độ Kiosk toàn màn hình"
            ],
            "color": "#059669"
        },
        {
            "num": "GIAI ĐOẠN 4",
            "title": "Thiết lập WebRTC P2P",
            "actor": "Hai trình duyệt trong mạng LAN",
            "points": [
                "1. Trao đổi SDP Offer / Answer qua WS",
                "2. Truy vấn ICE Candidate qua Google STUN",
                "3. Thiết lập kết nối ngang hàng P2P",
                "4. Truyền luồng video khách -> máy nhân viên",
                "5. Luồng video chạy nội bộ, 0% tốn server"
            ],
            "color": "#d97706"
        }
    ]

    card_w = 405
    card_h = 470
    y_top = 85
    start_x = 35

    for i, p in enumerate(phases):
        x = start_x + i * (card_w + 35)
        draw_rounded_card(draw, [x, y_top, x + card_w, y_top + card_h], fill="#ffffff", outline=p["color"], width=2, radius=8)

        draw_rounded_card(draw, [x, y_top, x + card_w, y_top + 60], fill="#f8fafc", outline=p["color"], width=1, radius=8)
        draw.rectangle([x, y_top + 40, x + card_w, y_top + 60], fill="#f8fafc")
        
        draw.text((x + 15, y_top + 10), p["num"], font=get_font(12, bold=True), fill=p["color"])
        draw.text((x + 15, y_top + 30), p["title"], font=get_font(16, bold=True), fill="#0f172a")

        draw.text((x + 15, y_top + 75), f"Thực hiện: {p['actor']}", font=get_font(13, bold=True), fill="#64748b")
        draw.line([x + 15, y_top + 100, x + card_w - 15, y_top + 100], fill="#cbd5e1", width=1)

        y_pt = y_top + 120
        for pt in p["points"]:
            draw.text((x + 15, y_pt), pt, font=get_font(14), fill="#1e293b")
            y_pt += 42

        if i < len(phases) - 1:
            draw_arrow(draw, (x + card_w + 5, y_top + card_h // 2), (x + card_w + 30, y_top + card_h // 2), color="#64748b", width=2, arrow_size=9)

    # Highlights
    box_b = [35, 590, w - 35, 815]
    draw_rounded_card(draw, box_b, fill="#f8fafc", outline="#cbd5e1", width=2, radius=8)
    draw.text((60, 610), "ƯU ĐIỂM BẢO MẬT VÀ TÍNH TIỆN DỤNG CỦA CƠ CHẾ GHÉP NỐI QUẦY:", font=get_font(16, bold=True), fill="#0f172a")

    advs = [
        "1. Trải nghiệm rảnh tay cho khách: Khách hàng không cần đăng ký tài khoản hay chạm tay vào màn hình quầy.",
        "2. Tự phục hồi kết nối: Khi máy tính quầy khởi động lại, cookie bảo mật tự động tái lập phiên làm việc đúng quầy.",
        "3. Mã hóa luồng video ngang hàng: Dòng video WebRTC được mã hóa DTLS/SRTP end-to-end, không truyền ra Internet.",
        "4. Cơ chế chống nhầm lẫn: Khi mất mạng quá 1.5 giây, video tự động ẩn để tránh nhân viên nhận dạng sai cử chỉ cũ."
    ]
    y_adv = 650
    for adv in advs:
        draw.text((60, y_adv), adv, font=get_font(14), fill="#334155")
        y_adv += 35

    out_path = os.path.join(OUTPUT_DIR, "diagram_5_3_counter_pairing_webrtc.png")
    img.save(out_path, dpi=(300, 300))
    print(f"Generated clean academic: {out_path}")

# ==============================================================================
# Diagram 4: ML Pipeline Lifecycle (Academic Standard)
# ==============================================================================
def generate_diagram_4():
    w, h = 1800, 880
    img = Image.new("RGB", (w, h), "#ffffff")
    draw = ImageDraw.Draw(img)

    draw.rectangle([10, 10, w - 10, h - 10], outline="#cbd5e1", width=2)
    draw.rectangle([10, 10, w - 10, 55], fill="#f1f5f9", outline="#cbd5e1", width=1)
    draw.text((30, 20), "ĐƯỜNG ỐNG DỮ LIỆU, HUẤN LUYỆN VÀ QUẢN LÝ VÒNG ĐỜI MÔ HÌNH NHẬN DẠNG MVITV2-S", font=get_font(18, bold=True), fill="#0f172a")

    stages = [
        {
            "step": "BƯỚC 1",
            "title": "Dữ liệu đầu vào",
            "sub": "Thu thập & Phân tầng",
            "desc": [
                "• Kaggle VSL v2 (472 lớp, v8)",
                "• Tập ViSignLanguage-Video",
                "• Webcam quầy thu thập nội bộ",
                "• Lọc 30 nhãn sales-30 bán lẻ",
                "• Phân chia Signer-independent:",
                "  Train / Validation / Test"
            ],
            "color": "#0284c7"
        },
        {
            "step": "BƯỚC 2",
            "title": "Tiền xử lý ROI",
            "sub": "Cắt Body-Crop chuẩn",
            "desc": [
                "• Bám 11 mốc thân MediaPipe",
                "• Thuật toán trim-bodycrop-v1",
                "• Căn chỉnh tâm ngực và vai",
                "• Lấy mẫu 16 frame RGB đều",
                "• Kích thước 224 x 224 pixel",
                "• Chuẩn hóa tensor ImageNet"
            ],
            "color": "#0d9488"
        },
        {
            "step": "BƯỚC 3",
            "title": "Huấn luyện GPU",
            "sub": "MViTv2-S Video 3D",
            "desc": [
                "• Spatiotemporal 3D Attention",
                "• Checkpoint: sales30-epoch36",
                "• PyTorch 2.4 CUDA 12",
                "• Cross-Entropy + Label Smooth",
                "• Data Augmentation không gian",
                "  và thời gian chống Overfitting"
            ],
            "color": "#d97706"
        },
        {
            "step": "BƯỚC 4",
            "title": "Đánh giá độc lập",
            "sub": "Held-out Snapshot Test",
            "desc": [
                "• Phân hệ /evaluation độc lập",
                "• Test đứng (351 clip): 95.73% đúng",
                "• False Accept thấp (1.71%)",
                "• Validation đứng (144 clip): 95.83%",
                "• Validation ngồi (600 clip): 65.00%",
                "• So sánh candidate vs baseline"
            ],
            "color": "#ea580c"
        },
        {
            "step": "BƯỚC 5",
            "title": "Đóng gói & Chốt duyệt",
            "sub": "Approval Gate & Deploy",
            "desc": [
                "• Xuất container Modal GPU",
                "• Biên dịch Core ML Apple Silicon",
                "• Cơ chế chốt duyệt độc lập",
                "  (Chỉ Admin có quyền phê duyệt)",
                "• Đổi Active Pointer trong 0 giây",
                "• Hỗ trợ Rollback tức thì"
            ],
            "color": "#16a34a"
        }
    ]

    card_w = 325
    card_h = 480
    y_top = 85
    start_x = 35

    for i, st in enumerate(stages):
        x = start_x + i * (card_w + 25)
        draw_rounded_card(draw, [x, y_top, x + card_w, y_top + card_h], fill="#ffffff", outline=st["color"], width=2, radius=8)

        draw_rounded_card(draw, [x, y_top, x + card_w, y_top + 60], fill="#f8fafc", outline=st["color"], width=1, radius=8)
        draw.rectangle([x, y_top + 40, x + card_w, y_top + 60], fill="#f8fafc")
        
        draw.text((x + 15, y_top + 10), st["step"], font=get_font(12, bold=True), fill=st["color"])
        draw.text((x + 15, y_top + 30), st["title"], font=get_font(16, bold=True), fill="#0f172a")

        draw.text((x + 15, y_top + 75), st["sub"], font=get_font(13, bold=True), fill="#64748b")
        draw.line([x + 15, y_top + 100, x + card_w - 15, y_top + 100], fill="#cbd5e1", width=1)

        y_l = y_top + 120
        for line in st["desc"]:
            draw.text((x + 15, y_l), line, font=get_font(14), fill="#1e293b")
            y_l += 36

        if i < len(stages) - 1:
            draw_arrow(draw, (x + card_w + 3, y_top + card_h // 2), (x + card_w + 22, y_top + card_h // 2), color="#64748b", width=2, arrow_size=9)

    # Governance box
    gov_box = [35, 600, w - 35, 840]
    draw_rounded_card(draw, gov_box, fill="#f8fafc", outline="#cbd5e1", width=2, radius=8)
    draw.text((60, 620), "NGUYÊN TẮC QUẢN TRỊ AN TOÀN MÔ HÌNH AI TRONG HỆ THỐNG VSIGN (AI GOVERNANCE):", font=get_font(16, bold=True), fill="#0f172a")

    govs = [
        "1. Phân tách tập dữ liệu nghiêm ngặt: Tập Test held-out là bất biến, người ký trong tập Test không bao giờ xuất hiện trong tập Train.",
        "2. Không tự động triển khai (Zero Unattended Deploy): Mọi mô hình candidate phải vượt qua bài đánh giá đối chuẩn và có phê duyệt thủ công.",
        "3. Đóng băng phiên bản (Immutable Versioning): Mỗi checkpoint đều gắn mã hash SHA-256 và lưu nhật ký huấn luyện đầy đủ trong bảng /models.",
        "4. Tính sẵn sàng cao (High Availability Runtime): Checkpoint luôn sẵn sàng ở cả hai môi trường: Cloud GPU (Modal) và On-Premise (Core ML)."
    ]
    y_gov = 660
    for g in govs:
        draw.text((60, y_gov), g, font=get_font(14), fill="#334155")
        y_gov += 35

    out_path = os.path.join(OUTPUT_DIR, "diagram_5_4_ml_pipeline_lifecycle.png")
    img.save(out_path, dpi=(300, 300))
    print(f"Generated clean academic: {out_path}")

if __name__ == "__main__":
    generate_diagram_1()
    generate_diagram_2()
    generate_diagram_3()
    generate_diagram_4()
    print("All 4 academic diagrams generated successfully!")
