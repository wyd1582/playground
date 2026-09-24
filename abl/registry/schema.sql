-- ABL registry — OPS.md A.2, verbatim field lists.
-- Every table is append-only: corrections are new rows with a `supersedes` pointer.
-- Every row carries ownership: owner ∈ {customer, newco, public}, sharing_tier ∈ {private, aggregated, public}.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS campaigns (
  campaign_id        TEXT PRIMARY KEY,
  customer_id        TEXT NOT NULL,
  species            TEXT NOT NULL,
  trait_set          TEXT NOT NULL,          -- JSON list
  horizon            TEXT NOT NULL,
  champion_id        TEXT NOT NULL,
  budget_full_evals  INTEGER NOT NULL,
  budget_tokens      INTEGER NOT NULL,
  started_at         TEXT NOT NULL,
  ended_at           TEXT,
  owner              TEXT NOT NULL,
  sharing_tier       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
  proposal_id        TEXT PRIMARY KEY,
  campaign_id        TEXT NOT NULL REFERENCES campaigns(campaign_id),
  agent_model        TEXT NOT NULL,
  mechanism_text     TEXT NOT NULL,
  mechanism_cluster  TEXT NOT NULL,
  direction          TEXT NOT NULL,
  falsifiers         TEXT NOT NULL,          -- JSON list
  expected_gain      TEXT NOT NULL,          -- JSON {delta_oos, dispersion_b}
  novelty_hash       TEXT NOT NULL,
  source_refs        TEXT NOT NULL,          -- JSON list
  tokens             INTEGER NOT NULL DEFAULT 0,
  created_at         TEXT NOT NULL,
  owner              TEXT NOT NULL DEFAULT 'newco',
  sharing_tier       TEXT NOT NULL DEFAULT 'private'
);

CREATE TABLE IF NOT EXISTS candidates (
  candidate_id       TEXT PRIMARY KEY,
  proposal_id        TEXT NOT NULL REFERENCES proposals(proposal_id),
  dsl_text           TEXT NOT NULL,
  dsl_hash           TEXT NOT NULL,
  code_hash          TEXT NOT NULL,
  data_decl_hash     TEXT NOT NULL,
  state              TEXT NOT NULL CHECK (state IN
                       ('registered','reviewed','implemented','validated','evaluated','promoted','rejected')),
  retry_count        INTEGER NOT NULL DEFAULT 0,
  supersedes         TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);

