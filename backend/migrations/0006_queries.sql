-- 0006_queries: database-level guards for the query / dispute workflow (S8).
-- Never edit this file after it has been applied. Add 0007_... instead.
--
-- Story of one query:  RAISE (faculty) -> REPLY ... -> ESCALATE (HOD, optional) -> RESOLVE.
-- If the HOD upheld the flag, the faculty member may APPEAL once to the Dean.
-- Every step is a row in query_steps, which can never be changed or deleted.

-- 1) More facts per step: who acted (role), at which level, whether the Dean stepped in at the
--    HOD level (override), and for RESOLVE what the decision was.
ALTER TABLE query_steps ADD COLUMN level      text;
ALTER TABLE query_steps ADD COLUMN actor_role text;
ALTER TABLE query_steps ADD COLUMN override   boolean NOT NULL DEFAULT false;
ALTER TABLE query_steps ADD COLUMN outcome    text;
-- Steps are shown in the order they happened. created_at can tie (same transaction, same clock), seq never does.
ALTER TABLE query_steps ADD COLUMN seq        bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX query_steps_seq_idx ON query_steps (seq);

UPDATE query_steps SET level = 'HOD' WHERE level IS NULL;
UPDATE query_steps s SET actor_role = u.role FROM users u WHERE u.id = s.actor_id AND s.actor_role IS NULL;

ALTER TABLE query_steps ALTER COLUMN level SET NOT NULL;
ALTER TABLE query_steps ALTER COLUMN actor_role SET NOT NULL;
ALTER TABLE query_steps ADD CONSTRAINT query_steps_level_check CHECK (level IN ('HOD', 'DEAN'));
ALTER TABLE query_steps ADD CONSTRAINT query_steps_actor_role_check CHECK (actor_role IN ('FACULTY', 'HOD', 'DEAN'));
ALTER TABLE query_steps ADD CONSTRAINT query_steps_outcome_check CHECK (outcome IN ('UPHELD', 'OVERTURNED'));
-- Only a RESOLVE step carries an outcome, and every RESOLVE step carries one.
ALTER TABLE query_steps ADD CONSTRAINT query_steps_outcome_only_on_resolve
    CHECK ((action = 'RESOLVE') = (outcome IS NOT NULL));
-- An override only makes sense when the Dean acts.
ALTER TABLE query_steps ADD CONSTRAINT query_steps_override_is_dean CHECK (NOT override OR actor_role = 'DEAN');

-- APPEAL is new: the faculty member takes an HOD decision to the Dean.
ALTER TABLE query_steps DROP CONSTRAINT query_steps_action_check;
ALTER TABLE query_steps ADD CONSTRAINT query_steps_action_check
    CHECK (action IN ('RAISE', 'REPLY', 'ESCALATE', 'APPEAL', 'RESOLVE'));

-- 2) A step is history: it can never be changed or deleted.
CREATE TRIGGER query_steps_append_only
    BEFORE UPDATE OR DELETE ON query_steps
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

-- 3) More facts per query.
ALTER TABLE queries ADD COLUMN resolved_by      uuid REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE queries ADD COLUMN resolved_level   text CHECK (resolved_level IN ('HOD', 'DEAN'));
ALTER TABLE queries ADD COLUMN exception_id     uuid REFERENCES exceptions (id) ON DELETE RESTRICT;
ALTER TABLE queries ADD COLUMN appealed         boolean NOT NULL DEFAULT false;
ALTER TABLE queries ADD COLUMN last_activity_at timestamptz NOT NULL DEFAULT now();

-- A decided query always says who decided and at which level.
ALTER TABLE queries ADD CONSTRAINT queries_resolved_has_resolver
    CHECK (status = 'OPEN' OR (resolved_by IS NOT NULL AND resolved_level IS NOT NULL));
-- An open query has no decision.
ALTER TABLE queries ADD CONSTRAINT queries_open_has_no_decision
    CHECK (status <> 'OPEN' OR (resolved_by IS NULL AND resolved_level IS NULL AND resolved_at IS NULL));

-- 4) One query per flag for the life of the flag. A decided flag is not argued twice
--    (a HOD decision can be appealed once, inside the same query).
CREATE UNIQUE INDEX queries_one_per_flag ON queries (flag_id);
CREATE INDEX queries_raised_by_idx ON queries (raised_by);

-- 5) Only legal moves are allowed on a query row.
--      OPEN (HOD)  -> OPEN (DEAN)                         escalate
--      OPEN        -> RESOLVED_UPHELD / RESOLVED_OVERTURNED
--      RESOLVED_UPHELD by the HOD, not yet appealed -> OPEN (DEAN), appealed = true   (the one appeal)
--    Everything else is refused: a Dean decision is final, an overturned flag stays overturned,
--    a query never moves back from DEAN to HOD, and who raised which flag never changes.
CREATE FUNCTION queries_legal_move() RETURNS trigger AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.flag_id IS DISTINCT FROM OLD.flag_id
       OR NEW.raised_by IS DISTINCT FROM OLD.raised_by OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'a query keeps its flag, its author and its creation time'
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF OLD.status = 'OPEN' THEN
        IF NEW.status = 'OPEN' THEN
            -- allowed on an open query: escalate HOD -> DEAN, or just a new activity time
            IF NEW.current_level IS DISTINCT FROM OLD.current_level
               AND NOT (OLD.current_level = 'HOD' AND NEW.current_level = 'DEAN') THEN
                RAISE EXCEPTION 'a query can only move from the HOD to the Dean, never back'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.appealed IS DISTINCT FROM OLD.appealed AND NOT (OLD.appealed = false AND NEW.appealed = true) THEN
                RAISE EXCEPTION 'an appeal cannot be taken back' USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END IF;
        -- decided now
        IF NEW.current_level IS DISTINCT FROM OLD.current_level OR NEW.appealed IS DISTINCT FROM OLD.appealed THEN
            RAISE EXCEPTION 'a decision does not change the level or the appeal'
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;

    -- OLD is already decided: the only way forward is the single appeal after a HOD "upheld".
    IF OLD.status = 'RESOLVED_UPHELD' AND OLD.resolved_level = 'HOD' AND OLD.appealed = false
       AND NEW.status = 'OPEN' AND NEW.current_level = 'DEAN' AND NEW.appealed = true THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'this query has been decided and cannot be changed'
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER queries_legal_move
    BEFORE UPDATE ON queries
    FOR EACH ROW EXECUTE FUNCTION queries_legal_move();

-- 6) Queries are history too: never deleted.
CREATE FUNCTION queries_never_deleted() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'queries are history and cannot be deleted' USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER queries_never_deleted
    BEFORE DELETE ON queries
    FOR EACH ROW EXECUTE FUNCTION queries_never_deleted();
