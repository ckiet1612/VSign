# -*- coding: utf-8 -*-
"""
Test building all 4 diagrams natively in Word using clean shape blocks.
"""
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

def create_native_shape_block_diagram(doc, caption_prefix, caption_title, blocks, width_in=6.0):
    # Caption ABOVE or BELOW? In academic reports, diagram captions are placed BELOW the diagram.
    # First, container table for the flow
    total_rows = len(blocks) * 2 - 1
    table = doc.add_table(rows=total_rows, cols=1)
    table.alignment = docx.enum.table.WD_TABLE_ALIGNMENT.CENTER
    
    row_idx = 0
    for i, (title, subtext) in enumerate(blocks):
        # Box cell
        cell = table.rows[row_idx].cells[0]
        cell.width = Inches(width_in)
        
        tcPr = cell._tc.get_or_add_tcPr()
        # 1.5pt solid black border
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
        
        # Internal padding
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
        p.alignment = docx.enum.text.WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.15
        
        r_title = p.add_run(title + "\n")
        r_title.font.name = "Times New Roman"
        r_title.font.size = Pt(13)
        r_title.bold = True
        r_title.font.color.rgb = RGBColor(0, 0, 0)
        
        r_sub = p.add_run(subtext)
        r_sub.font.name = "Times New Roman"
        r_sub.font.size = Pt(11)
        r_sub.font.color.rgb = RGBColor(40, 40, 40)
        
        if i < len(blocks) - 1:
            # Arrow row
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
            p_a.alignment = docx.enum.text.WD_ALIGN_PARAGRAPH.CENTER
            p_a.paragraph_format.space_before = Pt(2)
            p_a.paragraph_format.space_after = Pt(2)
            
            r_arr = p_a.add_run("▼")
            r_arr.font.name = "Times New Roman"
            r_arr.font.size = Pt(13)
            r_arr.bold = True
            r_arr.font.color.rgb = RGBColor(0, 0, 0)
            row_idx += 2
        else:
            row_idx += 1
            
    # Caption BELOW diagram
    p_cap = doc.add_paragraph()
    p_cap.alignment = docx.enum.text.WD_ALIGN_PARAGRAPH.CENTER
    p_cap.paragraph_format.space_before = Pt(6)
    p_cap.paragraph_format.space_after = Pt(14)
    
    r_pre = p_cap.add_run(caption_prefix + ": ")
    r_pre.font.name = "Times New Roman"
    r_pre.font.size = Pt(12)
    r_pre.bold = True
    r_pre.font.color.rgb = RGBColor(15, 23, 42)
    
    r_title = p_cap.add_run(caption_title)
    r_title.font.name = "Times New Roman"
    r_title.font.size = Pt(12)
    r_title.italic = True
    r_title.font.color.rgb = RGBColor(51, 65, 85)

doc = docx.Document()
blocks_52 = [
    ("1. THU NHẬN HÌNH ẢNH CỬ CHỈ", "Camera quầy khách thu nhận video 30 khung hình/giây liên tục"),
    ("2. BÁM BẮT ĐẶC TRƯNG & CẮT VÙNG THÂN TRÊN ROI", "MediaPipe bám bắt 21 mốc tay + 11 mốc thân; thuật toán trim-bodycrop-v1 đóng gói 16 khung hình RGB 224x224"),
    ("3. SUY LUẬN NHẬN DẠNG TRÊN MÁY CHỦ GPU", "Gửi chuỗi 16 frame qua WebSocket lên Asia Modal GPU (NVIDIA L4 PyTorch); ngưỡng tin cậy 40%, margin 0.0"),
    ("4. GHÉP CÂU TIẾNG VIỆT TỰ NHIÊN RẢNH TAY", "Bộ Sentence Composer tự động liên kết từ ngữ bằng từ 'và', ngắt câu thông minh; Web Speech TTS đọc to cho nhân viên"),
    ("5. NHÂN VIÊN PHẢN HỒI HAI CHIỀU", "Nhân viên trả lời bằng giọng nói (STT) hoặc gõ phím; câu trả lời lập tức đồng bộ chữ lớn sang Màn hình khách")
]
create_native_shape_block_diagram(doc, "Sơ đồ 5.2", "Sơ đồ khối luồng xử lý nhận dạng cử chỉ video và điều phối hội thoại hai chiều", blocks_52)

doc.save("/tmp/test_native_diagram.docx")
print("Saved /tmp/test_native_diagram.docx successfully!")
