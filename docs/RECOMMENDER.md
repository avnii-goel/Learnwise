# Phase 6: Adaptive Recommendation Engine Specification

## 1. Ground Rules

All Phase 6 implementation tasks must adhere strictly to these engineering constraints:
1. **Scope Boundaries:** Execute ONLY the current assigned chunk. Never add speculative or out-of-scope features.
2. **Database Isolation:** Never connect to or execute migrations or scripts against the shared Supabase database. If a task requires changes on the shared database, provide the exact commands for manual execution.
3. **Regression Safety:** Keep all existing tests passing. Execute test suites strictly against the local test database (`localhost:5433`).
4. **No Unprompted Commits:** Do not make Git commits unless explicitly instructed.
5. **Lean Delivery & Verification:** Conclude each chunk with a concise operational report detailing files changed, tests run with results, and manual operational actions.
6. **Knowledge Consistency:** Reference and reuse status thresholds and mastery semantics from `docs/KNOWLEDGE_MODEL.md` (e.g., `not_attempted`, `weak`, `developing`, `strong`) without duplicating or redefining them.

---

## 2. Recommendation Pipeline

When a learner requests recommendations (`POST /api/recommendations/me`), the engine executes the following multi-stage pipeline:

```
[Target Selection]
       │  Pick up to MAX_TARGET_TOPICS = 3 topics (weak/developing by need, or fill not_attempted)
       ▼
[Prerequisite Resolution]
       │  Recursively replace target topic if blocked by weak prerequisites
       ▼
[Candidate Collection]
       │  Gather learning_resources for each target topic (skip topics with no embedded resources)
       ▼
[Difficulty Filtering]
       │  Determine learner target difficulty rank (easy=0, medium=1, hard=2)
       │  Exclude resources with (rank - target_rank >= 2); relax if pool is empty
       ▼
[Multi-Component Scoring]
       │  Compute: need, semantic similarity, difficulty fit, collaborative score
       │  Dynamically re-weight and normalize score
       ▼
[Ranking & Output]
       │  Sort by score descending; select top RESOURCES_PER_TOPIC = 3 per topic
       ▼
[Audit Logging]
          Persist recommendation_impressions rows for each recommended item
```

Key Pipeline Constants:
- `MAX_TARGET_TOPICS = 3`: Maximum number of focus topics recommended in a single request.
- `RESOURCES_PER_TOPIC = 3`: Maximum number of ranked resources returned per focus topic.

---

## 3. Resource & Query Embeddings

### 3.1 Model & Dimensionality
- **Primary Model:** `sentence-transformers/all-MiniLM-L6-v2` executed via **`fastembed`** (lightweight ONNX runtime, zero PyTorch dependency), producing 384-dimensional dense vectors.
- **Fallback Model:** `BAAI/bge-small-en-v1.5` (also 384 dimensions).
- **Storage:** Stored in a `vector(384)` column on `learning_resources`. With ~100 curated resources, full vector indexes (e.g. HNSW/IVFFlat) are unnecessary; linear scans and in-memory cosine similarities are instantaneous.
- **Cache Directory:** Local model cache directory is pinned to `.cache/fastembed` inside the repository and excluded via `.gitignore`.

### 3.2 Offline Resource Embedding Script (`scripts/embed_resources.py`)
- **Embedded Text Template:**
  ```
  "{topic title}. {resource title}. {resource description}"
  ```
- **Embedding Fingerprint:**
  ```python
  embedding_hash = hashlib.sha256(f"{model_name}\n{text}".encode("utf-8")).hexdigest()
  ```
- The offline script processes only rows where `embedding_hash != current_hash` or `embedding IS NULL`, ensuring idempotency.

### 3.3 Online Query Text Construction
At request time, the query vector is generated dynamically per target topic to reflect the learner's immediate misconceptions:
- **Template:**
  ```
  "{topic title}. {up to 3 most recent wrong question texts in that topic}"
  ```
- If the learner has no recent incorrect responses for that topic (e.g., unattempted topics), fallback to:
  ```
  "{topic title}. {topic description}"
  ```
  *(Note on Deviation: The original draft suggested falling back to title only; enriching with topic description improves embedding cosine fidelity against resource descriptions).*

### 3.4 Test Isolation (`EMBEDDER_BACKEND=fake`)
In test environments, `EMBEDDER_BACKEND=fake` activates a deterministic, hashing bag-of-words embedder (384 dimensions, $L_2$-normalized). Pytest never downloads or executes real ONNX models.

