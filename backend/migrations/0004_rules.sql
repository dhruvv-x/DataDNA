-- 0004_rules: database-level guards for the rule engine (S5).
-- Never edit this file after it has been applied. Add 0005_... instead.

-- 1) A submission can have at most ONE lateness flag in its whole life (open or waived).
--    Lateness is a fact about the first delivery. It is judged once, at upload time.
CREATE UNIQUE INDEX flags_one_late_per_submission
    ON flags (submission_id)
    WHERE kind = 'LATE' AND submission_id IS NOT NULL;

-- 2) A flag can only become WAIVED when a WAIVER exception for it exists.
--    (A waiver always carries a reason of 10+ characters and the person who granted it.)
CREATE FUNCTION flags_waived_needs_waiver() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'WAIVED' AND OLD.status IS DISTINCT FROM 'WAIVED' THEN
        IF NOT EXISTS (SELECT 1 FROM exceptions WHERE flag_id = NEW.id AND kind = 'WAIVER') THEN
            RAISE EXCEPTION 'a flag can only be WAIVED when a waiver exception exists for it'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER flags_waived_needs_waiver
    BEFORE UPDATE OF status ON flags
    FOR EACH ROW EXECUTE FUNCTION flags_waived_needs_waiver();

-- 3) A waiver is only meaningful for an OPEN flag when it is created, and an extension must
--    point at a submission whose course file it belongs to (already enforced by the FK).
--    Exceptions are history: they can never be changed or deleted.
CREATE FUNCTION exceptions_are_history() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'exceptions are history and cannot be changed or deleted'
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER exceptions_append_only
    BEFORE UPDATE OR DELETE ON exceptions
    FOR EACH ROW EXECUTE FUNCTION exceptions_are_history();
