-- OAuth (Google): liên kết tài khoản với provider.
-- NULL = tài khoản mật khẩu thuần (mọi row cũ). Một email có thể có cả 2.
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_sub TEXT;
-- tra cứu lúc callback: (provider, sub) là duy nhất
CREATE UNIQUE INDEX IF NOT EXISTS users_oauth_sub_key
  ON users (oauth_provider, oauth_sub)
  WHERE oauth_sub IS NOT NULL;
