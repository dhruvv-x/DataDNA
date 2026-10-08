-- S6: trust score history.
-- score_snapshots: every time a course file's score changes, one row is added. Never edited, never deleted.
-- semester_weights: which weights a semester is scored with (so a later weight change does not move old goalposts).

-- A course file's semester must match its snapshot's semester.
ALTER TABLE course_files ADD CONSTRAINT course_files_id_semester_uniq UNIQUE (id, semester_id);

-- Completeness + Timeliness + Format together must carry at least half the score, so that the score still
-- means something while the Content part is switched off (its weight is then shared among these three).
ALTER TABLE score_weights ADD CONSTRAINT score_weights_main_parts_min_50
    CHECK (completeness + timeliness + format >= 50);

CREATE TABLE semester_weights (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    semester_id uuid   NOT NULL REFERENCES semesters (id) ON DELETE RESTRICT,
    weights_id  bigint NOT NULL REFERENCES score_weights (id) ON DELETE RESTRICT,
    reason      text   NOT NULL CHECK (btrim(reason) <> ''),
    set_by      uuid   REFERENCES users (id) ON DELETE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX semester_weights_sem_idx ON semester_weights (semester_id, id DESC);
CREATE TRIGGER semester_weights_append_only
    BEFORE UPDATE OR DELETE ON semester_weights
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

-- Every semester that exists today is scored with the weights that exist today.
INSERT INTO semester_weights (semester_id, weights_id, reason)
SELECT s.id, (SELECT max(id) FROM score_weights), 'Weights in force when scoring was introduced (S6)'
FROM semesters s;

CREATE TABLE score_snapshots (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    course_file_id  uuid   NOT NULL,
    semester_id     uuid   NOT NULL,
    weights_id      bigint NOT NULL REFERENCES score_weights (id) ON DELETE RESTRICT,
    content_active  boolean NOT NULL,
    status          text   NOT NULL CHECK (status IN ('SCORED', 'NO_DEADLINES', 'NO_ITEMS')),
    total           numeric(5,2) CHECK (total BETWEEN 0 AND 100),
    completeness_pts numeric(5,2) CHECK (completeness_pts BETWEEN 0 AND 100),
    timeliness_pts   numeric(5,2) CHECK (timeliness_pts BETWEEN 0 AND 100),
    format_pts       numeric(5,2) CHECK (format_pts BETWEEN 0 AND 100),
    content_pts      numeric(5,2) CHECK (content_pts BETWEEN 0 AND 100),
    eff_completeness numeric(5,2) NOT NULL CHECK (eff_completeness BETWEEN 0 AND 100),
    eff_timeliness   numeric(5,2) NOT NULL CHECK (eff_timeliness BETWEEN 0 AND 100),
    eff_format       numeric(5,2) NOT NULL CHECK (eff_format BETWEEN 0 AND 100),
    eff_content      numeric(5,2) NOT NULL CHECK (eff_content BETWEEN 0 AND 100),
    items_total     integer NOT NULL CHECK (items_total >= 0),
    items_pending   integer NOT NULL CHECK (items_pending >= 0 AND items_pending <= items_total),
    breakdown       jsonb  NOT NULL,
    fingerprint     char(64) NOT NULL,
    trigger         text   NOT NULL CHECK (btrim(trigger) <> ''),
    is_final        boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT score_snapshots_course_file_fk FOREIGN KEY (course_file_id, semester_id)
        REFERENCES course_files (id, semester_id) ON DELETE RESTRICT,
    -- A number exists exactly when the status is SCORED, and the parts always add up to the total.
    CONSTRAINT score_snapshots_scored_has_numbers CHECK (
        (status = 'SCORED') = (total IS NOT NULL
            AND completeness_pts IS NOT NULL AND timeliness_pts IS NOT NULL
            AND format_pts IS NOT NULL AND content_pts IS NOT NULL)
    ),
    CONSTRAINT score_snapshots_parts_add_up CHECK (
        status <> 'SCORED'
        OR total = completeness_pts + timeliness_pts + format_pts + content_pts
    ),
    CONSTRAINT score_snapshots_eff_sum_100 CHECK (
        eff_completeness + eff_timeliness + eff_format + eff_content = 100
    )
);
CREATE INDEX score_snapshots_cf_idx ON score_snapshots (course_file_id, id DESC);
CREATE INDEX score_snapshots_sem_idx ON score_snapshots (semester_id);
CREATE TRIGGER score_snapshots_append_only
    BEFORE UPDATE OR DELETE ON score_snapshots
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
