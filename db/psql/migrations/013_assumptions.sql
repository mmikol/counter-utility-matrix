-- 013: STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS
--
-- A third kind of strategy file: an ASSUMPTION is prose by definition -
-- what the solver takes as given and the session holds a comp to - and
-- carries nothing to score. What were prose constraints (`prose: true`)
-- are assumptions; the flag is gone.

ALTER TABLE strategies DROP CONSTRAINT strategies_kind_check;
ALTER TABLE strategies ADD CONSTRAINT strategies_kind_check
    CHECK (kind IN ('constraint', 'heuristic', 'assumption'));