---

## 4. Topic Prerequisites & Substitution

### 4.1 Relational Schema (`topic_prerequisites`)
```sql
CREATE TABLE topic_prerequisites (
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    prerequisite_topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    CONSTRAINT pk_topic_prerequisites PRIMARY KEY (topic_id, prerequisite_topic_id),
    CONSTRAINT chk_topic_prerequisites_no_self CHECK (topic_id <> prerequisite_topic_id)
);
```
- **Validation Rules:**
  - Prerequisites are strictly within the same course (`topic.course_id == prerequisite.course_id`).
  - Graph must be acyclic (DAG validated at seed/import time).
- **Resource Inheritance:** Resources inherit all prerequisites of their parent topic.

### 4.2 Substitution Traversal Rule
If a target topic $T$ has a prerequisite $P$ whose current competency status is **`weak`** ($p < 0.40$):
1. Replace $T$ with $P$.
2. Recursively inspect $P$'s prerequisites for any `weak` dependencies.
3. Repeat until a prerequisite with no `weak` dependencies is reached.
4. **Visited Guard:** Maintain a `visited: set[int]` to prevent infinite loops.
5. Prerequisites with status `not_attempted` or `developing` **do not block** the learner from the target topic.

---

## 5. Target Topic Selection

The recommender selects up to `MAX_TARGET_TOPICS = 3` distinct target topics:

1. **Weak & Developing Candidates:**
   - Filter learner topics with status `weak` or `developing`.
   - Apply prerequisite substitution on each.
   - De-duplicate resulting topics.
   - Compute `need`:
     $$\text{need} = 1.0 - \text{mastery\_probability}$$
   - Sort descending by `need`.
2. **Backfill with Unattempted Topics:**
   - If fewer than 3 target topics exist, fill remaining slots using `not_attempted` topics.
   - Eligibility: All prerequisites of the topic must be either `strong` ($p \ge 0.80$ with $\ge 3$ answers) or non-existent.
   - Candidate order: Stable course order (`course.id ASC`) followed by topic order (`topic.order ASC`).
   - Fixed need:
     $$\text{need} = \text{NOT\_ATTEMPTED\_NEED} = 0.50$$
3. **Resource Availability Guard:** Topics containing zero embedded learning resources are skipped.

---

## 6. Difficulty Fit & Filtering

Questions and resources share a 3-level difficulty scale:
- `easy`: rank 0
- `medium`: rank 1
- `hard`: rank 2

### 6.1 Target Difficulty by Mastery
The learner's target difficulty rank for a topic is derived from their current topic mastery $p$:
- **Easy (rank 0):** $p < 0.40$ (or `not_attempted`)
- **Medium (rank 1):** $0.40 \le p < 0.70$
- **Hard (rank 2):** $p \ge 0.70$

### 6.2 Difficulty Exclusion Filter
- Exclude candidate resources where:
  $$\text{resource\_rank} - \text{target\_rank} \ge 2$$
  *(i.e., a learner targeted for `easy` (rank 0) is never shown `hard` (rank 2) resources).*
- **Filter Relaxation:** If filtering removes all candidates for a topic, relax the filter and allow all candidates for that topic.

---

## 7. Learner Similarity Metric

Given learner $u$ and peer learner $v$, similarity is calculated across topics both learners have attempted:

$$\text{sim}(u, v) = 1.0 - \frac{1}{|S_{uv}|} \sum_{t \in S_{uv}} |m_{u, t} - m_{v, t}|$$

where:
- $S_{uv}$ is the set of topics where both $u$ and $v$ have recorded mastery ($total\_answers > 0$).
- $m_{u, t}, m_{v, t} \in [0.0, 1.0]$ are the respective topic mastery probabilities.

### Filtering & Neighbor Selection:
- **Shared Breadth Requirement:** $|S_{uv}| \ge \text{MIN\_SHARED\_TOPICS} = 3$. If fewer than 3 topics overlap, peer $v$ is excluded.
- **Minimum Correlation Threshold:** $\text{sim}(u, v) \ge \text{MIN\_SIMILARITY} = 0.75$.
- **Self Exclusion:** Learner $u$ is strictly excluded ($v \ne u$).
- **Top Neighbors:** Select up to `K_NEIGHBORS = 10` peers with the highest similarity.

---

## 8. Collaborative Scoring Engine