-- append-only state history; candidates.state is the projection of the latest row here
CREATE TABLE IF NOT EXISTS candidate_transitions (
  transition_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id       TEXT NOT NULL REFERENCES candidates(candidate_id),
  from_state         TEXT,
  to_state           TEXT NOT NULL,
  gate               TEXT NOT NULL,          -- which gate (or 'registry') authorised the transition
  reason             TEXT NOT NULL,
  at                 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS critic_reviews (
  review_id          TEXT PRIMARY KEY,
  candidate_id       TEXT NOT NULL REFERENCES candidates(candidate_id),
  verdict            TEXT NOT NULL CHECK (verdict IN ('PASS','RETURN','REJECT')),
  leak_type          TEXT NOT NULL,          -- JSON list ⊆ {temporal, relatedness, structure, thesis_code, dispersion, plan}
  evidence           TEXT NOT NULL,          -- JSON list of {file,line,field,note}
  tokens             INTEGER NOT NULL DEFAULT 0,
  created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gate_results (
  gate_result_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id       TEXT NOT NULL REFERENCES candidates(candidate_id),
  gate               TEXT NOT NULL CHECK (gate IN ('validity','accuracy','incremental','plan','robustness','research')),
  metric             TEXT NOT NULL,
  value              REAL,
  ci_low             REAL,
  ci_high            REAL,
  threshold          REAL,
  passed             INTEGER NOT NULL,
  cutoff_date        TEXT,
  seed               INTEGER,
  data_snapshot_id   TEXT,
  evaluated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
  evaluation_id      TEXT PRIMARY KEY,
  candidate_id       TEXT NOT NULL REFERENCES candidates(candidate_id),
  split_id           TEXT NOT NULL,
  rho                REAL,
  bias               REAL,
  dispersion         REAL,
  delta_oos          REAL,
  delta_oos_ci_low   REAL,
  n_train            INTEGER,
  n_test             INTEGER,
  compute_seconds    REAL NOT NULL DEFAULT 0,
  tokens             INTEGER NOT NULL DEFAULT 0,
  evaluated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_snapshots (
  snapshot_id        TEXT PRIMARY KEY,
  customer_id        TEXT NOT NULL,
  genotype_source    TEXT NOT NULL CHECK (genotype_source IN ('solid','liquid','seq','sim')),
  genotype_build     TEXT NOT NULL,
  pedigree_version   TEXT NOT NULL,
  phenotype_version  TEXT NOT NULL,
  n_animals          INTEGER NOT NULL,
  n_markers          INTEGER NOT NULL,
  cutoff_date        TEXT NOT NULL,
  owner              TEXT NOT NULL,
  sharing_tier       TEXT NOT NULL,
  deidentified       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS recommendations (
  rec_id             TEXT PRIMARY KEY,
  customer_id        TEXT NOT NULL,
  selection_date     TEXT NOT NULL,
  candidate_id       TEXT NOT NULL,
  snapshot_id        TEXT NOT NULL,
  animal_id          TEXT NOT NULL,
  score              REAL NOT NULL,
  rank               INTEGER NOT NULL,
  pct_rank           REAL NOT NULL,
  recommended_action TEXT NOT NULL,          -- keep | cull | mate_with:<id>
  issued_at          TEXT NOT NULL,
  owner              TEXT NOT NULL DEFAULT 'customer'
);

CREATE TABLE IF NOT EXISTS decisions (
  decision_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  rec_id             TEXT NOT NULL REFERENCES recommendations(rec_id),
  adopted            INTEGER NOT NULL,
  actual_action      TEXT NOT NULL,
  decided_by_role    TEXT NOT NULL,
  decided_at         TEXT NOT NULL,
  override_reason    TEXT,
  owner              TEXT NOT NULL DEFAULT 'customer'
);

CREATE TABLE IF NOT EXISTS outcomes (
  outcome_id         TEXT PRIMARY KEY,
  rec_id             TEXT NOT NULL REFERENCES recommendations(rec_id),
  animal_id          TEXT NOT NULL,
  outcome_type       TEXT NOT NULL,          -- progeny_phenotype | debv | survival | culled | litter | egg | fcr | ...
  value              REAL,
  observed_at        TEXT NOT NULL,
  generation         INTEGER,
  owner              TEXT NOT NULL DEFAULT 'customer'
);

CREATE TABLE IF NOT EXISTS agent_events (
  event_id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ts                 TEXT NOT NULL,
  campaign_id        TEXT,
  agent              TEXT NOT NULL,
  action             TEXT NOT NULL,
  candidate_id       TEXT,
  input_hash         TEXT NOT NULL,
  output_hash        TEXT NOT NULL,
  tokens             INTEGER NOT NULL DEFAULT 0,
  latency_ms         INTEGER NOT NULL DEFAULT 0,
  summary            TEXT NOT NULL DEFAULT '',
  policy_flags       TEXT NOT NULL DEFAULT '[]',   -- JSON list ⊆ {holdout_touch, budget_exceeded, threshold_edit, retry_limit, holdout_final_read}
  cost_usd           REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS costs (
  cost_id            INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id        TEXT NOT NULL,
  customer_id        TEXT NOT NULL,
  period             TEXT NOT NULL,
  tokens             INTEGER NOT NULL DEFAULT 0,
  compute_seconds    REAL NOT NULL DEFAULT 0,
  human_review_minutes REAL NOT NULL DEFAULT 0,
  cash_cost          REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS controls (
  control_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id        TEXT NOT NULL,
  arm                TEXT NOT NULL CHECK (arm IN ('champion','random_ops','one_shot_llm','human_batch','shuffled_labels','random_snp','abl_loop')),
  metric             TEXT NOT NULL,
  value              REAL,
  evaluated_at       TEXT NOT NULL
);

-- threshold provenance (CLAUDE.md rule 4): every campaign records the hash of gates/thresholds.yaml
CREATE TABLE IF NOT EXISTS threshold_versions (
  campaign_id        TEXT NOT NULL,
  thresholds_hash    TEXT NOT NULL,
  recorded_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_proposals_campaign ON proposals(campaign_id);
CREATE INDEX IF NOT EXISTS ix_candidates_proposal ON candidates(proposal_id);
CREATE INDEX IF NOT EXISTS ix_gate_results_cand ON gate_results(candidate_id);
CREATE INDEX IF NOT EXISTS ix_events_ts ON agent_events(ts);
