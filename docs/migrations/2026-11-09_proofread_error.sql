-- Proofread: lưu lỗi LLM gần nhất để UI phân biệt "0 gợi ý vì văn bản sạch"
-- với "0 gợi ý vì LLM chết". NULL = lần chạy cuối OK (hoặc chưa chạy).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS proofread_error TEXT;
