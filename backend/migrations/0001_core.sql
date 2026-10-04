-- 0001_core: core tables for the Faculty Compliance & Trust Engine (S2).
-- Rules are enforced here in the database, not only in Python.
-- Never edit this file after it has been applied. Add 0002_... instead.

-- ---------------------------------------------------------------
-- Helper: tables that must only ever be appended to
-- ---------------------------------------------------------------
CREATE FUNCTION forbid_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% on table % is not allowed: this table is append-only',
        TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------
-- People and organisation
-- ---------------------------------------------------------------
CREATE TABLE departments (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code        text NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    name        text NOT NULL UNIQUE CHECK (btrim(name) <> ''),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email          text NOT NULL UNIQUE CHECK (email = lower(email) AND email LIKE '%_@_%'),
    password_hash  text NOT NULL,
    full_name      text NOT NULL CHECK (btrim(full_name) <> ''),
    role           text NOT NULL CHECK (role IN ('FACULTY', 'HOD', 'DEAN')),
    department_id  uuid REFERENCES departments (id) ON DELETE RESTRICT,
    employee_code  text UNIQUE,
    is_active      boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    -- DEAN sees all departments (no department). FACULTY and HOD belong to exactly one.
    CONSTRAINT users_role_department CHECK (
        (role = 'DEAN' AND department_id IS NULL)
        OR (role IN ('FACULTY', 'HOD') AND department_id IS NOT NULL)
    )
);
CREATE INDEX users_department_idx ON users (department_id);
-- At most one active HOD per department.
CREATE UNIQUE INDEX users_one_active_hod_per_department
    ON users (department_id) WHERE role = 'HOD' AND is_active;

CREATE TABLE semesters (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    academic_year  text NOT NULL CHECK (academic_year ~ '^[0-9]{4}-[0-9]{2}$'),
    term           text NOT NULL CHECK (term IN ('ODD', 'EVEN')),
    start_date     date NOT NULL,
    end_date       date NOT NULL,
    is_current     boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (academic_year, term),
    CHECK (end_date > start_date)
);
-- Only one semester can be "current". Older ones are history only.
CREATE UNIQUE INDEX semesters_one_current ON semesters ((true)) WHERE is_current;

