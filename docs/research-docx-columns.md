# Research: DOCX giữ cấu trúc nhiều cột (từ bbox)

Phạm vi: renderer Python + python-docx, nguồn là OCR regions có `bbox=[x1,y1,x2,y2]` trên trang.
Quyết định đã chốt: **không `w:framePr`, không textbox/shape** — mọi block nằm trong dòng chảy paragraph.

## 1. Ba cách biểu diễn cột

| cách | cơ chế | số cột đổi giữa trang | cột dài tự xuống dòng | PDF (Word/LibreOffice) | user sửa tay | reading order |
|---|---|---|---|---|---|---|
| `w:cols` (section) | `sectPr/w:cols w:num` + `w:col w:w/w:space`; đổi số cột = **section break liên tục** | được (`add_section(WD_SECTION_START.CONTINUOUS)`) | được (Word tự chảy sang cột sau) | ổn định, cả 2 đều hỗ trợ | tốt (đúng khái niệm Word) | theo cột→hàng, đúng nếu nội dung đặt đúng thứ tự |
| bảng borderless | mỗi cột = 1 `tc`, `tblBorders=nil` | phải tạo bảng riêng cho từng band → nhiều bảng | được nhưng **không tự chảy** — dài quá thì tràn/xuống hàng | ổn định | tạm (người dùng thấy "bảng ma") | theo hàng→cột = **sai** nếu đọc dọc từng cột |
| indent + tab stop | `w:ind` + `w:tabs` | tầm thường (mỗi paragraph tự khai) | không (mỗi dòng là 1 paragraph) | ổn định | tốt | đúng thứ tự XML |

Kết luận: **cột trang → `w:cols` + continuous section**; **2 khối song song trong cùng band (nhãn–giá trị, chữ ký–ngày) → `w:tabs`**; **bảng thật → table**. Bảng borderless chỉ dùng khi band 2 cột ngắn và không cần chảy trang.

## 2. Số cột không hằng định
Dùng **section break liên tục**: python-docx `doc.add_section(WD_SECTION_START.CONTINUOUS)` rồi set `w:cols` cho section mới.
Quy tắc: gom trang liên tiếp có cùng "chữ ký cột" (số cột + tỉ lệ width từ `_cluster_columns`) thành 1 section; band trải hết chiều ngang (không cluster) chèn section 1 cột bao quanh nó.
Nguồn: python-docx sections doc (`add_section`, `start_type`) — https://python-docx.readthedocs.io/en/latest/user/sections.html

Cạm bẫy: `w:cols` áp cho cả section, nên mọi trang trong section dùng chung. Trang lẻ khác layout → tách section (chấp nhận thêm sectPr).

## 3. `w:tabs` vs `w:ind`
- `w:ind` (`left_indent`, `first_line_indent`, `right_indent`) = **lề của cả paragraph**. Dùng khi khối bắt đầu tại x khác lề trái (thụt đầu dòng, hanging indent của list, block lệch).
- `w:tabs` = **mốc dừng trong dòng**. Dùng khi 2+ mẩu chữ trên cùng dòng ở x khác nhau (nhãn + giá trị, "Họ tên: ....", cột số-liệu).
- Map bbox → twips: `twips = round(px * 1440 / dpi)`; đo từ **inside edge của paragraph** (đã tính cả `left_indent`), không phải từ mép trang. Với `x` lấy từ bbox đã trừ left margin + left indent hiện tại.
- `TabStops.add_tab_stop(position, alignment, leader)`; `WD_TAB_LEADER.DOTS` cho form field; `WD_TAB_ALIGNMENT.RIGHT` cho số liệu canh phải.
  (API xác nhận trong source `python-docx` `docx/text/paragraph.py`.)
- Cạm bẫy: tab mặc định 0.5" (720 twips) chèn giữa nếu position vượt width; tab position tính từ paragraph edge nên **cộng dồn với `left_indent`**; tab âm chỉ dùng cho hanging indent.

## 4. Khoảng cách dọc
- `space_before`/`space_after` = pt; `line_spacing` = multiple hoặc `Pt`.
- Map: `gap_px` giữa 2 band → `space_after = max(0, gap_px - line_height) * 72 / dpi`, cap ~24pt; trong cùng band dùng `line_spacing = round(line_height_pt / font_pt, 2)`.
- Đặt `space_after` ở paragraph **trước**, `space_before=0` toàn cục → tránh cộng dồn (Word cộng cả hai).
- Font size: từ band height (`round(h_px * 72 / dpi)`, clamp 8–32) — đây là suy luận, cần hiệu chỉnh bằng ảnh mẫu thật.

## 5. Verify reading order (regression)
- `python-docx`: `[p.text for p in doc.paragraphs]` — thứ tự XML, chính là thứ tự đọc.
- `pandoc -f docx -t markdown` — kiểm tra cấu trúc + thứ tự sau khi qua parser khác.
- LibreOffice headless: `soffice --headless --convert-to pdf` rồi `pdftotext -layout` để so vị trí.
- Regression: lưu snapshot text đã chuẩn hoá (bỏ whitespace) cho 3–5 ảnh mẫu; fail nếu thứ tự đổi.

## Khuyến nghị cho project này
1. Cột: `w:cols` + continuous section theo từng nhóm trang (fallback: nếu section count > 8 → linearize 1 cột cho gọn).
2. Canh lề trong dòng: `w:tabs` (kèm `WD_TAB_LEADER.DOTS` cho form field), lệch khối: `w:ind`.
3. Bảng thật: table (đã có trong `html_to_docx`).
4. Spacing: `space_after` + `line_spacing` theo bbox gap.
5. Verify: snapshot `p.text` + `pandoc docx→md` trong test.

## Nguồn
- python-docx sections: https://python-docx.readthedocs.io/en/latest/user/sections.html
- python-docx `TabStops`/`TabStop` API: source `docx/text/paragraph.py` (đọc trực tiếp trong venv)
- OOXML `w:cols`/`w:col`/`w:sectPr`: ECMA-376 Part 1 §17.6.4/17.6.17 (chưa fetch được trang MS — nêu theo spec, **suy luận** về chi tiết thuộc tính)
- LibreOffice/Word khác biệt render cột: **suy luận** từ hành vi chung, chưa có nguồn đo được.