The collaborative score for resource $r$ within peer neighborhood $N_u$ is:

$$\text{collab}(r) = \frac{\sum_{v \in N_u} \text{sim}(u, v) \cdot \text{credit}(v, r)}{\sum_{v \in N_u} \text{sim}(u, v)}$$

### 8.1 Credit Attribution Rule
For peer $v$ and resource $r$ under topic $T$:
$$\text{credit}(v, r) = 1 \iff \begin{cases} v \text{ clicked resource } r \; (\text{clicked\_at IS NOT NULL}) \\ \text{AND} \\ \text{mastery}_{v, T}^{\text{current}} > \text{mastery}_{v, T}^{\text{shown}} + \text{IMPROVEMENT\_MARGIN} \; (0.05) \end{cases}$$
Otherwise, $\text{credit}(v, r) = 0$. Each $(v, r)$ pair is credited at most once.

### 8.2 Availability Fallback
If $\text{collab}(r) = 0.0$ for all candidate resources across the topic pool, the collaborative component is marked **unavailable**.

---

## 9. Multi-Component Scoring Function

Each candidate resource $r$ receives a composite recommendation score:

$$\text{score}(r) = W_{\text{NEED}} \cdot \text{need} + W_{\text{SEMANTIC}} \cdot \text{semantic} + W_{\text{DIFF}} \cdot \text{difficulty\_fit} + W_{\text{COLLAB}} \cdot \text{collaborative}$$

### 9.1 Component Definitions
1. **`need`:**
   - Attempted topic: $1.0 - \text{mastery}$
   - `not_attempted` topic: $0.50$
2. **`semantic`:**
   - Raw cosine similarity: $\cos(\mathbf{q}_{\text{topic}}, \mathbf{e}_r)$.
   - Min-max scaled across candidates within that topic's pool:
     $$\text{semantic} = \frac{\cos(r) - \min_{c} \cos(c)}{\max_{c} \cos(c) - \min_{c} \cos(c)}$$
   - If $\max_c \cos(c) == \min_c \cos(c)$ or pool size is 1, default to $0.50$.
3. **`difficulty_fit`:**
   - Distance $|\text{rank}_r - \text{target\_rank}|$:
     - $0$ levels apart $\implies 1.0$
     - $1$ level apart $\implies 0.5$
     - $2$ levels apart $\implies 0.0$
4. **`collaborative`:** $\text{collab}(r)$ from Section 8.

### 9.2 Strategy Weight Profiles & Dynamic Rescaling
Base strategy profiles configured in `app/recommender/config.py`:

| Strategy | $W_{\text{NEED}}$ | $W_{\text{SEMANTIC}}$ | $W_{\text{DIFF}}$ | $W_{\text{COLLAB}}$ |
| :--- | :---: | :---: | :---: | :---: |
| `hybrid` | 0.30 | 0.30 | 0.15 | 0.25 |
| `content_only` | 0.40 | 0.40 | 0.20 | 0.00 |

**Dynamic Normalization Rule:**
If any component is unavailable (e.g., collaborative score unavailable) or has zero base weight, drop that component and normalize remaining weights to sum to 1.0:
$$W_k' = \frac{W_k}{\sum_{j \in \text{available}} W_j}$$

---

## 10. Worked Verification Example (Unit Test Benchmark)

This numerical example serves as an exact reference fixture for automated testing:

**Context:**
- Current Topic Mastery: $p = 0.30$
- Need: $1.0 - 0.30 = 0.70$
- Target Difficulty: $p < 0.40 \implies \text{easy}$ (rank 0)
- Candidate Pool: 3 resources ($A$, $B$, $D$)

| Resource | Difficulty | Raw Cosine | Collab Score | Semantic Min-Max | Fit Distance | Difficulty Fit |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A** | easy (0) | 0.62 | 0.60 | $\frac{0.62 - 0.40}{0.22} = \mathbf{1.000}$ | $|0 - 0| = 0$ | $\mathbf{1.0}$ |
| **B** | medium (1) | 0.48 | 0.10 | $\frac{0.48 - 0.40}{0.22} = \frac{4}{11} \approx \mathbf{0.364}$ | $|1 - 0| = 1$ | $\mathbf{0.5}$ |
| **D** | easy (0) | 0.40 | 0.00 | $\frac{0.40 - 0.40}{0.22} = \mathbf{0.000}$ | $|0 - 0| = 0$ | $\mathbf{1.0}$ |

