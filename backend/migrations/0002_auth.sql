-- 0002_auth: login lockout columns on users, and the refresh_tokens table (S3).
-- Never edit this file after it has been applied. Add 0003_... instead.

ALTER TABLE users
    ADD COLUMN failed_login_count    integer     NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    ADD COLUMN locked_until          timestamptz,
    ADD COLUMN last_login_at         timestamptz,
    ADD COLUMN password_changed_at   timestamptz NOT NULL DEFAULT now(),
    -- true for accounts created with a temporary password; they may only change it
    ADD COLUMN must_change_password  boolean     NOT NULL DEFAULT false;

-- Refresh tokens: only the SHA-256 of the token is stored, never the token itself.
-- used_at is set when a token is exchanged for a new one (rotation).
-- Seeing a used or revoked token again means it was copied, so the user is logged out everywhere.
CREATE TABLE refresh_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid        NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    token_hash  char(64)    NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    issued_at   timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    revoked_at  timestamptz,
    CHECK (expires_at > issued_at)
);
CREATE INDEX refresh_tokens_user_idx ON refresh_tokens (user_id);
