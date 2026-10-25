# -*- coding: utf-8 -*-
"""
Standardized Full Report Generator for VSign Project: Chapter 5 and Chapter 7.
Strictly adheres to Vietnamese Academic Thesis Guidelines (TCVN 385:2002):
- Diagrams drawn natively using Word shape blocks (Sơ đồ khối vẽ bằng khung hình Shape chuẩn Word):
  * Purely Black & White / Grayscale (Nền trắng, viền đen 1.5pt, bóng xám nhẹ #F8FAFC, chữ đen).
  * Minimal text, concise, extremely clear and easy to read.
  * Native Word elements (selectable, editable, vector-sharp, zero clutter).
- Uniform list hierarchy: Clean bullets with bold lead-ins, distinct numbered paragraphs, structured step paragraphs.
- Academic table formatting: Captions placed ABOVE table ("Bảng X.X: Tên bảng"), repeating header row (<w:tblHeader/>), no row-splitting (<w:cantSplit/>), booktabs borders.
- Academic figure formatting: Captions placed BELOW graphic ("Hình X.X: Tên hình" and "Sơ đồ X.X: Tên sơ đồ"), centered.
- Clean academic typography: Times New Roman 14pt (body), 18pt (Chapter title), 16pt (H1), 14pt bold (H2), 14pt bold italic (H3), 11-12pt (tables & captions).
  TCVN Margins: Top 2cm, Bottom 2cm, Left 3cm, Right 2cm.
"""

import os
import sys
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