### Case 1: Hybrid Strategy (All Components Available)
Weights: $\text{need}=0.30, \text{semantic}=0.30, \text{diff}=0.15, \text{collab}=0.25$
- **Resource A:**
  $$0.30(0.70) + 0.30(1.000) + 0.15(1.0) + 0.25(0.60) = 0.210 + 0.300 + 0.150 + 0.150 = \mathbf{0.810}$$
- **Resource B:**
  $$0.30(0.70) + 0.30(0.3636) + 0.15(0.5) + 0.25(0.10) = 0.210 + 0.1091 + 0.075 + 0.025 = \mathbf{0.419}$$
- **Resource D:**
  $$0.30(0.70) + 0.30(0.000) + 0.15(1.0) + 0.25(0.00) = 0.210 + 0.000 + 0.150 + 0.000 = \mathbf{0.360}$$

### Case 2: Collaborative Component Unavailable
Rescaled Weights: $\text{need}=0.40, \text{semantic}=0.40, \text{diff}=0.20, \text{collab}=0.00$
- **Resource A:**
  $$0.40(0.70) + 0.40(1.000) + 0.20(1.0) = 0.280 + 0.400 + 0.200 = \mathbf{0.880}$$
- **Resource B:**
  $$0.40(0.70) + 0.40(0.3636) + 0.20(0.5) = 0.280 + 0.1455 + 0.100 = \mathbf{0.526}$$
- **Resource D:**
  $$0.40(0.70) + 0.40(0.000) + 0.20(1.0) = 0.280 + 0.000 + 0.200 = \mathbf{0.480}$$

---

## 11. Deterministic Explanation Engine

Explanations are assembled using deterministic rule templates (zero external LLM inference, strictly private with no peer identities exposed):

1. **Competency Status Clause:**
   - Weak: *"Your mastery in {topic} is low ({mastery}%)."*
   - Developing: *"You are making progress in {topic} ({mastery}% mastery)."*
   - Not Attempted: *"You have not started {topic} yet."*
2. **Prerequisite Redirection Clause (if substituted):**
   - *"You are weak in {prereq}, a foundational prerequisite of {target}; focus on this first."*
3. **Misconception / Semantic Clause:**
   - If $\text{semantic} \ge 0.50$ and wrong answers were included in the query:
     *"Matches the questions you recently answered incorrectly in this topic."*
4. **Difficulty Alignment Clause:**
   - Equal rank: *"Matches your recommended {target_diff} difficulty level."*
   - Adjacent rank: *"Introduces slightly more advanced material to challenge your understanding."*
5. **Peer Evidence Clause:**
   - If $N > 0$ neighbors improved after clicking:
     *"{N} similar learner(s) improved their mastery after engaging with this resource."*
6. **Unattempted Fill Clause:**
   - *"Topic not started, but all prerequisite competencies have been satisfied."*

---

## 12. Relational Database Schema

### 12.1 Modifications to Existing Tables
- **`learning_resources`:**
  - `difficulty`: `VARCHAR(16) NOT NULL DEFAULT 'medium'` (constrained to `'easy'`, `'medium'`, `'hard'`)
  - `embedding`: `vector(384) NULL`
  - `embedding_hash`: `VARCHAR(64) NULL`
  - `CONSTRAINT uq_learning_resources_topic_url UNIQUE (topic_id, url)`

### 12.2 Table: `topic_prerequisites`
```sql
CREATE TABLE topic_prerequisites (
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    prerequisite_topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    CONSTRAINT pk_topic_prerequisites PRIMARY KEY (topic_id, prerequisite_topic_id),
    CONSTRAINT chk_topic_prerequisites_no_self CHECK (topic_id <> prerequisite_topic_id)
);

ALTER TABLE topic_prerequisites ENABLE ROW LEVEL SECURITY;
```

### 12.3 Table: `recommendation_impressions`
```sql
CREATE TABLE recommendation_impressions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resource_id INTEGER NOT NULL REFERENCES learning_resources(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    request_id UUID NOT NULL,
    strategy VARCHAR(32) NOT NULL,
    rank INTEGER NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    mastery_at_shown DOUBLE PRECISION NULL,
    components JSONB NOT NULL,
    reason TEXT NOT NULL,
    shown_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    clicked_at TIMESTAMPTZ NULL,
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX ix_recommendation_impressions_user_shown ON recommendation_impressions (user_id, shown_at);
CREATE INDEX ix_recommendation_impressions_resource ON recommendation_impressions (resource_id);

ALTER TABLE recommendation_impressions ENABLE ROW LEVEL SECURITY;
```