CREATE TABLE subjects (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code           text NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    name           text NOT NULL CHECK (btrim(name) <> ''),
    department_id  uuid NOT NULL REFERENCES departments (id) ON DELETE RESTRICT,
    subject_type   text NOT NULL CHECK (subject_type IN ('THEORY', 'LAB', 'THEORY_LAB')),
    is_active      boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX subjects_department_idx ON subjects (department_id);

-- One faculty teaching one subject in one semester = one course file.
-- department_id is copied on purpose: it must not change if the faculty moves later.
CREATE TABLE course_files (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id     uuid NOT NULL REFERENCES subjects (id) ON DELETE RESTRICT,
    semester_id    uuid NOT NULL REFERENCES semesters (id) ON DELETE RESTRICT,
    faculty_id     uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    department_id  uuid NOT NULL REFERENCES departments (id) ON DELETE RESTRICT,
    division       text CHECK (division IS NULL OR btrim(division) <> ''),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX course_files_unique
    ON course_files (subject_id, semester_id, faculty_id, COALESCE(division, ''));
CREATE INDEX course_files_faculty_semester_idx ON course_files (faculty_id, semester_id);
CREATE INDEX course_files_department_semester_idx ON course_files (department_id, semester_id);

-- ---------------------------------------------------------------
-- Checklist (the 19 mandatory items) and deadlines per semester
-- ---------------------------------------------------------------
CREATE TABLE checklist_templates (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code                text NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    title               text NOT NULL CHECK (btrim(title) <> ''),
    description         text NOT NULL DEFAULT '',
    applies_to          text NOT NULL DEFAULT 'BOTH' CHECK (applies_to IN ('THEORY', 'LAB', 'BOTH')),
    allowed_extensions  text[] NOT NULL DEFAULT '{}',
    max_size_mb         integer NOT NULL DEFAULT 10 CHECK (max_size_mb > 0),
    sort_order          integer NOT NULL DEFAULT 0,
    is_active           boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE checklist_deadlines (
    semester_id  uuid NOT NULL REFERENCES semesters (id) ON DELETE RESTRICT,
    template_id  uuid NOT NULL REFERENCES checklist_templates (id) ON DELETE RESTRICT,
    due_at       timestamptz NOT NULL,
    PRIMARY KEY (semester_id, template_id)
);

-- ---------------------------------------------------------------
-- Submissions and their versions
-- ---------------------------------------------------------------
-- One row per (course file, checklist item), created up front so "missing" is a real row.
-- No status column: current_version_id IS NULL means nothing uploaded yet.
CREATE TABLE submissions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_file_id      uuid NOT NULL REFERENCES course_files (id) ON DELETE RESTRICT,
    template_id         uuid NOT NULL REFERENCES checklist_templates (id) ON DELETE RESTRICT,
    current_version_id  uuid,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (course_file_id, template_id),
    UNIQUE (id, course_file_id)
);
CREATE INDEX submissions_template_idx ON submissions (template_id);

-- Every upload is kept forever. This table is append-only (see trigger below).
CREATE TABLE submission_versions (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id      uuid NOT NULL REFERENCES submissions (id) ON DELETE RESTRICT,
    version_no         integer NOT NULL CHECK (version_no >= 1),
    storage_key        text NOT NULL CHECK (btrim(storage_key) <> ''),
    original_filename  text NOT NULL CHECK (btrim(original_filename) <> ''),
    content_type       text,
    size_bytes         bigint NOT NULL CHECK (size_bytes > 0),
    sha256             char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    uploaded_by        uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    uploaded_at        timestamptz NOT NULL DEFAULT now(),
    validation_status  text NOT NULL DEFAULT 'OK' CHECK (validation_status IN ('OK', 'FORMAT_FAILED')),
    validation_detail  jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (submission_id, version_no),
    UNIQUE (id, submission_id)
);
CREATE INDEX submission_versions_sha256_idx ON submission_versions (sha256);
CREATE INDEX submission_versions_uploaded_at_idx ON submission_versions (uploaded_at);

-- The "current version" must be a version of the SAME submission.
ALTER TABLE submissions
    ADD CONSTRAINT submissions_current_version_fk
    FOREIGN KEY (current_version_id, id)
    REFERENCES submission_versions (id, submission_id);

CREATE TRIGGER submission_versions_append_only
    BEFORE UPDATE OR DELETE ON submission_versions
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

-- ---------------------------------------------------------------
-- Flags, exceptions, queries
-- ---------------------------------------------------------------
CREATE TABLE flags (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_file_id         uuid NOT NULL REFERENCES course_files (id) ON DELETE RESTRICT,
    submission_id          uuid REFERENCES submissions (id) ON DELETE RESTRICT,
    kind                   text NOT NULL CHECK (kind IN
                             ('LATE', 'MISSING', 'INCOMPLETE', 'FORMAT', 'CONTENT', 'MISMATCH', 'ANOMALY')),
    status                 text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLEARED', 'WAIVED')),
    reason                 text NOT NULL CHECK (btrim(reason) <> ''),
    detail                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    raised_by_version_id   uuid REFERENCES submission_versions (id) ON DELETE RESTRICT,
    raised_at              timestamptz NOT NULL DEFAULT now(),
    cleared_by_version_id  uuid REFERENCES submission_versions (id) ON DELETE RESTRICT,
    cleared_at             timestamptz,
    -- Lateness never clears. It can only stay OPEN or be WAIVED by an exception.
    CONSTRAINT flags_late_never_clears CHECK (NOT (kind = 'LATE' AND status = 'CLEARED')),
    CONSTRAINT flags_cleared_has_time CHECK (status <> 'CLEARED' OR cleared_at IS NOT NULL),
    CONSTRAINT flags_versions_need_submission CHECK (
        submission_id IS NOT NULL
        OR (raised_by_version_id IS NULL AND cleared_by_version_id IS NULL)
    ),
    -- A flag's submission, and the versions it points to, must belong to the flag's own course file / submission.
    CONSTRAINT flags_submission_matches_course_file FOREIGN KEY (submission_id, course_file_id)
        REFERENCES submissions (id, course_file_id),
    CONSTRAINT flags_raised_version_matches_submission FOREIGN KEY (raised_by_version_id, submission_id)
        REFERENCES submission_versions (id, submission_id),
    CONSTRAINT flags_cleared_version_matches_submission FOREIGN KEY (cleared_by_version_id, submission_id)
        REFERENCES submission_versions (id, submission_id)
);
CREATE INDEX flags_course_file_status_idx ON flags (course_file_id, status);
CREATE INDEX flags_submission_idx ON flags (submission_id);
-- No duplicate open flag of the same kind on one submission (MISMATCH and ANOMALY can repeat).
CREATE UNIQUE INDEX flags_one_open_per_kind
    ON flags (submission_id, kind)
    WHERE status = 'OPEN' AND submission_id IS NOT NULL
      AND kind IN ('LATE', 'MISSING', 'INCOMPLETE', 'FORMAT', 'CONTENT');

CREATE TABLE exceptions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_file_id  uuid NOT NULL REFERENCES course_files (id) ON DELETE RESTRICT,
    submission_id   uuid REFERENCES submissions (id) ON DELETE RESTRICT,
    kind            text NOT NULL CHECK (kind IN ('EXTENSION', 'WAIVER')),
    new_due_at      timestamptz,
    flag_id         uuid REFERENCES flags (id) ON DELETE RESTRICT,
    reason          text NOT NULL CHECK (length(btrim(reason)) >= 10),
    granted_by      uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    granted_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT exceptions_shape CHECK (
        (kind = 'EXTENSION' AND new_due_at IS NOT NULL AND submission_id IS NOT NULL AND flag_id IS NULL)
        OR (kind = 'WAIVER' AND flag_id IS NOT NULL AND new_due_at IS NULL)
    ),
    CONSTRAINT exceptions_submission_matches_course_file FOREIGN KEY (submission_id, course_file_id)
        REFERENCES submissions (id, course_file_id)
);
CREATE INDEX exceptions_course_file_idx ON exceptions (course_file_id);
CREATE INDEX exceptions_flag_idx ON exceptions (flag_id);

CREATE TABLE queries (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    flag_id        uuid NOT NULL REFERENCES flags (id) ON DELETE RESTRICT,
    raised_by      uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    current_level  text NOT NULL DEFAULT 'HOD' CHECK (current_level IN ('HOD', 'DEAN')),
    status         text NOT NULL DEFAULT 'OPEN'
                     CHECK (status IN ('OPEN', 'RESOLVED_UPHELD', 'RESOLVED_OVERTURNED')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    resolved_at    timestamptz,
    CONSTRAINT queries_resolved_has_time CHECK (status = 'OPEN' OR resolved_at IS NOT NULL)
);
CREATE INDEX queries_status_level_idx ON queries (status, current_level);
-- One open query per flag at a time.
CREATE UNIQUE INDEX queries_one_open_per_flag ON queries (flag_id) WHERE status = 'OPEN';

CREATE TABLE query_steps (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    query_id    uuid NOT NULL REFERENCES queries (id) ON DELETE RESTRICT,
    actor_id    uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    action      text NOT NULL CHECK (action IN ('RAISE', 'REPLY', 'ESCALATE', 'RESOLVE')),
    message     text NOT NULL CHECK (btrim(message) <> ''),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX query_steps_query_idx ON query_steps (query_id, created_at);

-- ---------------------------------------------------------------
-- Score weights (append-only; the newest row is the current one)
-- ---------------------------------------------------------------
CREATE TABLE score_weights (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    completeness  integer NOT NULL CHECK (completeness BETWEEN 0 AND 100),
    timeliness    integer NOT NULL CHECK (timeliness BETWEEN 0 AND 100),
    format        integer NOT NULL CHECK (format BETWEEN 0 AND 100),
    content       integer NOT NULL CHECK (content BETWEEN 0 AND 100),
    set_by        uuid REFERENCES users (id) ON DELETE RESTRICT,
    reason        text NOT NULL CHECK (btrim(reason) <> ''),
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT score_weights_sum_100 CHECK (completeness + timeliness + format + content = 100)
);
CREATE TRIGGER score_weights_append_only
    BEFORE UPDATE OR DELETE ON score_weights
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

INSERT INTO score_weights (completeness, timeliness, format, content, reason)
VALUES (35, 35, 20, 10, 'Initial weights from the PPSU problem statement');

-- ---------------------------------------------------------------
-- Audit log (append-only; hash columns are filled in step S11)
-- ---------------------------------------------------------------
CREATE TABLE audit_log (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at           timestamptz NOT NULL DEFAULT now(),
    actor_id     uuid REFERENCES users (id) ON DELETE RESTRICT,
    actor_role   text,
    action       text NOT NULL CHECK (btrim(action) <> ''),
    entity_type  text NOT NULL CHECK (btrim(entity_type) <> ''),
    entity_id    text,
    payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
    prev_hash    char(64),
    entry_hash   char(64)
);
CREATE INDEX audit_log_entity_idx ON audit_log (entity_type, entity_id);
CREATE INDEX audit_log_actor_idx ON audit_log (actor_id, at);
CREATE TRIGGER audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