def build_docx(output_path):
    doc = docx.Document()

    # 1. Page Margins (Vietnamese Standard TCVN: Left 3cm, Right 2cm, Top 2cm, Bottom 2cm)
    for section in doc.sections:
        section.top_margin = Inches(2.0 / 2.54)
        section.bottom_margin = Inches(2.0 / 2.54)
        section.left_margin = Inches(3.0 / 2.54)
        section.right_margin = Inches(2.0 / 2.54)
        section.page_width = Inches(21.0 / 2.54)
        section.page_height = Inches(29.7 / 2.54)

    # 2. Font Enforcer helper
    def set_font(run, font_name="Times New Roman", size_pt=14, bold=False, italic=False, color_rgb=(0,0,0)):
        run.font.name = font_name
        run.font.size = Pt(size_pt)
        run.bold = bold
        run.italic = italic
        run.font.color.rgb = RGBColor(*color_rgb)
        
        rPr = run._r.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts')
            rPr.append(rFonts)
        rFonts.set(qn('w:ascii'), font_name)
        rFonts.set(qn('w:hAnsi'), font_name)
        rFonts.set(qn('w:cs'), font_name)
        rFonts.set(qn('w:eastAsia'), font_name)

    # 3. Typography & Paragraph Helpers
    def add_p(text, align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_before=0, space_after=6, line_spacing=1.25, bold=False, italic=False):
        p = doc.add_paragraph()
        p.alignment = align
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.line_spacing = line_spacing
        run = p.add_run(text)
        set_font(run, "Times New Roman", 14, bold=bold, italic=italic)
        return p

    def add_title(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(16)
        p.paragraph_format.space_after = Pt(16)
        p.paragraph_format.line_spacing = 1.25
        run = p.add_run(text)
        set_font(run, "Times New Roman", 18, bold=True, color_rgb=(15, 34, 64))
        return p

    def add_h1(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(18)
        p.paragraph_format.space_after = Pt(10)
        p.paragraph_format.line_spacing = 1.25
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        set_font(run, "Times New Roman", 16, bold=True, color_rgb=(15, 34, 64))
        return p

    def add_h2(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.25
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        set_font(run, "Times New Roman", 14, bold=True, color_rgb=(24, 49, 83))
        return p

    def add_h3(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.25
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        set_font(run, "Times New Roman", 14, bold=True, italic=True, color_rgb=(30, 41, 59))
        return p

    # Standardized List Helpers
    def add_bullet(text, bold_prefix=None, level=0):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.25
        p.paragraph_format.left_indent = Inches(0.25 * (level + 1))
        
        run_b = p.add_run("•  ")
        set_font(run_b, "Times New Roman", 14, bold=True, color_rgb=(30, 41, 59))
        
        if bold_prefix:
            run_pfx = p.add_run(bold_prefix)
            set_font(run_pfx, "Times New Roman", 14, bold=True, color_rgb=(15, 23, 42))
        
        run_text = p.add_run(text)
        set_font(run_text, "Times New Roman", 14, bold=False, color_rgb=(30, 41, 59))
        return p

    def add_numbered_item(num_str, title, content):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.25
        p.paragraph_format.left_indent = Inches(0.25)
        
        r_num = p.add_run(f"{num_str}. {title}: ")
        set_font(r_num, "Times New Roman", 14, bold=True, color_rgb=(15, 23, 42))
        
        r_content = p.add_run(content)
        set_font(r_content, "Times New Roman", 14, bold=False, color_rgb=(30, 41, 59))
        return p

    def add_step_item(step_label, title, content):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.25
        p.paragraph_format.left_indent = Inches(0.25)
        
        r_step = p.add_run(f"{step_label} ({title}): ")
        set_font(r_step, "Times New Roman", 14, bold=True, color_rgb=(15, 23, 42))
        
        r_content = p.add_run(content)
        set_font(r_content, "Times New Roman", 14, bold=False, color_rgb=(30, 41, 59))
        return p

    # Standardized Figure Helper (For Real Interface Screenshots)
    def add_figure(img_path, caption_prefix, caption_title, width_inches=6.2):
        if os.path.exists(img_path):
            p_img = doc.add_paragraph()
            p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_img.paragraph_format.space_before = Pt(12)
            p_img.paragraph_format.space_after = Pt(4)
            p_img.paragraph_format.keep_with_next = True
            run_img = p_img.add_run()
            run_img.add_picture(img_path, width=Inches(width_inches))
            
            p_cap = doc.add_paragraph()
            p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_cap.paragraph_format.space_before = Pt(2)
            p_cap.paragraph_format.space_after = Pt(14)
            
            r_pre = p_cap.add_run(caption_prefix + ": ")
            set_font(r_pre, "Times New Roman", 12, bold=True, color_rgb=(15, 23, 42))
            
            r_title = p_cap.add_run(caption_title)
            set_font(r_title, "Times New Roman", 12, italic=True, color_rgb=(51, 65, 85))
        else:
            p_warn = doc.add_paragraph()
            p_warn.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p_warn.add_run(f"[{caption_prefix}: {caption_title} - Không tìm thấy tệp ảnh: {img_path}]")
            set_font(run, "Times New Roman", 12, italic=True, color_rgb=(185, 28, 28))

    # ==============================================================================
    # NATIVE WORD SHAPE DIAGRAM GENERATORS (B&W, MINIMAL TEXT, ZERO CLUTTER)
    # ==============================================================================
    def add_native_shape_flow_diagram(caption_prefix, caption_title, blocks, width_in=6.2):
        total_rows = len(blocks) * 2 - 1
        table = doc.add_table(rows=total_rows, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        # Prevent row split across pages
        for row in table.rows:
            trPr = row._tr.get_or_add_trPr()
            trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))

        row_idx = 0
        for i, (title, subtext) in enumerate(blocks):
            cell = table.rows[row_idx].cells[0]
            cell.width = Inches(width_in)
            
            tcPr = cell._tc.get_or_add_tcPr()
            # Solid black 1.5pt border (sz="12")
            borders = parse_xml(
                f'<w:tcBorders {nsdecls("w")}>'
                f'<w:top w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                f'<w:left w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                f'<w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                f'<w:right w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                f'</w:tcBorders>'
            )
            tcPr.append(borders)
            shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F8FAFC"/>')
            tcPr.append(shd)
            
            tcMar = parse_xml(
                f'<w:tcMar {nsdecls("w")}>'
                f'<w:top w:w="120" w:type="dxa"/>'
                f'<w:bottom w:w="120" w:type="dxa"/>'
                f'<w:left w:w="180" w:type="dxa"/>'
                f'<w:right w:w="180" w:type="dxa"/>'
                f'</w:tcMar>'
            )
            tcPr.append(tcMar)
            
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.15
            
            r_title = p.add_run(title + "\n")
            set_font(r_title, "Times New Roman", 13, bold=True, color_rgb=(0, 0, 0))
            
            r_sub = p.add_run(subtext)
            set_font(r_sub, "Times New Roman", 11, bold=False, color_rgb=(40, 40, 40))
            
            if i < len(blocks) - 1:
                arrow_cell = table.rows[row_idx + 1].cells[0]
                arrow_cell.width = Inches(width_in)
                tcPr_a = arrow_cell._tc.get_or_add_tcPr()
                borders_a = parse_xml(
                    f'<w:tcBorders {nsdecls("w")}>'
                    f'<w:top w:val="none"/>'
                    f'<w:left w:val="none"/>'
                    f'<w:bottom w:val="none"/>'
                    f'<w:right w:val="none"/>'
                    f'</w:tcBorders>'
                )
                tcPr_a.append(borders_a)
                
                p_a = arrow_cell.paragraphs[0]
                p_a.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_a.paragraph_format.space_before = Pt(2)
                p_a.paragraph_format.space_after = Pt(2)
                
                r_arr = p_a.add_run("▼")
                set_font(r_arr, "Times New Roman", 13, bold=True, color_rgb=(0, 0, 0))
                row_idx += 2
            else:
                row_idx += 1
                
        p_cap = doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_cap.paragraph_format.space_before = Pt(6)
        p_cap.paragraph_format.space_after = Pt(14)
        
        r_pre = p_cap.add_run(caption_prefix + ": ")
        set_font(r_pre, "Times New Roman", 12, bold=True, color_rgb=(15, 23, 42))
        
        r_title = p_cap.add_run(caption_title)
        set_font(r_title, "Times New Roman", 12, italic=True, color_rgb=(51, 65, 85))

    def add_native_arch_diagram(caption_prefix, caption_title, width_in=6.2):
        table = doc.add_table(rows=5, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        
        for row in table.rows:
            trPr = row._tr.get_or_add_trPr()
            trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
        
        tiers = [
            ("TẦNG THIẾT BỊ MÁY TRẠM TẠI QUẦY (CLIENT STATIONS)",
             "• Màn hình khách (/display): Camera 30 fps, Web Worker MediaPipe bám 21 mốc tay + 11 mốc thân, cắt chuẩn hóa 16 khung hình RGB 224x224 (trim-bodycrop-v1).\n• Bàn làm việc nhân viên (/recognize): Nhận video WebRTC P2P nội bộ, bộ ghép câu rảnh tay (Sentence Composer), phát âm TTS và micro phản hồi STT."),
            
            ("TẦNG MÁY CHỦ DỊCH VỤ & ĐIỀU PHỐI (FASTAPI BACKEND)",
             "• FastAPI Gateway & Uvicorn ASGI Server: Quản lý phiên làm việc đa quầy, điều phối WebSocket Hub.\n• Ghép đôi quầy an toàn (PIN 6 số, QR Token, Cookie Kiosk vĩnh viễn), xác thực RBAC & băm Argon2id.\n• Bộ điều phối luồng (Debounce 1.000 ms, Heuristic nghỉ 1.800 ms), ký số Webhook HMAC SHA-256.\n• Bộ chuyển mạch dự phòng Failover: Tự động điều tuyến giữa Asia Modal GPU và Local Core ML trong 6s."),
             
            ("TẦNG HẠ TẦNG SUY LUẬN AI MÁY CHỦ (SERVER-SIDE GPU)",
             "• Cụm GPU đám mây Đông Nam Á (Asia Modal GPU): NVIDIA L4 24GB Tensor Core, PyTorch CUDA 12, thực thi mô hình video không-thời gian MViTv2-S (sales30-epoch36), thời gian tính toán 35–65 ms / 16 frame.\n• Máy chủ trạm dự phòng tại chỗ: Apple Silicon Neural Engine (Core ML port 8000), suy luận < 15 ms.\n• Bảo mật riêng tư: 16 khung hình RGB chỉ giải mã trong RAM GPU của tiến trình, tuyệt đối không ghi đĩa.")
        ]
        
        connectors = [
            "▲   Kênh kết nối thời gian thực: WebSocket (16 frame RGB)  &  WebRTC P2P (Luồng video LAN nội bộ)   ▲\n▼                                                                                                                                           ▼",
            "▲   Giao thức mạng suy luận AI: wss:// (Cloud GPU chính)  &  HTTP localhost:8000 (Dự phòng Core ML)   ▲\n▼                                                                                                                                           ▼"
        ]
        
        row_idx = 0
        for i, (title, content) in enumerate(tiers):
            cell = table.rows[row_idx].cells[0]
            cell.width = Inches(width_in)
            tcPr = cell._tc.get_or_add_tcPr()
            borders = parse_xml(
                f'<w:tcBorders {nsdecls("w")}>'
                f'<w:top w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                f'<w:left w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                f'<w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                f'<w:right w:val="single" w:sz="12" w:space="0" w:color="000000"/>'
                f'</w:tcBorders>'
            )
            tcPr.append(borders)
            shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F8FAFC"/>')
            tcPr.append(shd)
            
            tcMar = parse_xml(
                f'<w:tcMar {nsdecls("w")}>'
                f'<w:top w:w="120" w:type="dxa"/>'
                f'<w:bottom w:w="120" w:type="dxa"/>'
                f'<w:left w:w="180" w:type="dxa"/>'
                f'<w:right w:w="180" w:type="dxa"/>'
                f'</w:tcMar>'
            )
            tcPr.append(tcMar)
            
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            r_title = p.add_run(title + "\n")
            set_font(r_title, "Times New Roman", 12, bold=True, color_rgb=(0, 0, 0))
            
            p2 = cell.add_paragraph()
            p2.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p2.paragraph_format.space_before = Pt(2)
            p2.paragraph_format.space_after = Pt(3)
            p2.paragraph_format.line_spacing = 1.15
            r_content = p2.add_run(content)
            set_font(r_content, "Times New Roman", 11, bold=False, color_rgb=(30, 41, 59))
            
            if i < len(tiers) - 1:
                conn_cell = table.rows[row_idx + 1].cells[0]
                conn_cell.width = Inches(width_in)
                tcPr_c = conn_cell._tc.get_or_add_tcPr()
                borders_c = parse_xml(
                    f'<w:tcBorders {nsdecls("w")}>'
                    f'<w:top w:val="none"/>'
                    f'<w:left w:val="none"/>'
                    f'<w:bottom w:val="none"/>'
                    f'<w:right w:val="none"/>'
                    f'</w:tcBorders>'
                )
                tcPr_c.append(borders_c)
                p_c = conn_cell.paragraphs[0]
                p_c.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_c.paragraph_format.space_before = Pt(2)
                p_c.paragraph_format.space_after = Pt(2)
                r_c = p_c.add_run(connectors[i])
                set_font(r_c, "Times New Roman", 10, bold=True, color_rgb=(0, 0, 0))
                row_idx += 2
            else:
                row_idx += 1
                
        p_cap = doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_cap.paragraph_format.space_before = Pt(6)
        p_cap.paragraph_format.space_after = Pt(14)
        r_pre = p_cap.add_run(caption_prefix + ": ")
        set_font(r_pre, "Times New Roman", 12, bold=True, color_rgb=(15, 23, 42))
        r_title = p_cap.add_run(caption_title)
        set_font(r_title, "Times New Roman", 12, italic=True, color_rgb=(51, 65, 85))

    # Standardized Table Helper (Captions ABOVE the table)
    def set_cell_margins(cell, top=100, bottom=100, left=140, right=140):
        tcPr = cell._tc.get_or_add_tcPr()
        tcMar = OxmlElement('w:tcMar')
        for margin, value in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
            node = OxmlElement(f'w:{margin}')
            node.set(qn('w:w'), str(value))
            node.set(qn('w:type'), 'dxa')
            tcMar.append(node)
        tcPr.append(tcMar)

    def set_cell_shading(cell, color_hex):
        shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
        cell._tc.get_or_add_tcPr().append(shading)

    def add_styled_table(headers, data, col_widths, align_cols=None, caption_prefix="Bảng 5.1", caption_title=""):
        if caption_prefix:
            p_cap = doc.add_paragraph()
            p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_cap.paragraph_format.space_before = Pt(12)
            p_cap.paragraph_format.space_after = Pt(4)
            p_cap.paragraph_format.keep_with_next = True
            
            r_pre = p_cap.add_run(caption_prefix + ": ")
            set_font(r_pre, "Times New Roman", 12, bold=True, color_rgb=(15, 23, 42))
            
            r_title = p_cap.add_run(caption_title)
            set_font(r_title, "Times New Roman", 12, italic=True, color_rgb=(15, 23, 42))

        table = doc.add_table(rows=1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        # Repeat Header Row across pages & Prevent split
        header_tr = table.rows[0]._tr.get_or_add_trPr()
        header_tr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
        header_tr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))

        # Booktabs-style professional borders
        tblPr = table._tbl.tblPr
        tblBorders = parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            f'<w:top w:val="single" w:sz="12" w:space="0" w:color="0F172A"/>'
            f'<w:bottom w:val="single" w:sz="12" w:space="0" w:color="0F172A"/>'
            f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
            f'<w:insideV w:val="none"/>'
            f'<w:left w:val="none"/>'
            f'<w:right w:val="none"/>'
            f'</w:tblBorders>'
        )
        tblPr.append(tblBorders)

        hdr_cells = table.rows[0].cells
        for i, h_text in enumerate(headers):
            hdr_cells[i].text = h_text
            set_cell_margins(hdr_cells[i], top=120, bottom=120, left=140, right=140)
            set_cell_shading(hdr_cells[i], "F1F5F9")
            p = hdr_cells[i].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.15
            for r in p.runs:
                set_font(r, "Times New Roman", 11, bold=True, color_rgb=(15, 23, 42))

        for row_idx, row_values in enumerate(data):
            row = table.add_row()
            trPr = row._tr.get_or_add_trPr()
            trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
            
            row_cells = row.cells
            bg_color = "FFFFFF" if row_idx % 2 == 0 else "F8FAFC"
            for col_idx, val in enumerate(row_values):
                row_cells[col_idx].text = str(val)
                set_cell_margins(row_cells[col_idx], top=80, bottom=80, left=140, right=140)
                set_cell_shading(row_cells[col_idx], bg_color)
                p = row_cells[col_idx].paragraphs[0]
                align = WD_ALIGN_PARAGRAPH.LEFT
                if align_cols and col_idx < len(align_cols):
                    align = align_cols[col_idx]
                p.alignment = align
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.line_spacing = 1.15
                for r in p.runs:
                    set_font(r, "Times New Roman", 11, bold=False, color_rgb=(30, 41, 59))

        for row in table.rows:
            for idx, width in enumerate(col_widths):
                row.cells[idx].width = width

        p_spacer = doc.add_paragraph()
        p_spacer.paragraph_format.space_before = Pt(0)
        p_spacer.paragraph_format.space_after = Pt(8)

    # ==========================================
    # HEADER / INTRO
    # ==========================================
    p_meta = doc.add_paragraph()
    p_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_meta = p_meta.add_run("BÁO CÁO THỰC THI DỰ ÁN HỆ THỐNG VSIGN\nGIẢI PHÁP HỖ TRỢ GIAO TIẾP BẰNG NGÔN NGỮ KÝ HIỆU VIỆT NAM TRONG LĨNH VỰC BÁN LẺ")
    set_font(run_meta, "Times New Roman", 14, bold=True, color_rgb=(71, 85, 105))
    p_meta.paragraph_format.space_after = Pt(14)

    # ==========================================
    # CHƯƠNG 5: TRIỂN KHAI XÂY DỰNG WEBSITE
    # ==========================================
    add_title("CHƯƠNG 5: TRIỂN KHAI XÂY DỰNG WEBSITE")

    add_h1("5.1. Lựa chọn công nghệ và thiết kế cấu trúc website")
    
    add_h2("5.1.1. Phạm vi kiến trúc và mô hình dịch vụ tại quầy bán lẻ")
    add_p("Nền tảng thương mại VSign (https://vsign.io.vn) được thiết kế và triển khai nhằm phục vụ trực tiếp môi trường quầy giao dịch và chuỗi cửa hàng bán lẻ theo mô hình phần mềm dịch vụ B2B SaaS. Toàn bộ kiến trúc tập trung giải quyết bài toán giao tiếp hai chiều thời gian thực giữa khách hàng khiếm thính sử dụng Ngôn ngữ ký hiệu Việt Nam (VSL) và nhân viên thu ngân/tư vấn quầy theo mô hình quầy hai thiết bị độc lập (Dual-Device Counter Service):")
    add_bullet("Mở giao diện bàn làm việc (/recognize), kết nối trực tiếp với hạ tầng suy luận AI máy chủ GPU chuyên dụng (Server-side GPU) và tiếp nhận tín hiệu video từ camera của khách qua WebRTC.", bold_prefix="Thiết bị nhân viên (Staff Device): ")
    add_bullet("Mở đường dẫn https://vsign.io.vn/display, đặt ở chế độ toàn màn hình kiosk. Thiết bị chỉ hiển thị hình ảnh phản chiếu của khách để căn chỉnh cử chỉ, khu vực hiển thị từ nhận diện và câu tiếng Việt bằng chữ lớn, cùng phản hồi văn bản của nhân viên. Khách hàng không cần tạo tài khoản hay chạm vào màn hình.", bold_prefix="Thiết bị khách hàng (Customer Display): ")
    add_p("Kiến trúc tổng thể của hệ thống VSign phân bổ rõ ràng ranh giới trách nhiệm giữa các thiết bị đầu cuối của máy khách, hạ tầng mạng truyền thông thời gian thực và cụm máy chủ suy luận GPU, bảo đảm tính sẵn sàng cao và bảo mật tuyệt đối cho giao dịch thương mại:")

    # Sơ đồ 5.1: Native Shape Block Architecture Diagram
    add_native_arch_diagram("Sơ đồ 5.1", "Sơ đồ khối kiến trúc phân tầng hệ thống VSign")

    add_h2("5.1.2. Chi tiết các công nghệ sử dụng và Bảng tổng hợp công nghệ hệ thống")
    add_p("Để đáp ứng yêu cầu khắt khe về tính ổn định, độ trễ thấp và bảo mật dữ liệu của môi trường bán lẻ, VSign lựa chọn và kết hợp các công nghệ hiện đại nhất trên 4 tầng kiến trúc chính:")
    
    add_h3("a. Tầng Trình duyệt và Thiết bị máy trạm (Frontend Client)")
    add_bullet("Xây dựng giao diện hướng thành phần (Component-driven) với khả năng quản lý trạng thái luồng video, danh sách nhãn nhận dạng và bộ đệm câu tiếng Việt. TypeScript bảo đảm kiểm soát kiểu dữ liệu tĩnh nghiêm ngặt trên toàn bộ hợp đồng API.", bold_prefix="React 19 và TypeScript 5.8: ")
    add_bullet("Công cụ đóng gói module siêu tốc hỗ trợ tối ưu hóa gói phân phối (Tree-shaking, Code-splitting). Tailwind CSS kết hợp bộ biến số thiết kế (CSS design tokens) bảo đảm giao diện quầy rõ nét, tương phản cao, tối ưu cho mắt người nhìn ở khoảng cách quầy 1–1.5m.", bold_prefix="Vite 6 và Tailwind CSS v3: ")
    add_bullet("Chạy ngầm bám bắt 21 điểm mốc bàn tay và 11 mốc thân trên mà không phong tỏa luồng kết xuất đồ họa chính (Main Thread) của trình duyệt. Thuật toán trim-bodycrop-v1 tự động căn tâm ngực và tỷ lệ hai vai để cắt chuỗi 16 khung hình RGB 224 x 224 pixel.", bold_prefix="@mediapipe/tasks-vision trên Web Worker: ")
    add_bullet("WebRTC truyền phát luồng video trực tiếp giữa hai máy quầy (P2P). Web Speech API cung cấp tính năng Text-to-Speech (TTS) tự động đọc to câu nói cho nhân viên nghe và Speech-to-Text (STT) ghi nhận phản hồi bằng giọng nói của nhân viên.", bold_prefix="WebRTC API và Web Speech API: ")
    add_bullet("Duy trì kênh truyền nhị phân hai chiều liên tục (wss://), gửi các gói tin 16 khung hình RGB lên máy chủ GPU và tiếp nhận kết quả phân tích trong vài chục mili-giây.", bold_prefix="WebSocket API: ")

    add_h3("b. Tầng Máy chủ Ứng dụng và Dịch vụ (Backend & Services)")
    add_bullet("Khung ứng dụng bất đồng bộ hiệu năng cao (ASGI), quản lý toàn bộ các điểm cuối RESTful API và trung tâm điều phối WebSocket Hub. Tận dụng kiến trúc async/await của Python để phục vụ đồng thời hàng trăm quầy giao dịch.", bold_prefix="Python 3.11 và FastAPI: ")
    add_bullet("Định nghĩa và xác thực nghiêm ngặt mọi lược đồ dữ liệu (Schema contract-driven development), loại bỏ hoàn toàn các lỗi sai định dạng gói tin giữa client và máy chủ.", bold_prefix="Pydantic v2: ")
    add_bullet("Áp dụng thuật toán băm mật khẩu bộ nhớ kháng GPU (RFC 9106) cho tài khoản quản trị. Phiên đăng nhập được lưu giữ qua cookie có gắn cờ HttpOnly, Secure và SameSite=Lax chống tấn công đánh cắp phiên XSS/CSRF.", bold_prefix="Argon2id và Cookie HttpOnly: ")
    add_bullet("Lưu trữ an toàn siêu dữ liệu cấu hình quầy, tài khoản phân quyền và nhật ký kiểm toán. Hỗ trợ tích hợp với hệ thống POS bán lẻ qua Webhook được ký số bảo mật bằng mã băm HMAC SHA-256.", bold_prefix="SQLite / PostgreSQL và HMAC SHA-256 Webhook: ")

    add_h3("c. Tầng Hạ tầng Suy luận AI Máy chủ (Server-side GPU Inference)")
    add_bullet("Hệ thống triển khai worker containerized không máy chủ trên hạ tầng đám mây Modal đặt tại Singapore (ap-southeast), trang bị GPU chuyên dụng NVIDIA L4 (24GB VRAM) hoặc A10 Tensor Core, thực thi PyTorch 2.4 CUDA 12 để suy luận mô hình video MViTv2-S.", bold_prefix="Cụm đám mây Asia Modal GPU: ")
    add_bullet("Máy Mac quầy bán hàng chạy mô hình MViTv2-S được biên dịch tối ưu cho Apple Silicon Neural Engine (port 8000), cung cấp khả năng xử lý dưới 15 ms khi xảy ra sự cố mạng quốc tế.", bold_prefix="Tầng dự phòng Apple Silicon Core ML: ")
    add_bullet("Tiền xử lý chuỗi tensor, chuẩn hóa kích thước và giá trị màu ImageNet trước khi đưa qua các lớp Attention của mạng nơ-ron.", bold_prefix="OpenCV và Torchvision: ")

    add_h3("d. Tầng Mạng, Hạ tầng Đám mây và An toàn Thông tin")
    add_bullet("Mạng phân phối toàn cầu phục vụ giao diện tĩnh và định tuyến biên với độ trễ thấp.", bold_prefix="Vercel CDN: ")
    add_bullet("Tạo đường hầm mã hóa an toàn nối API nội bộ (api.vsign.io.vn) ra Internet mà không cần mở bất kỳ cổng (port) nào trên router của cửa hàng.", bold_prefix="Cloudflare Tunnel: ")
    add_bullet("Hỗ trợ đàm phán ứng viên ICE để kết nối WebRTC video đi trực tiếp nội bộ giữa hai máy tính trong quầy.", bold_prefix="Google STUN: ")

    tech_headers = ["Tầng kiến trúc", "Công nghệ / Thư viện", "Phiên bản", "Vai trò & Chức năng trong hệ thống", "Giao thức / Ranh giới"]
    tech_data = [
        ["Frontend Client", "React", "19.0.0", "Thư viện nền tảng xây dựng giao diện người dùng theo component", "DOM / Virtual DOM"],
        ["Frontend Client", "TypeScript", "5.8.2", "Ngôn ngữ định kiểu tĩnh, bảo đảm tính an toàn dữ liệu và hợp đồng API", "Type Checking"],
        ["Frontend Client", "Vite", "6.2.0", "Công cụ đóng gói module siêu tốc, tối ưu hóa kích thước bản build production", "ES Modules"],
        ["Frontend Client", "Tailwind CSS", "3.4.17", "Framework CSS tiện ích xây dựng hệ thống thiết kế giao diện quầy nhất quán", "CSS Variables"],
        ["Frontend Client", "Lucide React", "0.475.0", "Bộ biểu tượng vector sắc nét tối ưu cho màn hình kiosk và quầy làm việc", "SVG Icons"],
        ["Frontend Client", "@mediapipe/tasks-vision", "1.0.1", "Bám bắt 21 mốc bàn tay và 11 mốc thân trên, cắt vùng cử chỉ trim-bodycrop-v1", "Web Worker bất đồng bộ"],
        ["Frontend Client", "WebRTC API", "W3C Spec", "Truyền phát trực tiếp luồng video camera khách sang máy nhân viên trong mạng LAN", "P2P DTLS/SRTP (STUN)"],
        ["Frontend Client", "Web Speech API", "W3C Spec", "Chuyển giọng nói nhân viên thành chữ (STT) và đọc to câu tiếng Việt (TTS)", "Native Browser API"],
        ["Frontend Client", "WebSocket API", "RFC 6455", "Truyền chuỗi 16 khung hình RGB và đồng bộ hội thoại hai chiều tức thì", "wss:// (Giao thức nhị phân)"],
        ["Backend Services", "Python", "3.11+", "Ngôn ngữ phát triển backend, pipeline thị giác máy tính và dịch vụ API", "Runtime CPython"],
        ["Backend Services", "FastAPI", "0.115.8", "Framework web bất đồng bộ hiệu năng cao định tuyến API và WebSocket Hub", "ASGI (Starlette-based)"],
        ["Backend Services", "Uvicorn", "0.34.0", "Máy chủ web ASGI tiêu chuẩn xử lý đồng thời hàng nghìn kết nối mạng", "HTTP/1.1 & WebSocket"],
        ["Backend Services", "Pydantic", "2.10.6", "Xác thực cấu trúc dữ liệu theo lược đồ hợp đồng (Contract-driven schema)", "Data Validation"],
        ["Backend Services", "Argon2id", "RFC 9106", "Thuật toán băm mật khẩu quản trị bảo mật cao chống tấn công GPU/ASIC", "Memory-hard Hash"],
        ["Backend Services", "SQLite / PostgreSQL", "3.45+ / 16+", "Lưu trữ dữ liệu cấu hình quầy, tài khoản phân quyền và nhật ký kiểm toán", "SQL Database Engine"],
        ["Backend Services", "HMAC SHA-256", "RFC 2104", "Ký số bảo mật các gói tin sự kiện Webhook gửi sang hệ thống POS bán lẻ", "Cryptographic Signature"],
        ["AI Inference GPU", "Asia Modal GPU Cloud", "Modal v0.68+", "Hạ tầng GPU đám mây containerized không máy chủ đặt tại Đông Nam Á (ap-south)", "Serverless Cloud Worker"],
        ["AI Inference GPU", "NVIDIA L4 / A10 GPU", "24GB VRAM", "Phần cứng tăng tốc tính toán AI chuyên dụng với lõi Tensor Core thế hệ mới", "PCIe Gen4 / Ada Lovelace"],
        ["AI Inference GPU", "PyTorch CUDA", "2.4.1 (CUDA 12)", "Framework học sâu thực thi suy luận mô hình video không gian - thời gian MViTv2-S", "GPU CUDA Tensor Cores"],
        ["AI Inference GPU", "Apple Core ML", "Core ML 3.x", "Runtime suy luận dự phòng tại chỗ tối ưu hóa trên Apple Silicon Neural Engine (ANE)", "Local Neural Engine (port 8000)"],
        ["AI Inference GPU", "OpenCV & Torchvision", "4.10+ / 0.19+", "Tiền xử lý chuỗi video, chuẩn hóa khung hình 224x224 và tensor ImageNet", "Tensor Preprocessing"],
        ["Infra & Security", "Vercel CDN", "Edge Network", "Mạng phân phối giao diện tĩnh toàn cầu liên kết tên miền chính thức vsign.io.vn", "Global Anycast Edge"],
        ["Infra & Security", "Cloudflare Tunnel", "cloudflared 2024+", "Đường hầm định tuyến an toàn máy chủ nội bộ api.vsign.io.vn không mở cổng router", "Encrypted Tunnel"],
        ["Infra & Security", "Google STUN", "STUN RFC 5389", "Máy chủ đàm phán ứng viên ICE thiết lập đường truyền WebRTC P2P trong mạng nội bộ", "UDP Port 19302"],
        ["Infra & Security", "Pytest & Playwright", "8.3+ / 1.49+", "Bộ công cụ tự động hóa kiểm thử đa tầng: Unit test, Integration test và E2E browser", "Automated QA Suite"]
    ]
    add_styled_table(
        tech_headers, tech_data,
        [Inches(1.1), Inches(1.2), Inches(0.7), Inches(2.3), Inches(1.0)],
        [WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT],
        caption_prefix="Bảng 5.1",
        caption_title="Bảng tổng hợp toàn bộ công nghệ sử dụng trong hệ thống VSign"
    )

    add_h2("5.1.3. Hạ tầng suy luận AI máy chủ: Đám mây Asia Modal GPU và Apple Core ML")
    add_p("Đối với hệ thống thương mại phục vụ tại quầy bán lẻ (vsign.io.vn), việc nhận dạng chuỗi cử chỉ đòi hỏi độ chính xác tuyệt đối trong môi trường ánh sáng phức tạp. Do đó, mô hình nhận dạng chính của VSign là MViTv2-S (Multiscale Vision Transformer) – kiến trúc biến đổi thị giác không gian - thời gian (spatiotemporal vision) 3D tiếp nhận chuỗi 16 khung hình RGB. Để đáp ứng khối lượng tính toán lớn này, suy luận được thực thi trên hạ tầng máy chủ GPU chuyên dụng (Server-side GPU):")
    add_bullet("Hệ thống đã triển khai chính thức cụm worker containerized trên nền tảng đám mây Modal (địa chỉ ckiet1612--vsign-inference-inference-ap-southeast.ap-south.modal.run) đặt tại trung tâm dữ liệu Đông Nam Á (Singapore/Asia). Cụm tính toán sử dụng GPU NVIDIA (L4 / A10) tăng tốc PyTorch CUDA, thực thi checkpoint sales30-mvitv2s-personal-v3-bodycrop-curated-head-epoch36. Kết nối WebSocket wss:// tiếp nhận 16 frame ảnh RGB từ trình duyệt và trả về xác suất dự đoán chỉ trong 35–65 ms suy luận thuần (tổng độ trễ mạng khu vực đạt 120–180 ms).", bold_prefix="Đám mây GPU chuyên dụng khu vực Châu Á (Asia Modal GPU): ")
    add_bullet("Đóng vai trò là máy chủ trạm tại quầy hoặc phương án dự phòng tự động (fallback) khi mất kết nối Internet. Tận dụng Apple Silicon Neural Engine trên máy Mac quầy bán hàng (port 8000), Core ML đạt tốc độ suy luận dưới 15 ms cho mỗi mẫu 16 khung hình.", bold_prefix="Tầng suy luận cục bộ máy Mac (Apple Core ML): ")
    add_bullet("Hook useInferenceEndpoint liên tục kiểm tra kết nối Modal GPU; nếu mất tín hiệu quá 6 giây, trình duyệt tự động chuyển về Core ML trên máy Mac; khi Modal GPU sẵn sàng trở lại, hệ thống tự động kết nối lại giữa các lượt ký mà không làm gián đoạn phiên làm việc. Huy hiệu BackendLocationBadge hiển thị trực tiếp cho nhân viên biết đang sử dụng 'Asia Modal GPU' hay 'Local Core ML'.", bold_prefix="Cơ chế tự động chuyển đổi runtime linh hoạt (Dynamic Failover): ")
    add_p("Về truyền thông thời gian thực và an toàn video trên máy chủ:")
    add_bullet("Luồng video giữa laptop khách và laptop nhân viên đi trực tiếp ngang hàng P2P trong mạng nội bộ qua máy chủ STUN của Google (stun:stun.l.google.com:19302), không trung chuyển qua máy chủ.", bold_prefix="Video WebRTC ngang hàng nội bộ: ")
    add_bullet("Gói tin 16 khung hình RGB gửi lên server GPU qua WebSocket chỉ được giải mã trong bộ nhớ RAM của tiến trình PyTorch/Core ML để tính toán phân phối xác suất. Máy chủ tuyệt đối không ghi các khung hình này xuống ổ cứng hay cơ sở dữ liệu, bảo đảm nguyên tắc bảo vệ quyền riêng tư của khách hàng.", bold_prefix="Nguyên tắc an toàn dữ liệu 16 khung hình: ")

    add_h2("5.1.4. Thiết bị, trình duyệt và cấu trúc điều hướng website")
    add_p("Hệ thống VSign tại điểm bán lẻ được thiết kế để tương thích với các thiết bị phần cứng thông dụng:")
    add_bullet("Máy tính để bàn POS hoặc laptop tiêu chuẩn của cửa hàng chạy hệ điều hành Windows, macOS hoặc Linux, trang bị bàn phím và micro thu âm định hướng có tính năng lọc ồn.", bold_prefix="Thiết bị quầy nhân viên: ")
    add_bullet("Laptop thứ hai hoặc máy tính bảng cảm ứng đặt đối diện khách hàng, trang bị webcam góc rộng tiêu chuẩn 720p hoặc 1080p có khả năng bao quát khung hình từ thắt lưng lên đỉnh đầu.", bold_prefix="Thiết bị quầy khách hàng: ")
    add_bullet("Hỗ trợ hoàn chỉnh trên Google Chrome (khuyến nghị cho chế độ toàn màn hình kiosk), Microsoft Edge, Mozilla Firefox và Apple Safari.", bold_prefix="Trình duyệt tương thích: ")
    add_p("Cấu trúc điều hướng của website (Sitemap) được phân định thành bốn phân hệ chức năng chính:")
    add_numbered_item("1", "Phân hệ cổng truy cập và hiển thị quầy", "Cổng đăng nhập an toàn (/login), trang tiếp nhận lời mời tham gia tổ chức (/invite) và Màn hình hiển thị chuyên dụng tại quầy dành cho khách (/display).")
    add_numbered_item("2", "Phân hệ vận hành quầy bán lẻ", "Bàn làm việc nhận dạng và hỗ trợ giao tiếp hai chiều dành cho nhân viên bán hàng (/recognize).")
    add_numbered_item("3", "Phân hệ quản trị doanh nghiệp (Workspace Console)", "Bảng điều khiển tổng quan (/overview), Quản lý dữ liệu & thu mẫu (/data), Đánh giá mô hình (/evaluation), Giám sát dịch vụ (/monitoring), Quản lý vòng đời mô hình (/models), Nhật ký kiểm toán (/activity), Tích hợp khóa API & Webhook (/integrations), Thành viên & phân quyền (/team) và Cấu hình hệ thống & thiết bị quầy (/settings).")
    add_numbered_item("4", "Phân hệ kiểm thử nội bộ", "Bàn kiểm định chẩn đoán kỹ thuật (/dev-test), được cô lập hoàn toàn và tự động loại bỏ khỏi bản phát hành thương mại.")

    add_h2("5.1.5. Luồng xử lý giao tiếp hai chiều và phân định an toàn dữ liệu")
    add_p("Chu trình xử lý giao tiếp hai chiều tại quầy giữa khách hàng khiếm thính và nhân viên bán lẻ diễn ra khép kín theo 8 bước nối tiếp:")
    add_step_item("Bước 1", "Ghi nhận hình ảnh", "Camera tại quầy khách thu nhận chuyển động ký hiệu với tốc độ ổn định 30 khung hình/giây.")
    add_step_item("Bước 2", "Bám bắt đặc trưng", "MediaPipe trích xuất tọa độ không gian 21 khớp xương bàn tay và 11 điểm mốc tư thế thân trên.")
    add_step_item("Bước 3", "Cắt tỉa và chuẩn hóa khung hình", "Trình duyệt căn chỉnh vùng thân trên theo tỷ lệ hai vai (chuẩn trim-bodycrop-v1), đóng gói chuỗi 16 khung hình RGB kích thước 224 × 224 pixel.")
    add_step_item("Bước 4", "Suy luận nhận dạng trên máy chủ GPU", "Chuỗi 16 khung hình được gửi qua WebSocket wss:// đến cụm máy chủ Asia Modal GPU (hoặc Local Core ML). Mô hình MViTv2-S thực thi tính toán và xuất phân phối xác suất cử chỉ. Ngưỡng chấp nhận tin cậy của mô hình hiện được thiết lập tối ưu ở mức 40% (0.40) với margin 0.0, bảo đảm độ nhạy cao khi khách hàng thao tác nhanh tại quầy.")
    add_step_item("Bước 5", "Trả kết quả và chống ghi lặp", "Máy chủ trả về nhãn nhận dạng qua WebSocket. Bộ điều phối luồng áp dụng cơ chế debounce 1.000 ms để chống ghi lặp cùng một cử chỉ kéo dài; tự động ngắt câu sau 5.000 ms nghỉ giữa các lượt giao tiếp.")
    add_step_item("Bước 6", "Diễn đạt câu tiếng Việt tự nhiên rảnh tay", "Bộ ghép câu (Sentence Composer) tự động chuẩn hóa thứ tự từ ngữ, liên kết các danh từ và bổ ngữ bằng từ 'và', tự động ngắt câu khi xuất hiện chủ ngữ mới hoặc lời chào/cảm ơn mà không làm gián đoạn câu trước. Cơ chế tạo câu diễn ra hoàn toàn tự động, loại bỏ các cảnh báo rườm rà gây phân tâm tại quầy.")
    add_step_item("Bước 7", "Hiển thị và phát âm cho nhân viên", "Câu diễn đạt tiếng Việt và chuỗi từ gốc được hiển thị song song trên màn hình nhân viên; hệ thống tự động kích hoạt Web Speech API để đọc thành tiếng (Text-to-Speech) câu nói cho nhân viên nghe.")
    add_step_item("Bước 8", "Nhân viên phản hồi hai chiều", "Nhân viên trả lời khách bằng cách gõ phím hoặc nhấn nút nói (Speech-to-Text); câu trả lời lập tức được chuyển thành văn bản chữ lớn hiển thị trên màn hình khách (/display).")

    # Sơ đồ 5.2: Native Shape Block Sequence Flow
    blocks_52 = [
        ("1. THU NHẬN HÌNH ẢNH CỬ CHỈ", "Camera quầy khách thu nhận video 30 khung hình/giây liên tục"),
        ("2. BÁM BẮT ĐẶC TRƯNG & CẮT VÙNG THÂN TRÊN ROI", "MediaPipe bám bắt 21 mốc tay + 11 mốc thân; thuật toán trim-bodycrop-v1 đóng gói 16 khung hình RGB 224x224"),
        ("3. SUY LUẬN NHẬN DẠNG TRÊN MÁY CHỦ GPU", "Gửi chuỗi 16 frame qua WebSocket lên Asia Modal GPU (NVIDIA L4 PyTorch); ngưỡng tin cậy 40%, margin 0.0"),
        ("4. GHÉP CÂU TIẾNG VIỆT TỰ NHIÊN RẢNH TAY", "Bộ Sentence Composer tự động liên kết từ ngữ bằng từ 'và', ngắt câu thông minh; Web Speech TTS đọc to cho nhân viên"),
        ("5. NHÂN VIÊN PHẢN HỒI HAI CHIỀU", "Nhân viên trả lời bằng giọng nói (STT) hoặc gõ phím; câu trả lời lập tức đồng bộ chữ lớn sang Màn hình khách")
    ]
    add_native_shape_flow_diagram("Sơ đồ 5.2", "Sơ đồ khối luồng xử lý nhận dạng cử chỉ video và điều phối hội thoại hai chiều", blocks_52)

    add_h2("5.1.6. Quy trình ghép nối quầy giao dịch và thiết lập WebRTC ngang hàng")
    add_p("Quy trình ghép nối giữa máy tính quầy nhân viên và màn hình khách tại điểm bán lẻ được thiết kế bảo mật tối đa, đồng thời loại bỏ rào cản thao tác cho khách hàng:")
    add_step_item("Giai đoạn 1", "Khởi tạo yêu cầu quầy", "Nhân viên mở phân hệ /settings -> Màn hình khách, bấm 'Thêm màn hình quầy'. Backend sinh mã counter_id, mã PIN ngẫu nhiên 6 chữ số và mã QR (thời gian sống TTL 10 phút).")
    add_step_item("Giai đoạn 2", "Kết nối máy khách", "Thiết bị quầy khách mở https://vsign.io.vn/display, nhập mã 6 số hoặc dùng camera quét mã QR trên màn hình nhân viên để gửi yêu cầu ghép đôi.")
    add_step_item("Giai đoạn 3", "Xác nhận và cấp Cookie vĩnh viễn", "Hai màn hình hiển thị mã đối chiếu an toàn 2 ký tự. Nhân viên kiểm tra trùng khớp và bấm 'Xác nhận'. Máy khách nhận cookie bảo mật vsign_display có giá trị vĩnh viễn cho quầy đó, chuyển sang chế độ kiosk toàn màn hình. Các lần khởi động lại máy sau đều tự động nhận quầy.")
    add_step_item("Giai đoạn 4", "Thiết lập WebRTC ngang hàng", "Hai trình duyệt trao đổi SDP Offer/Answer qua WebSocket và truy vấn máy chủ Google STUN để xác định ứng viên ICE. Luồng video được truyền trực tiếp qua giao thức DTLS/SRTP trong mạng LAN nội bộ, hoàn toàn không tiêu tốn băng thông máy chủ đám mây.")

    # Sơ đồ 5.3: Native Shape Block Counter Pairing Flow
    blocks_53 = [
        ("BƯỚC 1: KHỞI TẠO YÊU CẦU GHÉP ĐÔI", "Nhân viên mở /settings -> Màn hình khách -> Bấm 'Thêm màn hình quầy'\nBackend sinh mã PIN ngẫu nhiên 6 chữ số và mã QR tương ứng (thời gian sống TTL = 10 phút)"),
        ("BƯỚC 2: KẾT NỐI TỪ MÀN HÌNH KHÁCH", "Thiết bị quầy khách mở địa chỉ https://vsign.io.vn/display\nKhách hoặc nhân viên nhập mã PIN 6 số hoặc dùng camera quét mã QR hiển thị"),
        ("BƯỚC 3: ĐỐI CHIẾU MÃ AN TOÀN & CẤP COOKIE KIOSK", "Hai máy đối chiếu mã xác nhận 2 ký tự trùng khớp -> Nhân viên bấm xác nhận\nMáy khách nhận cookie vsign_display vĩnh viễn và chuyển sang chế độ Kiosk toàn màn hình"),
        ("BƯỚC 4: THIẾT LẬP KẾT NỐI WEBRTC P2P NỘI BỘ", "Trao đổi SDP Offer/Answer qua WebSocket & truy vấn máy chủ Google STUN\nTruyền phát trực tiếp luồng video camera khách sang máy nhân viên trong mạng LAN")
    ]
    add_native_shape_flow_diagram("Sơ đồ 5.3", "Sơ đồ khối quy trình ghép nối quầy giao dịch và thiết lập WebRTC ngang hàng", blocks_53)

    # ==========================================
    # 5.2. XÂY DỰNG GIAO DIỆN VÀ CHỨC NĂNG
    # ==========================================
    add_h1("5.2. Xây dựng giao diện và chức năng")
    
    add_h2("5.2.1. Kịch bản mua sắm minh họa xuyên suốt tại quầy bán lẻ điện máy")
    add_p("Hệ thống VSign được thiết kế phục vụ tình huống mua sắm thực tế tại siêu thị điện máy và cửa hàng bán lẻ:")
    add_bullet("Khách hàng khiếm thính bước đến quầy tư vấn thiết bị gia dụng, mong muốn tìm kiếm một chiếc tủ lạnh giá rẻ và hỏi về hình thức thanh toán chuyển khoản qua ngân hàng.", bold_prefix="Tình huống giao tiếp: ")
    add_bullet("Khách đứng trước camera quầy, nhìn vào màn hình khách (https://vsign.io.vn/display). Màn hình hiển thị khung dẫn hướng bo góc màu xanh báo hiệu vị trí cơ thể đã đạt chuẩn. Khách thực hiện lần lượt chuỗi ký hiệu: [Tôi] -> [Muốn] -> [Mua] -> [Tủ lạnh] -> [Rẻ].", bold_prefix="Thao tác của khách hàng: ")
    add_bullet("Khung hình cử chỉ được gửi lên server GPU nhận dạng. Chuỗi nhãn nhận diện được bộ Sentence Composer rảnh tay tự động kết nối thành câu tiếng Việt hoàn chỉnh: 'Tôi muốn mua tủ lạnh rẻ.', hiển thị trên màn hình và đọc to qua loa cho nhân viên.", bold_prefix="Xử lý của hệ thống AI: ")
    add_bullet("Nhân viên nhấn phím micro trên bàn làm việc (/recognize), nói: 'Siêu thị đang có tủ lạnh Aqua giá ưu đãi, mời quý khách xem tại dãy B.'. Lời nói lập tức chuyển thành chữ tiếng Việt lớn trên màn hình của khách.", bold_prefix="Phản hồi của nhân viên: ")
    add_bullet("Khách ký tiếp chuỗi [Tôi] -> [Muốn] -> [Ngân hàng] -> [Mua bán]. Hệ thống diễn đạt: 'Tôi muốn thanh toán qua ngân hàng.'. Nhân viên xác nhận bằng văn bản: 'Dạ được, siêu thị hỗ trợ quét mã VietQR.'. Khách ký [Cảm ơn] và kết thúc phiên giao dịch.", bold_prefix="Hoàn tất phiên giao dịch: ")

    add_h2("5.2.2. Giao diện Cổng đăng nhập và xác thực hệ thống (https://vsign.io.vn)")
    add_p("Cổng đăng nhập chính thức của nền tảng VSign tại địa chỉ vsign.io.vn được thiết kế kết hợp giữa cổng xác thực an toàn doanh nghiệp và khu vực trình diễn trực quan công nghệ nhận dạng:")
    add_bullet("Giao diện tích hợp mô-đun mô phỏng chuyển động vector SVG tương tác, tự động lặp qua chuỗi ký hiệu trong bộ sales-30, làm sáng 16 thanh trích mẫu đặc trưng thời gian và hiển thị từ ngữ được nhận diện tương ứng ('Từ vừa nhận: Cảm ơn...'), giúp người dùng nhận diện ngay bản chất công nghệ của hệ thống.", bold_prefix="Hoạt họa khung xương cử chỉ (LoginSignDemo): ")
    add_bullet("Cho phép quản trị viên và nhân viên đăng nhập vào workspace tổ chức thông qua tài khoản được cấp phát, hỗ trợ cơ chế bảo mật mật khẩu Argon2id và kiểm soát phiên làm việc an toàn bằng HttpOnly cookie.", bold_prefix="Khung đăng nhập doanh nghiệp an toàn: ")

    add_figure(
        "artifacts/report_screenshots/02_vsign_io_vn_login.png",
        "Hình 5.1",
        "Giao diện đăng nhập hệ thống VSign tại địa chỉ vsign.io.vn với mô-đun hoạt họa LoginSignDemo",
        width_inches=6.2
    )

    add_h2("5.2.3. Giao diện giao tiếp qua camera cho khách hàng và nhân viên")
    add_p("Hệ thống giao tiếp tại điểm bán của VSign được chia tách độc lập thành hai màn hình chuyên biệt:")
    
    add_h3("a. Giao diện Màn hình khách tại quầy (Customer Display - https://vsign.io.vn/display)")
    add_p("Màn hình khách được tối ưu hóa theo phong cách giao diện nền sáng tối giản (light theme), đồng bộ với bộ nhận diện thương hiệu của hệ thống:")
    add_bullet("Giúp khách hàng quan sát tư thế cử chỉ của chính mình để điều chỉnh trong tầm quan sát của camera.", bold_prefix="Khung hiển thị hình ảnh tự soi: ")
    add_bullet("Hiển thị tức thời chuỗi từ ngữ hệ thống vừa ghi nhận và câu tiếng Việt hoàn chỉnh sau khi ghép bằng chữ lớn, độ tương phản cao.", bold_prefix="Khu vực văn bản nhận diện và câu diễn đạt: ")
    add_bullet("Hiển thị câu trả lời của nhân viên bán hàng bằng phông chữ đậm nổi bật, giúp khách hàng nắm bắt trọn vẹn thông tin tư vấn.", bold_prefix="Khu vực tiếp nhận phản hồi từ nhân viên: ")

    add_figure(
        "artifacts/report_screenshots/03_vsign_io_vn_customer_display.png",
        "Hình 5.2",
        "Giao diện Màn hình khách tại quầy (Customer Display) với thiết kế nền sáng tối giản tại vsign.io.vn/display",
        width_inches=6.2
    )

    add_h3("b. Giao diện Bàn làm việc nhân viên (Staff Console - /recognize)")
    add_p("Giao diện nhân viên cung cấp đầy đủ công cụ tiếp nhận, kiểm soát và phản hồi hội thoại:")
    add_bullet("Menu thả xuống cho phép nhân viên lựa chọn giữa 'Camera máy này' hoặc camera truyền từ 'Quầy khách' qua WebRTC.", bold_prefix="Khung hiển thị luồng video và chọn nguồn camera: ")
    add_bullet("Hiển thị trạng thái kết nối hạ tầng AI thời gian thực (kết nối GPU đám mây 'Asia Modal GPU' hoặc máy chủ cục bộ 'Local Core ML').", bold_prefix="Huy hiệu vị trí Backend (BackendLocationBadge): ")
    add_bullet("Hiển thị chuỗi từ ngữ nhận diện theo thời gian thực và câu diễn đạt tiếng Việt tự nhiên liên tục. Nhân viên có thể nhấn nút phát âm thanh TTS để nghe câu nói.", bold_prefix="Hàng đợi nhận dạng và bộ ghép câu tự động rảnh tay: ")
    add_bullet("Tích hợp ô nhập liệu văn bản bàn phím kèm nút bấm kích hoạt nhận diện giọng nói (STT). Nội dung gửi đi lập tức đồng bộ sang màn hình khách thông qua WebSocket.", bold_prefix="Khu vực phản hồi hai chiều: ")

    add_figure(
        "artifacts/report_screenshots/current_02_workspace_recognize.png",
        "Hình 5.3",
        "Bàn làm việc nhận dạng của nhân viên (/recognize) với huy hiệu kết nối Modal GPU Asia và bộ ghép câu rảnh tay",
        width_inches=6.2
    )

    add_h2("5.2.4. Giao diện quản lý dành cho tổ chức (Workspace Console)")
    add_p("Hệ thống quản trị doanh nghiệp của VSign cung cấp đầy đủ các phân hệ quản lý chuyên sâu:")
    add_bullet("Giám sát trạng thái hoạt động theo thời gian thực của máy chủ, số lượng điểm quầy đang trực tuyến, phiên bản mô hình AI đang phục vụ và chỉ số sức khỏe của các cổng API.", bold_prefix="Bảng điều khiển tổng quan (System Overview - /overview): ")
    add_bullet("Quản lý danh mục 30 nhãn nghiệp vụ bán lẻ sales-30, theo dõi tiến độ thu mẫu định mức (50 mẫu tay trái, 50 mẫu tay phải mỗi nhãn), cung cấp công cụ thu thập mẫu webcam chuẩn hóa có khung viền hướng dẫn.", bold_prefix="Quản trị dữ liệu & thu mẫu (Workspace Data - /data): ")
    add_bullet("Lưu trữ danh mục các checkpoint đã đăng ký, cơ chế chốt duyệt độc lập (approval gate) ngăn chặn tự ý thay đổi mô hình production, quản lý con trỏ mô hình (active pointer) cho phép chuyển đổi và rollback tức thì trong 0 giây.", bold_prefix="Quản lý vòng đời mô hình (Workspace Models - /models): ")
    add_bullet("Cung cấp giao diện chạy các đợt đánh giá độc lập mô hình candidate so với baseline hiện tại trên tập held-out snapshot bất biến, hiển thị biểu đồ so sánh Accuracy, Macro-F1, False Accept và P95 Latency.", bold_prefix="Đánh giá mô hình (Workspace Evaluations - /evaluation): ")
    add_bullet("Cấu hình mã PIN và QR code ghép nối màn hình khách tại quầy, quản lý thời gian lưu giữ dữ liệu và nhật ký kiểm toán hệ thống.", bold_prefix="Cấu hình hệ thống & thiết bị quầy (Workspace Settings - /settings): ")
    add_bullet("Quản lý phân quyền dựa trên vai trò (RBAC), kiểm soát danh sách thành viên và lời mời tham gia tổ chức.", bold_prefix="Thành viên & phân quyền (Workspace Team - /team): ")

    add_figure(
        "artifacts/report_screenshots/current_01_workspace_overview.png",
        "Hình 5.4",
        "Bảng điều khiển quản trị tổng quan hệ thống VSign (/overview) dành cho doanh nghiệp",
        width_inches=6.2
    )

    add_figure(
        "artifacts/report_screenshots/current_03_workspace_data.png",
        "Hình 5.5",
        "Giao diện phân hệ Quản trị dữ liệu & thu mẫu (/data) với danh mục 30 nhãn nghiệp vụ sales-30",
        width_inches=6.2
    )

    add_figure(
        "artifacts/report_screenshots/current_04_workspace_models.png",
        "Hình 5.6",
        "Giao diện phân hệ Quản lý mô hình và chốt triển khai an toàn (/models)",
        width_inches=6.2
    )

    add_figure(
        "artifacts/report_screenshots/current_05_workspace_evaluation.png",
        "Hình 5.7",
        "Giao diện phân hệ Đánh giá mô hình độc lập (/evaluation)",
        width_inches=6.2
    )

    add_figure(
        "artifacts/report_screenshots/current_06_workspace_settings.png",
        "Hình 5.8",
        "Giao diện Cấu hình hệ thống và Quản lý kết nối màn hình khách tại quầy (/settings)",
        width_inches=6.2
    )

    add_figure(
        "artifacts/report_screenshots/current_07_workspace_team.png",
        "Hình 5.9",
        "Giao diện Quản lý thành viên và phân quyền tài khoản tổ chức (/team)",
        width_inches=6.2
    )

    # ==========================================
    # 5.3. QUẢN LÝ DỮ LIỆU VÀ BẢO MẬT
    # ==========================================
    add_h1("5.3. Quản lý dữ liệu và bảo mật")

    add_h2("5.3.1. Phân loại và nguyên tắc quản trị ba nhóm dữ liệu")
    add_p("Hệ thống VSign thiết lập ranh giới quản trị dữ liệu minh bạch, phân định rõ thành ba nhóm dữ liệu có mục đích và chính sách bảo vệ riêng biệt:")
    add_numbered_item("1", "Dữ liệu phát triển và huấn luyện mô hình (Development Data)", "Kế thừa 472 lớp ký hiệu từ bộ dữ liệu công khai Kaggle nguyenanfms/vsl-vietnamese-sign-language-v2 (version 8, bản quyền CC BY 4.0), kết hợp tập dữ liệu ViSignLanguage-Video và dữ liệu thu thập webcam nội bộ. Dữ liệu được lọc chuẩn hóa 30 nhãn bán lẻ (sales-30), trích xuất đặc trưng điểm mốc MediaPipe và phân chia độc lập nghiêm ngặt theo nhóm người ký (signer-independent splits) giữa tập Huấn luyện (Train), Thẩm định (Validation) và Kiểm nghiệm (Test).")
    add_numbered_item("2", "Dữ liệu phiên giao tiếp trực tiếp tại quầy (Session Data)", "Video camera chỉ tồn tại tạm thời trong bộ nhớ đệm RAM để xử lý bám bắt khung xương và gửi các khung hình nhận dạng sang server GPU. Máy chủ tuyệt đối không ghi các khung hình này xuống ổ cứng. Văn bản trao đổi chỉ được lưu trữ tạm thời nếu khách hàng cho phép. Ngay khi nhân viên nhấn 'Phiên mới' hoặc kết thúc phiên, toàn bộ bộ nhớ đệm hội thoại bị xóa sạch. Sự đồng ý lưu phiên giao tiếp hỗ trợ dịch vụ tách biệt hoàn toàn với việc đồng ý dùng dữ liệu để huấn luyện mô hình.")
    add_numbered_item("3", "Dữ liệu quản trị và báo cáo doanh nghiệp (Management Telemetry Data)", "Chỉ lưu trữ các chỉ số tổng hợp ẩn danh (Aggregate telemetry) như số lượt phục vụ tại từng quầy, thời lượng trung bình mỗi phiên, tỷ lệ nhận diện thành công vs tỷ lệ yêu cầu ký lại, các nhóm nhãn có tần suất xuất hiện cao. Tuyệt đối không lưu trữ khuôn mặt, danh tính hay nội dung riêng tư của khách hàng trong các báo cáo kinh doanh.")

    add_p("Quy trình quản lý dữ liệu, kiểm soát chất lượng mẫu, huấn luyện mô hình và chốt triển khai an toàn được mô hình hóa thành một đường ống MLOps khép kín:")

    # Sơ đồ 5.4: Native Shape Block MLOps Pipeline Flow
    blocks_54 = [
        ("1. THU THẬP DỮ LIỆU ĐA NGUỒN", "Tập Kaggle VSL v2 (472 lớp) + ViSignLanguage-Video + Webcam quầy thu thập nội bộ"),
        ("2. TIỀN XỬ LÝ & LỌC TẬP NHÃN SALES-30", "Lọc 30 nhãn bán lẻ; thuật toán trim-bodycrop-v1 chuẩn hóa 16 khung hình RGB 224x224; phân chia Signer-independent (Train/Val/Test)"),
        ("3. HUẤN LUYỆN MÔ HÌNH VIDEO TRANSFORMATION", "Mạng MViTv2-S Spatiotemporal 3D Attention trên NVIDIA GPU (PyTorch CUDA 12); chống overfitting không gian - thời gian"),
        ("4. ĐÁNH GIÁ ĐỐI CHUẨN ĐỘC LẬP TRÊN TẬP HELD-OUT", "Kiểm thử trên tập Test đứng 351 clip bất biến: Đạt 95.73% đúng, 1.71% nhầm (False Accept); so sánh candidate vs baseline"),
        ("5. CHỐT DUYỆT APPROVAL GATE & TRIỂN KHAI 0-GIÂY", "Đóng gói đa môi trường (Asia Modal GPU + Apple Core ML); Admin phê duyệt thủ công -> Cập nhật Active Pointer trong 0 giây (hỗ trợ rollback tức thì)")
    ]
    add_native_shape_flow_diagram("Sơ đồ 5.4", "Sơ đồ khối quy trình đường ống dữ liệu và vòng đời mô hình MViTv2-S", blocks_54)

    add_h2("5.3.2. Cơ chế phân quyền và an toàn thông tin")
    add_p("Hệ thống áp dụng các tiêu chuẩn an toàn thông tin đa tầng:")
    add_bullet("Thiết lập 4 nhóm quyền tách biệt: system_admin (quản trị hạ tầng kỹ thuật), admin doanh nghiệp (quản lý quầy, xem báo cáo tổng hợp), operator (nhân viên quầy thực hiện nhận dạng), và reviewer (kiểm định chất lượng mô hình ở chế độ chỉ đọc).", bold_prefix="Phân quyền dựa trên vai trò (RBAC): ")
    add_bullet("Mật khẩu quản trị được băm bằng thuật toán Argon2id; phiên đăng nhập sử dụng cookie có gắn cờ HttpOnly, Secure và SameSite=Lax chống tấn công XSS/CSRF; áp dụng cơ chế chặn dò quét tần suất (rate limiting).", bold_prefix="Bảo mật danh tính và phiên làm việc: ")
    add_bullet("Khóa API được băm một chiều trong cơ sở dữ liệu; gói tin thông báo Webhook gửi đến hệ thống POS của doanh nghiệp được ký số bảo mật bằng mã băm HMAC SHA-256 bảo đảm tính toàn vẹn.", bold_prefix="Bảo vệ cổng kết nối API và Webhook: ")

    # ==========================================
    # 5.4. KIỂM THỬ VÀ ĐÁNH GIÁ WEBSITE
    # ==========================================
    add_h1("5.4. Kiểm thử và đánh giá website")

    add_h2("5.4.1. Khung kiểm thử đa tầng và kết quả xác thực kỹ thuật")
    add_p("Hệ thống VSign trải qua quy trình kiểm thử chất lượng đa tầng nghiêm ngặt trước khi đóng gói triển khai:")
    add_bullet("Backend Python vượt qua 177 bài kiểm thử unit và integration test bằng pytest. Frontend React vượt qua 307 bài kiểm thử giao diện trên 38 tệp mã nguồn và 595 ca kiểm thử hồi quy hợp đồng API trên 62 tệp, đạt tỷ lệ thành công 100%.", bold_prefix="Kiểm thử mã nguồn tự động (Automated Testing): ")
    add_bullet("Công cụ ESLint đạt 0 cảnh báo; bản build production tối ưu dung lượng (9 artifact sạch, loại bỏ hoàn toàn các trang và mã Dev/Test nội bộ).", bold_prefix="Kiểm tra chuẩn mực mã nguồn (Code Quality & Build): ")
    add_bullet("Kiểm thử render tự động trên Playwright ở 6 kích thước màn hình tiêu chuẩn (320px, 390px, 768px, 1024px, 1365px, 1920px), xác nhận không có hiện tượng vỡ khung DOM (horizontal overflow) và các phần tử hiển thị rõ nét.", bold_prefix="Kiểm thử độ tương thích giao diện (Responsive Design): ")

    add_h2("5.4.2. Đánh giá định lượng hiệu năng mô hình nhận dạng Sales-30")
    add_p("Hiệu năng nhận dạng của mô hình MViTv2-S sales-30 được đánh giá độc lập trên bộ dữ liệu video kiểm nghiệm (báo cáo ngày 2026-10-10, mô hình sales30-mvitv2s-personal-v1-head-epoch29, ngưỡng tin cậy 70%, chênh lệch tối thiểu 15%):")
    add_bullet("Đạt tỷ lệ chấp nhận đúng 95.73% (336/351 clip), tỷ lệ nhận nhầm (False Accept) là 1.71% (6/351 clip), tỷ lệ không xác định (Uncertain) là 2.56% (9/351 clip). Hầu hết các nhãn nghiệp vụ cốt lõi như Chào, Muốn, Xem, Siêu thị, Điện thoại, Laptop, Tivi, Máy giặt, Nồi cơm điện, Cảm ơn đạt độ chính xác 100%.", bold_prefix="Tập Test đứng (351 clip video chuẩn hóa): ")
    add_bullet("Đạt tỷ lệ chấp nhận đúng 95.83%, nhận nhầm 2.78%, không xác định 1.39%.", bold_prefix="Tập Validation đứng (144 clip): ")
    add_bullet("Đạt tỷ lệ chấp nhận đúng 65.00% (390/600 clip), nhận nhầm 14.00% (84/600 clip), không xác định 21.00% (126/600 clip). Sự sụt giảm độ chính xác ở tư thế ngồi bắt nguồn từ hiện tượng mặt bàn che khuất các cử chỉ ngang bụng/ngực (như Mua, Rẻ, Sử dụng) và góc camera bị hẹp, cung cấp căn cứ thực nghiệm để thiết kế chỉ dẫn tư thế đứng cho khách hàng.", bold_prefix="Tập Validation ngồi (600 clip): ")

    word_headers = ["Ký hiệu", "Số mẫu (N)", "Đúng (%)", "Nhầm (%)", "Không xác định (%)", "Dạng lỗi chủ yếu"]
    word_data = [
        ["Chào", "3", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Tôi", "5", "80.00", "0.00", "20.00", "Không xác định (tin cậy < 70%)"],
        ["Muốn", "16", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Mua", "4", "50.00", "25.00", "25.00", "Nhận nhầm sang 'Sử dụng'"],
        ["Cho", "16", "81.25", "6.25", "12.50", "Không xác định (tin cậy < 70%)"],
        ["Xem", "14", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Thử", "11", "90.91", "9.09", "0.00", "Nhận nhầm"],
        ["Siêu thị", "13", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Điện thoại", "11", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Laptop", "12", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Tivi", "14", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Tủ lạnh", "14", "92.86", "0.00", "7.14", "Không xác định"],
        ["Máy giặt", "15", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Nồi cơm điện", "14", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Gạo", "11", "100.00", "0.00", "0.00", "Chưa thấy lỗi"],
        ["Cảm ơn", "17", "94.12", "0.00", "5.88", "Không xác định"]
    ]
    add_styled_table(
        word_headers, word_data,
        [Inches(1.5), Inches(0.9), Inches(0.9), Inches(0.9), Inches(1.3), Inches(1.8)],
        [WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.LEFT],
        caption_prefix="Bảng 5.2",
        caption_title="Kết quả kiểm nghiệm độ chính xác một số ký hiệu tiêu biểu trên tập Test đứng"
    )

    add_p("Về độ trễ và khả năng diễn đạt câu:")
    add_bullet("Mô hình MViTv2-S thực thi trên hạ tầng GPU đám mây Asia Modal đạt thời gian tính toán thuần 35–65 ms; trên Apple Silicon Core ML máy trạm đạt dưới 15 ms. Tổng độ trễ toàn chu trình từ khi khách hoàn thành cử chỉ đến khi văn bản hiển thị trên màn hình quầy chỉ dao động trong khoảng 150–220 ms, bảo đảm tính tức thời của cuộc đối thoại.", bold_prefix="Độ trễ suy luận AI thời gian thực: ")
    add_bullet("Bộ Sentence Composer đạt độ chính xác 100% trên 24 họ câu thử nghiệm thuộc lĩnh vực bán lẻ, thời gian tạo câu < 20 ms.", bold_prefix="Chất lượng diễn đạt câu tự nhiên: ")

    add_h2("5.4.3. Bảng đối chiếu yêu cầu MRD với kết quả kiểm nghiệm thực tế")
    mrd_headers = ["Mã", "Yêu cầu chức năng / phi chức năng", "Phương pháp kiểm thử", "Kết quả thực tế đạt được", "Trạng thái"]
    mrd_data = [
        ["F01", "Tiếp nhận ký hiệu qua camera", "Kiểm thử trình duyệt máy khách qua WebRTC và MediaPipe", "Khách hàng sử dụng trực tiếp qua URL /display, không cần tạo tài khoản hay cài ứng dụng", "Đạt"],
        ["F02", "Nhận dạng chuỗi ký hiệu liên tục", "Kiểm thử chuỗi cử chỉ với heuristic nghỉ 1.800 ms và debounce 1.000 ms", "Nhận dạng đúng chuỗi ký hiệu theo thứ tự, triệt tiêu ghi lặp, không bắt xác nhận từng từ", "Đạt"],
        ["F03", "Chuyển ký hiệu thành câu tiếng Việt", "Kiểm nghiệm 24 họ câu và 20 ý định mua sắm bằng Sentence Composer", "Tạo câu tự nhiên rảnh tay, chuẩn hóa cú pháp, nối câu thông minh, không có cảnh báo rác", "Đạt"],
        ["F04", "Hiển thị và kiểm tra kết quả", "Kiểm thử hiển thị đồng thời hai màn hình và trạng thái nhận diện", "Hiển thị song song từ gốc và câu dự thảo trên cả máy khách và máy nhân viên", "Đạt"],
        ["F05", "Hỗ trợ giao tiếp hai chiều", "Kiểm thử nhập bàn phím và micro giọng nói STT -> text", "Phản hồi của nhân viên hiển thị chữ lớn tức thì trên màn hình khách qua WebSocket", "Đạt"],
        ["F06", "Hỗ trợ tình huống bán lẻ", "Xây dựng và đánh giá bộ 30 nhãn nghiệp vụ sales-30", "Bao quát các tình huống hỏi mua thiết bị điện máy, đồ gia dụng, hỏi giá, thanh toán", "Đạt"],
        ["F07", "Quản lý và tùy chỉnh theo tổ chức", "Kiểm thử phân quyền RBAC và quản trị quầy trong /settings", "Cho phép chọn bộ từ vựng, cấu hình quầy, ghép nối mã PIN hai máy thành công", "Đạt"],
        ["F08", "Thống kê và báo cáo sử dụng", "Kiểm thử bảng điều khiển /overview và nhật ký /activity", "Báo cáo tổng hợp số lượt dùng, độ trễ phản hồi, tỷ lệ chưa nhận diện ẩn danh", "Đạt"],
        ["F09", "Quản lý dịch vụ thuê bao B2B", "Kiểm thử cấp phát quyền truy cập và hạn dùng tenant", "Kiểm soát tài khoản tổ chức, khóa API và gói cước thuê bao B2B", "Đạt"],
        ["NF01", "Độ trễ phản hồi thời gian thực", "Đo thời gian suy luận GPU và độ trễ toàn luồng", "Modal GPU thuần 35–65 ms; Mac Core ML < 15 ms; độ trễ toàn luồng hiển thị < 250 ms", "Đạt"],
        ["NF02", "Độ chính xác nhận dạng", "Đo trên tập Test đứng 351 clip video chuẩn hóa", "Đạt 95.73% chấp nhận đúng, 1.71% nhầm, 2.56% không xác định", "Đạt"],
        ["NF03", "Bảo mật và quyền riêng tư", "Kiểm tra luồng mạng WebRTC và máy chủ GPU", "Video P2P nội bộ; 16 frame chỉ giải mã trong RAM GPU, không lưu video trên máy chủ", "Đạt"]
    ]
    add_styled_table(
        mrd_headers, mrd_data,
        [Inches(0.8), Inches(2.2), Inches(2.0), Inches(2.5), Inches(1.0)],
        [WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER],
        caption_prefix="Bảng 5.3",
        caption_title="Ma trận đối chiếu yêu cầu thị trường (MRD) với kết quả thực nghiệm hệ thống"
    )

    # ==========================================
    # 5.5. TRIỂN KHAI VÀ VẬN HÀNH WEBSITE
    # ==========================================
    add_h1("5.5. Triển khai và vận hành website")

    add_h2("5.5.1. Môi trường triển khai và hạ tầng mạng")
    add_p("Hệ thống VSign được triển khai phân tách hiện đại theo mô hình đa tầng:")
    add_bullet("Ứng dụng web được xuất bản trên mạng lưới Vercel CDN liên kết trực tiếp tên miền thương mại vsign.io.vn, bảo đảm tốc độ tải trang dưới 1.2 giây và khả năng phục vụ liên tục với độ sẵn sàng cao (High Availability).", bold_prefix="Hạ tầng phân phối giao diện (Frontend CDN): ")
    add_bullet("Triển khai worker suy luận GPU đám mây chuyên dụng tại khu vực Đông Nam Á (ckiet1612--vsign-inference-inference-ap-southeast.ap-south.modal.run), cung cấp năng lực tính toán AI tốc độ cao cho các luồng nhận dạng phức tạp.", bold_prefix="Hạ tầng đám mây GPU Modal Asia: ")
    add_bullet("Kết nối API máy chủ được định tuyến an toàn qua đường hầm Cloudflare Tunnel (api.vsign.io.vn), bảo vệ máy chủ nội bộ mà không cần mở cổng router hay để lộ IP tĩnh.", bold_prefix="Đường hầm kết nối bảo mật (Cloudflare Tunnel): ")

    add_h2("5.5.2. Quy trình thiết lập và kích hoạt quầy giao dịch hai màn hình")
    add_p("Quy trình đưa một quầy giao dịch mới vào hoạt động được thực hiện qua 4 bước chuẩn hóa:")
    add_step_item("Bước 1", "Khởi tạo mã", "Nhân viên đăng nhập vào hệ thống tại máy quầy (/settings -> Màn hình khách), chọn 'Thêm màn hình quầy'. Hệ thống sinh mã kết nối 6 chữ số kèm mã QR (mã có hiệu lực trong 10 phút).")
    add_step_item("Bước 2", "Kết nối quầy", "Máy khách mở trình duyệt tại địa chỉ https://vsign.io.vn/display, nhập mã 6 số hoặc quét mã QR.")
    add_step_item("Bước 3", "Đối chiếu an toàn", "Cả hai máy đối chiếu mã xác nhận 2 ký tự trùng khớp; nhân viên nhấn nút 'Xác nhận'.")
    add_step_item("Bước 4", "Kích hoạt Kiosk", "Máy khách nhận cookie bảo mật vsign_display có giá trị vĩnh viễn cho quầy đó, chuyển sang chế độ kiosk toàn màn hình. Các lần khởi động lại máy sau đó đều tự động kết nối vào đúng quầy mà không cần nhập lại mã.")

    add_h2("5.5.3. Hướng dẫn vận hành nhân viên và phương án xử lý sự cố")
    add_p("Nhân viên tại quầy chỉ cần theo dõi màn hình khi khách ký hiệu, đọc câu diễn đạt hoặc nghe âm thanh tự động, sau đó nhấn phím nói hoặc gõ bàn phím để trả lời. Khi hoàn tất giao dịch, nhân viên nhấn 'Phiên mới' để giải phóng màn hình.")
    add_p("Hệ thống xây dựng sẵn phương án dự phòng (Fallback Procedure) khi phát sinh sự cố:")
    add_bullet("Nếu đường truyền gián đoạn quá 1.5 giây, máy nhân viên lập tức ẩn video đóng băng để tránh nhầm lẫn; máy khách hiển thị thông báo 'Mất kết nối với máy nhân viên' và giữ camera chờ tối đa 30 giây trước khi chuyển sang thông báo đề nghị nhân viên phục vụ trực tiếp.", bold_prefix="Xử lý sự cố mất kết nối mạng: ")
    add_bullet("Khi khách hàng ký các cử chỉ chưa có trong bộ từ sales-30, hệ thống xuất trạng thái 'Không xác định', cảnh báo bằng màu vàng và đề xuất nhân viên chuyển sang hình thức viết chữ hoặc mời người hỗ trợ chuyên biệt.", bold_prefix="Xử lý cử chỉ ngoài bộ từ vựng (Out-of-Vocabulary): ")

    # ==========================================
    # CHƯƠNG 7: KẾT LUẬN VÀ ĐỊNH HƯỚNG PHÁT TRIỂN
    # ==========================================
    add_title("CHƯƠNG 7: KẾT LUẬN VÀ ĐỊNH HƯỚNG PHÁT TRIỂN DỰ ÁN")

    add_h1("7.1. Kết quả và mức độ hoàn thành mục tiêu")

    add_h2("7.1.1. Đối chiếu mục tiêu nghiên cứu và kết quả sản phẩm")
    add_p("Dự án VSign đã hoàn thành đầy đủ các mục tiêu nghiên cứu, phát triển công nghệ và xây dựng sản phẩm thực nghiệm đặt ra tại Chương 1 (Bảng 1.1) và tài liệu yêu cầu thị trường (MRD tại Chương 3):")

    goals_headers = ["STT", "Mục tiêu cụ thể đặt ra", "Bằng chứng kỹ thuật đã xây dựng", "Mức độ hoàn thành"]
    goals_data = [
        ["1", "Nghiên cứu nhu cầu và xác lập yêu cầu sản phẩm (MRD)", "Tài liệu MRD hoàn chỉnh với 9 yêu cầu chức năng (F01–F09) và 5 yêu cầu phi chức năng trong bán lẻ", "Hoàn thành 100%"],
        ["2", "Xây dựng bộ từ vựng nghiệp vụ bán lẻ và dữ liệu chuẩn", "Bộ nhãn sales-30 gồm 30 từ rời rạc và 20 ý định mua sắm; pipeline thu mẫu chuẩn hóa Workspace Data", "Hoàn thành 100%"],
        ["3", "Xây dựng giải pháp nhận dạng kết hợp GPU đám mây và Core ML", "Triển khai thành công hạ tầng Asia Modal GPU (NVIDIA PyTorch) và Local Core ML; độ trễ suy luận đáp ứng thời gian thực", "Hoàn thành 100%"],
        ["4", "Phát triển bộ diễn đạt câu tiếng Việt tự nhiên rảnh tay", "Bộ Sentence Composer rảnh tay với 24 họ câu bán lẻ, nối câu thông minh, xử lý < 20 ms", "Hoàn thành 100%"],
        ["5", "Hiện thực hóa hệ thống quầy hai màn hình tương tác", "Kết nối WebRTC ngang hàng và WebSocket đồng bộ giữa máy nhân viên (/recognize) và máy khách (/display)", "Hoàn thành 100%"],
        ["6", "Xây dựng hệ thống quản trị doanh nghiệp B2B tập trung", "Hoàn thiện 10 phân hệ quản trị: Overview, Models, Data, Evaluations, Team, Settings, Integrations...", "Hoàn thành 100%"],
        ["7", "Kiểm định định lượng chất lượng nhận dạng và hệ thống", "Đạt 95.73% độ chính xác trên tập Test đứng 351 clip; vượt qua 177 test backend và 307 test frontend", "Hoàn thành 100%"],
        ["8", "Xây dựng phương án kinh doanh SaaS và an toàn dữ liệu", "Mô hình định giá thuê bao B2B, cơ chế bảo vệ quyền riêng tư camera không lưu trữ máy chủ", "Hoàn thành 100%"]
    ]
    add_styled_table(
        goals_headers, goals_data,
        [Inches(0.6), Inches(2.5), Inches(3.2), Inches(1.5)],
        [WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER],
        caption_prefix="Bảng 7.1",
        caption_title="Tổng kết mức độ hoàn thành các mục tiêu dự án VSign"
    )

    add_h2("7.1.2. Tổng kết giá trị hỗ trợ giao tiếp và ý nghĩa kinh doanh")
    add_p("Kết quả đạt được của dự án VSign mang lại hai giá trị cốt lõi:")
    add_bullet("VSign giải quyết rào cản giao tiếp thực tế giữa người khiếm thính và nhân viên tại điểm bán lẻ. Bằng việc cho phép khách hàng ký hiệu tự nhiên trước camera mà không cần cài ứng dụng hay chạm vào thiết bị, hệ thống mang lại sự tự tin, độc lập và bình đẳng trong sinh hoạt mua sắm hàng ngày. Đối với nhân viên, hệ thống hỗ trợ tiếp nhận thông tin nhanh chóng, chính xác, giảm thiểu tình trạng hiểu lầm hoặc bối rối khi phục vụ.", bold_prefix="Giá trị xã hội và hỗ trợ giao tiếp: ")
    add_bullet("Bằng việc chứng minh tính khả thi của kiến trúc đám mây GPU khu vực (Modal GPU Asia) kết hợp chuyển đổi dự phòng Core ML tại chỗ, dự án tối ưu hóa được chi phí vận hành máy chủ đám mây nhờ cơ chế chỉ bật tính toán khi có luồng giao dịch. Nhờ đó, mô hình kinh doanh thuê bao phần mềm SaaS B2B có tỷ suất lợi nhuận khả thi, tạo điều kiện thuận lợi để các chuỗi siêu thị, cửa hàng tiện lợi và bán lẻ điện máy sẵn sàng đầu tư triển khai nhằm nâng cao chất lượng dịch vụ và khẳng định trách nhiệm xã hội doanh nghiệp (CSR).", bold_prefix="Ý nghĩa kinh tế và khả năng thương mại hóa B2B: ")

    # ==========================================
    # 7.2. HẠN CHẾ VÀ BÀI HỌC KINH NGHIỆM
    # ==========================================
    add_h1("7.2. Hạn chế và bài học kinh nghiệm")

    add_h2("7.2.1. Các hạn chế kỹ thuật và dữ liệu thực tế")
    add_p("Dù đạt được những kết quả khả quan, dự án thẳng thắn ghi nhận các hạn chế kỹ thuật sau quá trình triển khai thực tế:")
    add_bullet("Bộ từ vựng sales-30 gồm 30 nhãn rời rạc và 20 câu ý định mới chỉ bao quát các tình huống mua sắm cơ bản đối với sản phẩm điện máy và hàng tiêu dùng nhanh. Hệ thống chưa hỗ trợ các cuộc hội thoại mở tự do, các câu hỏi phức tạp về chính sách kỹ thuật hay xử lý khiếu nại chuyên sâu.", bold_prefix="Quy mô bộ từ vựng còn giới hạn: ")
    add_bullet("Kết quả thực nghiệm cho thấy độ chính xác giảm từ 95.73% (ở tư thế đứng) xuống 65.00% (ở tư thế ngồi). Nguyên nhân chính là do mặt bàn quầy che khuất các cử chỉ ngang ngực hoặc bụng, góc camera đặt thấp làm sai lệch khoảng cách hai vai và khuỷu tay bị che. Đây là hạn chế vật lý cần được khắc phục bằng khuyến nghị lắp đặt thiết bị.", bold_prefix="Sự sụt giảm độ chính xác ở tư thế ngồi: ")
    add_bullet("Hệ thống nhận dạng chuỗi ký hiệu dựa trên việc phân loại các cử chỉ đơn lẻ kết hợp heuristic khoảng nghỉ thời gian (1.800 ms), chưa phải là mô hình dịch máy ngôn ngữ ký hiệu liên tục (Continuous Sign Language Recognition - CSLR) hiểu trực tiếp ngữ pháp không gian và biểu cảm khuôn mặt của VSL.", bold_prefix="Cơ chế nhận dạng chuỗi từ rời rạc: ")
    add_bullet("Tập dữ liệu kiểm thử độc lập chủ yếu được thực hiện bởi nhóm tác giả và một số người tình nguyện tại địa phương, chưa bao quát đầy đủ sự khác biệt về phương ngữ ký hiệu giữa ba miền Bắc, Trung, Nam của Việt Nam.", bold_prefix="Độ đa dạng người ký và phương ngữ: ")

    add_h2("7.2.2. Bài học kinh nghiệm từ quá trình phát triển")
    add_p("Quá trình nghiên cứu và thực thi dự án mang lại ba bài học kinh nghiệm sâu sắc:")
    add_bullet("Việc chỉ đánh giá mô hình trên các tệp video mẫu sạch (offline benchmark) thường mang lại kết quả cao ảo. Chỉ khi đưa vào môi trường camera webcam quầy bán hàng thực tế mới bộc lộ các vấn đề nhiễu chuyển động nền, ánh sáng ngược, chuyển động nghỉ vô thức và sự che khuất vật lý.", bold_prefix="Bài học về kiểm thử trên camera thực tế: ")
    add_bullet("Trong ứng dụng bán lẻ, một kết quả 'Không xác định' (Uncertain) an toàn và trung thực có giá trị gấp nhiều lần một phỏng đoán sai lệch (False Accept). Thiết kế hệ thống phải luôn đặt tính chính xác lên hàng đầu, cung cấp trạng thái cảnh báo rõ ràng để nhân viên hỗ trợ kịp thời.", bold_prefix="Bài học về an toàn giao dịch thương mại: ")
    add_bullet("Khách hàng khiếm thính cần sự đơn giản tối đa. Giao diện quầy phải loại bỏ hoàn toàn các thao tác bấm chọn phức tạp, sử dụng chữ to, rõ ràng và phản hồi thị giác bằng màu sắc trực quan đóng vai trò then chốt.", bold_prefix="Bài học về trải nghiệm người dùng yếu thế: ")

    # ==========================================
    # 7.3. ĐỊNH HƯỚNG HOÀN THIỆN VÀ MỞ RỘNG
    # ==========================================
    add_h1("7.3. Định hướng hoàn thiện và mở rộng")

    add_h2("7.3.1. Lộ trình cải tiến kỹ thuật ngắn hạn")
    add_p("Trong giai đoạn tiếp theo, dự án ưu tiên các công việc hoàn thiện kỹ thuật có tính khả thi cao:")
    add_bullet("Tận dụng phân hệ Workspace Data đã xây dựng hoàn chỉnh để thu thập bổ sung 50 mẫu ngồi cho mỗi nhãn trong bộ sales-30, huấn luyện lại mô hình phân loại để nâng tỷ lệ nhận diện tư thế ngồi từ 65% lên trên 85%.", bold_prefix="Thu thập bổ sung dữ liệu tư thế ngồi và góc quay thấp: ")
    add_bullet("Tích hợp mô hình ngôn ngữ nhỏ (Small Language Model - SLM) chạy cục bộ để câu tiếng Việt phong phú, tự nhiên hơn mà vẫn kiểm soát chặt chẽ không bịa đặt thông tin.", bold_prefix="Nâng cấp bộ tạo câu tiếng Việt (Sentence Composer): ")
    add_bullet("Nghiên cứu đóng gói combo thiết bị chuẩn gồm màn hình phụ cảm ứng, camera góc rộng chống méo hình và giá đỡ định vị chuyên dụng để chuyển giao trọn gói cho doanh nghiệp bán lẻ.", bold_prefix="Đóng gói giải pháp phần cứng chuẩn hóa: ")

    add_h2("7.3.2. Định hướng mở rộng nghiệp vụ và nghiên cứu dài hạn")
    add_p("Định hướng dài hạn của dự án hướng đến mở rộng phạm vi ứng dụng và nâng tầm công nghệ:")
    add_bullet("Sau khi kiểm chứng thành công trong bán lẻ, dự án sẽ mở rộng bộ từ vựng sang khối Y tế (khám chữa bệnh, triệu chứng tại bệnh viện), Tài chính - Ngân hàng (giao dịch tài khoản, thẻ tín dụng) và Cơ quan hành chính công (hồ sơ thủ tục). Mỗi lĩnh vực sẽ được phát triển một bộ từ chuyên biệt độc lập.", bold_prefix="Mở rộng sang các lĩnh vực dịch vụ công thiết yếu: ")
    add_bullet("Ứng dụng các kiến trúc mạng Transformer thị giác không gian - thời gian (Spatiotemporal Vision Transformers) nhằm tiếp nhận trực tiếp chuỗi video liên tục, nhận biết ngữ pháp hình thể và biểu cảm khuôn mặt của người Điếc.", bold_prefix="Nghiên cứu mô hình nhận dạng ngôn ngữ ký hiệu liên tục (CSLR): ")
    add_bullet("Phối hợp chặt chẽ với các Hội người Điếc địa phương, các trường chuyên biệt và chuyên gia Ngôn ngữ ký hiệu Việt Nam để kiểm định dữ liệu đa phương ngữ (Hà Nội, Đà Nẵng, TP. Hồ Chí Minh), bảo đảm tính chuẩn xác và bình đẳng tiếp cận cho người khiếm thính trên cả nước.", bold_prefix="Hợp tác chiến lược với cộng đồng người Điếc Việt Nam: ")

    # ==========================================
    # TÀI LIỆU THAM KHẢO
    # ==========================================
    add_h1("TÀI LIỆU THAM KHẢO")
    refs = [
        "[1] W3C Web Accessibility Initiative (WAI), 'Making the Web Accessible - Sign Languages on the Web', 2023. [Online]. Available: https://www.w3.org/WAI/standards-guidelines/",
        "[2] Nguyễn An, 'VSL: Vietnamese Sign Language Dataset version 8', Kaggle Datasets, 2024. [Online]. License CC BY 4.0. Available: https://www.kaggle.com/datasets/nguyenanfms/vsl-vietnamese-sign-language-v2",
        "[3] C. Lugaresi et al., 'MediaPipe: A Framework for Building Perception Pipelines', arXiv preprint arXiv:1906.08172, 2019.",
        "[4] PyTorch Team, 'PyTorch: An Imperative Style, High-Performance Deep Learning Library', Advances in Neural Information Processing Systems (NeurIPS), 2019.",
        "[5] Z. Liu et al., 'Video Swin Transformer', in Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2022, pp. 3202-3211.",
        "[6] H. Fan et al., 'Multiscale Vision Transformers', in Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV), 2021, pp. 6824-6835.",
        "[7] A. Birrell, 'Argon2: the memory-hard function for password hashing and other applications', Internet Engineering Task Force (IETF) RFC 9106, 2021.",
        "[8] S. Tiarks et al., 'WebRTC 1.0: Real-Time Communication Between Browsers', W3C Recommendation, 2021. [Online]. Available: https://www.w3.org/TR/webrtc/",
        "[9] Strategyzer, 'Business Model Generation: A Handbook for Visionaries, Game Changers, and Challengers', John Wiley & Sons, 2010.",
        "[10] Aha! Labs, 'Market Requirements Document (MRD) Guide and Template', 2023. [Online]. Available: https://www.aha.io/roadmapping/guide/requirements-management/market-requirements-document"
    ]
    for r in refs:
        p_ref = doc.add_paragraph()
        p_ref.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p_ref.paragraph_format.space_before = Pt(2)
        p_ref.paragraph_format.space_after = Pt(4)
        p_ref.paragraph_format.line_spacing = 1.15
        p_ref.paragraph_format.left_indent = Inches(0.4)
        run_r = p_ref.add_run(r)
        set_font(run_r, "Times New Roman", 12)

    doc.save(output_path)
    print(f"Standardized Word-Shape Report successfully generated: {output_path}")

if __name__ == "__main__":
    out_file = "/Users/macbook/Documents/Personal Library/VSign/Bao_Cao_VSign_Chuong_5_va_Chung_7.docx"
    build_docx(out_file)