---

## 13. API Specification

All endpoints require authentication via `get_current_user`. The active learner identity is derived strictly from the JWT bearer token (never accepted via request parameters or body).

### 13.1 `POST /api/recommendations/me`
Generates personalized recommendations, evaluates scoring components, logs impression rows, and returns ranked learning materials.

- **Query Parameters:**
  - `strategy` (optional, default `"hybrid"`): `"hybrid"` or `"content_only"`.
- **Response Structure (200 OK):**
```json
{
  "request_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "strategy": "hybrid",
  "collaborative_available": true,
  "items": [
    {
      "impression_id": 401,
      "rank": 1,
      "resource": {
        "id": 12,
        "title": "TCP Flow Control Explained",
        "description": "Visual walkthrough of sliding window protocols.",
        "resource_type": "VIDEO",
        "url": "https://learnwise.test/resources/tcp-flow",
        "difficulty": "easy"
      },
      "topic": {
        "id": 5,
        "title": "Transport Layer"
      },
      "score": 0.810,
      "mastery": 0.30,
      "status": "weak",
      "reason": "Your mastery in Transport Layer is low (30%). Matches the questions you recently answered incorrectly in this topic. Matches your recommended easy difficulty level. 3 similar learner(s) improved their mastery after engaging with this resource.",
      "components": {
        "need": 0.70,
        "semantic": 1.000,
        "difficulty_fit": 1.0,
        "collaborative": 0.60
      }
    }
  ]
}
```

### 13.2 `POST /api/recommendations/impressions/{id}/click`
Records learner engagement against an existing impression.
- **Path Parameter:**
  - `id`: Integer primary key of `recommendation_impressions`.
- **Security Check:** Returns 404 if the impression ID does not belong to the authenticated user.
- **Idempotency:** If `clicked_at` is already set, retains the original timestamp and executes a no-op update.
- **Response (200 OK):**
```json
{
  "impression_id": 401,
  "resource_url": "https://learnwise.test/resources/tcp-flow",
  "clicked_at": "2026-10-29T12:00:00Z"
}
```

---

## 14. Known Limitations & Edge Cases

1. **Heuristic BKT Parameters:** Mastery states rely on global heuristic parameters rather than dynamically fit student populations.
2. **Cold-Start Collaborative Fallback:** Before peer impressions and clicks accumulate, the collaborative component evaluates to 0 and gracefully drops out, causing the engine to operate in rescaled content-only mode.
3. **Synthetic Response Grounding:** Synthetic evaluations establish pipeline validity and clustering structure; they do not simulate authentic cognitive progression.
4. **Neighbor Search Complexity:** Nearest-neighbor calculation runs in $O(|U| \cdot |S|)$ where $|U|$ is active learners and $|S|$ is shared topics. Acceptable for Phase 6 scale; approximate nearest neighbors (ANN) will be adopted if learner count exceeds $10^4$.
5. **No Long-Term Completion Tracking:** The system logs clicks but does not monitor total reading or video watch duration; a previously clicked resource can be re-recommended if its topic continues to exhibit high need.
6. **Click Simulation Safety Guard:** `scripts/simulate_recommendation_clicks.py` verifies that all synthetic learners from the Phase 5 generator exist (expected count read directly from `seed_synthetic_learners.py` constants, e.g. 50, never hard-coded) before simulating clicks.

---

## 15. Deviations from Initial Specification

During Phase 6 implementation, only one minor operational enhancement was introduced:
- **Fallback Query Construction (Section 3.3):**
  - *Spec:* When a learner has no recent incorrect responses in a target topic, the query text was specified as `"{topic title}"`.
  - *Implementation:* The engine enriches the fallback text to `"{topic title}. {topic description}"`.
  - *Rationale:* Since learning resources are embedded with `"{topic title}. {resource title}. {resource description}"`, using both the topic title and description for cold-start queries produces significantly closer semantic alignment with introductory resources than a bare 2-word topic title alone.

---

## 16. How to Demo

Follow these sequential steps from the `backend/` directory or project root to demonstrate the complete end-to-end adaptive recommendation pipeline:

### Step 1: Import Learning Resources & Prerequisites
Ensure the curated catalog and prerequisite graph are imported into the target database:
```zsh
# Run from repository root
python scripts/import_resources.py --file data/resources.csv
python scripts/import_prerequisites.py --file data/prerequisites.csv
```

