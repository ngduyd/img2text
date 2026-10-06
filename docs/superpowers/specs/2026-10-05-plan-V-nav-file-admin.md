# Plan V — Nav user menu + file view/download + admin sub-rail (spec)

## Decisions (user feedback 2026-10-05)
- V1: AuthZone — avatar thành BUTTON mở dropdown menu (email + role ở header menu; mục "Hồ sơ" + "Đăng xuất"). OcrBadge giữ trong nav (signal độc lập). Testids: nav-avatar (nút), btn-profile, btn-logout GIỮ NGUYÊN (bên trong menu); thêm nav-user-menu. Outside-click close pattern như AppNav.
- V2: Xem/tải file gốc KHÔNG qua presign (fix "kh lấy ảnh ra được" — presigned localhost:4566 không tới được khi VSCode-forward). Server: GET /api/jobs/{id}/file/download — owner-or-admin (_job_or_403), storage.get uploads key, KeyError→404 "Không tìm thấy file.", Content-Type map (jpg/png/webp/pdf), Content-Disposition attachment; filename. Web: client.downloadJobFile(id)→blob; OriginalFilePanel: inline viewer (image <img objectURL>, pdf iframe objectURL) + nút Tải xuống (icon Download) via blob anchor — không còn phụ thuộc presign để xem.
- V3: Admin tabs → sub-rail trái (icon + label, active accent) desktop ≥md; mobile = segmented horizontal scroll. Tokens DESIGN.md; testids admin-tab-* giữ nguyên (AdminTabId unchanged).

## Non-goals
Stats; routing cho admin tabs (in-page state giữ); Landing sửa đổi.

## Lanes (3 worktrees parallel, disjoint)
- V1 lane nav-user-menu: web/src/App.tsx (AuthZone) + App.test.tsx.
- V2 lane file-download: server/app/routers/jobs.py (endpoint) + server/tests/test_file_download.py + web/src/api/client.ts + web/src/components/panels/OriginalFilePanel.tsx + test + JobDetail.tsx (CHỈ nếu mount cần).
- V3 lane admin-rail: web/src/pages/Admin.tsx + admin/AdminOverview.tsx (tabs data/icons) + Admin.test.tsx.
Merge order: V2 → V1 → V3. Gate sau merge: full web suite + server subset + tsc + build; e2e Section H: H1 avatar menu mở/đóng + logout trong menu; H2 job detail xem ảnh/PDF inline + tải xuống qua forward không cần port 4566; H3 admin rail desktop/mobile + active state.
