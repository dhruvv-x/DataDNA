-- 0003_upload_trace: who uploaded a version, and in which role (S4).
-- A Dean may upload for a faculty member, but then a reason is compulsory and the role is kept forever.
-- Never edit this file after it has been applied. Add 0004_... instead.

ALTER TABLE submission_versions
    ADD COLUMN uploaded_by_role text NOT NULL DEFAULT 'FACULTY'
        CHECK (uploaded_by_role IN ('FACULTY', 'DEAN')),
    ADD COLUMN on_behalf_reason text;

ALTER TABLE submission_versions ALTER COLUMN uploaded_by_role DROP DEFAULT;

ALTER TABLE submission_versions
    ADD CONSTRAINT submission_versions_on_behalf_rule CHECK (
        (uploaded_by_role = 'FACULTY' AND on_behalf_reason IS NULL)
        OR (uploaded_by_role = 'DEAN' AND on_behalf_reason IS NOT NULL
            AND length(btrim(on_behalf_reason)) >= 10)
    );