### Step 2: Generate Vector Embeddings
Compute offline embeddings for all un-embedded resources using FastEmbed:
```zsh
# Generates 384-dimensional dense vectors
python scripts/embed_resources.py
```

### Step 3: Seed Synthetic Learner Population (If Needed)
If collaborative peer history has not yet been generated, seed 50 synthetic learners across Archetypes A–E:
```zsh
SYNTHETIC_PASSWORD="SyntheticTestPass123!" python -m app.seeds.seed_synthetic_learners
```

### Step 4: Simulate Peer Feedback & Clicks
Simulate learner engagement impressions and positive mastery outcomes:
```zsh
# Dry run verification
python scripts/simulate_recommendation_clicks.py --dry-run

# Execute simulation with rebuild
python scripts/simulate_recommendation_clicks.py --rebuild
```

### Step 5: Test Recommendations via API
1. **Log in as a Learner:**
   ```zsh
   curl -s -X POST http://localhost:8000/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email": "learner@learnwise.com", "password": "password123"}' | jq .
   ```
   Save the returned `access_token`.

2. **Generate Recommendations (`POST /api/recommendations/me`):**
   ```zsh
   curl -s -X POST "http://localhost:8000/api/recommendations/me?strategy=hybrid" \
     -H "Authorization: Bearer <ACCESS_TOKEN>" | jq .
   ```

3. **Click an Impression:**
   Extract an `impression_id` from the returned items:
   ```zsh
   curl -s -X POST "http://localhost:8000/api/recommendations/impressions/<IMPRESSION_ID>/click" \
     -H "Authorization: Bearer <ACCESS_TOKEN>" | jq .
   ```

---

## 17. Viva Notes & Oral Examination Guide

Key talking points for architectural defense and evaluation:

1. **Why Hybrid Architecture?**
   - Combining content-based semantic matching with collaborative filtering mitigates both the cold-start problem (pure collaborative fails with few users) and the filter bubble (pure content-based lacks peer discovery).
2. **Cold-Start Handling:**
   - When collaborative signals are missing, weights dynamically renormalize to $1.0$ across need ($0.40$), semantic similarity ($0.40$), and difficulty fit ($0.20$), gracefully falling back without errors.
3. **Misconception-Driven Retrieval:**
   - Rather than embedding user profile summaries, the query text directly incorporates the learner's last 3 incorrectly answered questions in the topic. This steers the embedding toward resources explaining the exact concepts missed.
4. **Privacy-Preserving Explanations:**
   - Recommendations explicitly explain *why* an item was chosen (e.g. topic need, difficulty match, peer validation) without exposing peer identities, emails, or scores.
5. **Prerequisite Redirection:**
   - If a learner is weak in an advanced topic whose prerequisite topic is also weak, the recommender dynamically redirects focus to the unmet foundational prerequisite before recommending advanced resources.
6. **No Heavy PyTorch / GPU Dependency:**
   - Utilizing ONNX Runtime via `fastembed` produces sub-50ms embedding inference with negligible CPU/memory overhead and zero multi-gigabyte PyTorch/CUDA overhead.

---

## 18. Implementation Chunk Roadmap

| Chunk | Milestone Title | Key Deliverables |
| :---: | :--- | :--- |
| **6.0** | Specification & Architecture | `docs/RECOMMENDER.md` (this document), test baseline verification. |
| **6.1** | Schema & Database Infrastructure | Alembic migration for `learning_resources` fields (`difficulty`, `embedding`, `embedding_hash`), `topic_prerequisites`, `recommendation_impressions`, and SQLAlchemy models. |
| **6.2** | Data Seeding & Prerequisite Validation | Idempotent prerequisite seed script, DAG cycle validation, and curated learning resource difficulty enrichment. |
| **6.3** | Embeddings & Offline Batch Pipeline | Fastembed integration, `scripts/embed_resources.py`, hashing cache, and fake hashing test embedder (`EMBEDDER_BACKEND=fake`). |
| **6.4** | Recommendation Engine Core | Target topic selection, prerequisite redirection, difficulty fit, neighbor similarity, collaborative scoring, and worked-example test fixture. |
| **6.5** | Endpoints, Audit Logging & Verification | `/api/recommendations/me`, `/click` endpoints, impression recording, `simulate_recommendation_clicks.py` script, and end-to-end test suite. |
