-- ABL analysis views — OPS.md A.3. Plain SQL so they run in SQLite and DuckDB alike.

DROP VIEW IF EXISTS v_funnel;
CREATE VIEW v_funnel AS
SELECT p.campaign_id,
       COUNT(DISTINCT p.proposal_id)                                                   AS proposals,
       COUNT(DISTINCT CASE WHEN cr.verdict = 'PASS' THEN c.candidate_id END)           AS passed_critic,
       COUNT(DISTINCT CASE WHEN t.to_state IN ('implemented','validated','evaluated','promoted') THEN c.candidate_id END) AS implemented,
       COUNT(DISTINCT CASE WHEN t.to_state IN ('validated','evaluated','promoted') THEN c.candidate_id END) AS validated,
       COUNT(DISTINCT CASE WHEN t.to_state IN ('evaluated','promoted') THEN c.candidate_id END) AS full_evaluated,
       COUNT(DISTINCT CASE WHEN t.to_state = 'promoted' THEN c.candidate_id END)       AS promoted,
       COUNT(DISTINCT CASE WHEN t.to_state = 'rejected' THEN c.candidate_id END)       AS rejected
FROM proposals p
LEFT JOIN candidates c ON c.proposal_id = p.proposal_id
LEFT JOIN critic_reviews cr ON cr.candidate_id = c.candidate_id
LEFT JOIN candidate_transitions t ON t.candidate_id = c.candidate_id
GROUP BY p.campaign_id;

DROP VIEW IF EXISTS v_cost_per_promotion;
CREATE VIEW v_cost_per_promotion AS
SELECT f.campaign_id,
       f.promoted,
       f.full_evaluated,
       COALESCE(SUM(k.tokens), 0)                    AS tokens,
       COALESCE(SUM(k.compute_seconds), 0)           AS compute_seconds,
       COALESCE(SUM(k.human_review_minutes), 0)      AS human_review_minutes,
       CASE WHEN f.promoted > 0 THEN COALESCE(SUM(k.tokens), 0) * 1.0 / f.promoted END          AS tokens_per_promotion,
       CASE WHEN f.promoted > 0 THEN COALESCE(SUM(k.compute_seconds), 0) / f.promoted END       AS compute_seconds_per_promotion,
       CASE WHEN f.promoted > 0 THEN f.full_evaluated * 1.0 / f.promoted END                    AS full_evals_per_promotion
FROM v_funnel f LEFT JOIN costs k ON k.campaign_id = f.campaign_id
GROUP BY f.campaign_id, f.promoted, f.full_evaluated;

DROP VIEW IF EXISTS v_adoption;
CREATE VIEW v_adoption AS
SELECT r.customer_id,
       r.candidate_id,
       CASE WHEN r.pct_rank < 0.1 THEN 'top10' WHEN r.pct_rank < 0.5 THEN 'mid' ELSE 'bottom' END AS rank_bucket,
       COUNT(*)                                   AS recommendations,
       SUM(COALESCE(d.adopted, 0))                AS adopted,
       AVG(COALESCE(d.adopted, 0))                AS adoption_rate
FROM recommendations r LEFT JOIN decisions d ON d.rec_id = r.rec_id
GROUP BY r.customer_id, r.candidate_id, rank_bucket;

DROP VIEW IF EXISTS v_realized;
CREATE VIEW v_realized AS
-- descriptive only: adoption is not randomised (OPS.md A.3)
SELECT r.customer_id, r.selection_date, o.outcome_type,
       COALESCE(d.adopted, 0) AS adopted,
       COUNT(*)               AS n,
       AVG(o.value)           AS mean_outcome
FROM recommendations r
JOIN outcomes o ON o.rec_id = r.rec_id
LEFT JOIN decisions d ON d.rec_id = r.rec_id
GROUP BY r.customer_id, r.selection_date, o.outcome_type, adopted;

DROP VIEW IF EXISTS v_drift;
CREATE VIEW v_drift AS
SELECT candidate_id, split_id, evaluated_at, rho, bias, dispersion, delta_oos
FROM evaluations ORDER BY candidate_id, evaluated_at;

DROP VIEW IF EXISTS v_diversity;
CREATE VIEW v_diversity AS
SELECT campaign_id, mechanism_cluster, COUNT(*) AS n,
       COUNT(*) * 1.0 / (SELECT COUNT(*) FROM proposals q WHERE q.campaign_id = p.campaign_id) AS share
FROM proposals p GROUP BY campaign_id, mechanism_cluster;

DROP VIEW IF EXISTS v_critic_quality;
CREATE VIEW v_critic_quality AS
SELECT p.campaign_id,
       CASE WHEN p.mechanism_cluster LIKE 'negative_control%' THEN 'negative_control' ELSE 'regular' END AS arm,
       SUM(CASE WHEN cr.verdict = 'REJECT' THEN 1 ELSE 0 END) AS rejected,
       SUM(CASE WHEN cr.verdict = 'RETURN' THEN 1 ELSE 0 END) AS returned,
       SUM(CASE WHEN cr.verdict = 'PASS'   THEN 1 ELSE 0 END) AS passed,
       COUNT(*) AS reviews
FROM critic_reviews cr
JOIN candidates c ON c.candidate_id = cr.candidate_id
JOIN proposals p ON p.proposal_id = c.proposal_id
GROUP BY p.campaign_id, arm;

DROP VIEW IF EXISTS v_marker_value;
CREATE VIEW v_marker_value AS
-- which operator families keep contributing on the incremental gate (feeds chip-content design)
SELECT p.campaign_id, p.mechanism_cluster,
       COUNT(*)                                    AS incremental_tests,
       SUM(g.passed)                               AS incremental_passes,
       AVG(g.value)                                AS mean_delta_oos,
       MAX(g.ci_low)                               AS best_ci_low
FROM gate_results g
JOIN candidates c ON c.candidate_id = g.candidate_id
JOIN proposals p ON p.proposal_id = c.proposal_id
WHERE g.gate = 'incremental' AND g.metric = 'delta_oos'
GROUP BY p.campaign_id, p.mechanism_cluster;

DROP VIEW IF EXISTS v_customer_scorecard;
CREATE VIEW v_customer_scorecard AS
SELECT ca.customer_id, ca.campaign_id, ca.species,
       (SELECT AVG(value) FROM controls x WHERE x.campaign_id = ca.campaign_id AND x.arm = 'champion' AND x.metric = 'gain_per_year') AS champion_gain_per_year,
       (SELECT MAX(value) FROM controls x WHERE x.campaign_id = ca.campaign_id AND x.arm = 'abl_loop' AND x.metric = 'gain_per_year')  AS loop_gain_per_year,
       (SELECT COALESCE(SUM(tokens),0) FROM costs k WHERE k.campaign_id = ca.campaign_id)                 AS tokens,
       (SELECT COALESCE(SUM(compute_seconds),0) FROM costs k WHERE k.campaign_id = ca.campaign_id)        AS compute_seconds,
       (SELECT COALESCE(SUM(cash_cost),0) FROM costs k WHERE k.campaign_id = ca.campaign_id)              AS cash_cost
FROM campaigns ca;
