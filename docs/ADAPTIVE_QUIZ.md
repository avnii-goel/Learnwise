# Phase 7: Single-Topic Adaptive Quizzing Specification

## 1. Ground Rules

All Phase 7 implementation tasks must adhere strictly to these engineering constraints:
1. **Scope Boundaries:** Execute ONLY the current assigned chunk. Never add speculative or unrequested features.
2. **No A/B Machinery:** Adaptive quizzing is purely algorithmic and deterministic. A/B testing infrastructure and comparative telemetry are strictly deferred to Phase 8.
3. **Database Isolation:** Never connect to or execute migrations or scripts against the shared Supabase database. If a task requires changes on the shared database, provide the exact commands for manual execution.
4. **Regression Safety:** Keep all existing tests passing. Execute test suites strictly against the local test database (`localhost:5433`).
5. **No Unprompted Commits:** Do not make Git commits unless explicitly instructed.
6. **Lean Delivery & Verification:** Conclude each chunk with a concise operational report detailing files changed, tests run with real outputs, deviations from spec, and manual operational actions.
7. **Knowledge Model Consistency:** Reuse status thresholds and mastery semantics from `docs/KNOWLEDGE_MODEL.md` (e.g., `not_attempted`, `weak`, `developing`, `strong`) and the difficulty cutoffs from `docs/RECOMMENDER.md` Section 6.1 by reference. Never duplicate or redefine them.

---

## 2. Overview & System Scope

Phase 7 introduces **Single-Topic Adaptive Quizzing** to LearnWise. Unlike the platform's initial 20-question course-wide diagnostic quiz, an adaptive quiz focuses deeply on an individual topic to rapidly pinpoint and advance learner mastery.

### Key Architectural Characteristics
- **Topic Scope:** Exactly ONE topic per adaptive quiz session (`topic_id`).
- **Quiz Length:** `ADAPTIVE_QUIZ_LENGTH = 8` questions.
- **Serving Mechanism:** Questions are served sequentially **one question at a time**. The next question is dynamically selected based on the learner's updated running mastery posterior.
- **Stopping Rule:** Fixed-length stopping rule (terminates immediately upon completion of the 8th question).
- **Isolation of Fixed Quizzes:** The existing fixed 20-question course quiz pipeline (`POST /api/quiz/generate/course/{course_id}` and `POST /api/quiz/submit`) remains completely unchanged and continues operating alongside adaptive quizzing.

---

## 3. Difficulty Adaptation & BKT Progression

### 3.1 Initial Mastery ($p_{\text{running}}$)
At the start of an adaptive quiz session for topic $T$:
- If the learner has an existing `TopicMastery` record for $T$ with `total_answers > 0`:
  $$p_{\text{running}} = \text{TopicMastery.mastery\_probability}$$
- If no record exists or `total_answers == 0`:
  $$p_{\text{running}} = P_{\text{INIT}} = 0.30$$

### 3.2 Dynamic In-Session Mastery Updates
Immediately after the learner submits an answer to a served question:
$$p_{\text{running}} \leftarrow \text{update\_mastery}(p_{\text{running}}, \text{is\_correct}, \text{difficulty\_of\_served\_question})$$

This update reuses the **identical canonical function** from Phase 5 (`backend/app/services/bkt.py`). The BKT parameter matrix is:
- **Easy:** $\text{slip} = 0.05, \text{guess} = 0.30$
- **Medium:** $\text{slip} = 0.10, \text{guess} = 0.25$
- **Hard:** $\text{slip} = 0.15, \text{guess} = 0.20$
- **Transit:** $P_{\text{TRANSIT}} = 0.10$
- **Clamping Bounds:** $\text{MIN\_P} = 0.01, \text{MAX\_P} = 0.99$

### 3.3 Target Difficulty Cutoffs
The target difficulty level for the next question is derived directly from $p_{\text{running}}$, referencing `docs/RECOMMENDER.md` Section 6.1:
- **Easy (`rank 0`):** $p_{\text{running}} < 0.40$
- **Medium (`rank 1`):** $0.40 \le p_{\text{running}} < 0.70$
- **Hard (`rank 2`):** $p_{\text{running}} \ge 0.70$

### 3.4 No Redundant Streak Rule
> [!IMPORTANT]
> The engine does **NOT** incorporate a separate "streak rule" (e.g., jump difficulty after 2 consecutive correct answers). Bayesian Knowledge Tracing inherently updates the posterior exponentially across successive correct or incorrect responses. Introducing an external streak rule would artificially double-count evidence and destabilize the Bayesian posterior.

---

## 4. Worked Example Reference Fixtures

The following deterministically calculated traces serve as exact assertions for unit test fixtures. All calculations were verified against `backend/app/services/bkt.py:update_mastery`.

### Trace 1: Starting at $p = 0.50$ (Mid-Level Learner)
- **Initial:** $p = 0.5000 \rightarrow$ Target: **Medium**
- **Q1 (Medium, Correct):**
  $$\text{posterior} = \frac{0.50 \cdot 0.90}{(0.50 \cdot 0.90) + (0.50 \cdot 0.25)} = \frac{0.45}{0.575} \approx 0.782609$$
  $$p_{\text{new}} = 0.782609 + (1 - 0.782609) \cdot 0.10 \approx \mathbf{0.804348} \quad (\rightarrow \text{Target: } \mathbf{Hard})$$
- **Q2 (Hard, Correct):**
  $$\text{posterior} = \frac{0.804348 \cdot 0.85}{(0.804348 \cdot 0.85) + (0.195652 \cdot 0.20)} = \frac{0.683696}{0.722826} \approx 0.945865$$
  $$p_{\text{new}} = 0.945865 + (1 - 0.945865) \cdot 0.10 \approx \mathbf{0.951278} \quad (\rightarrow \text{Target: } \mathbf{Hard})$$
- **Q3 (Hard, Wrong):**
  $$\text{posterior} = \frac{0.951278 \cdot 0.15}{(0.951278 \cdot 0.15) + (0.048722 \cdot 0.80)} = \frac{0.142692}{0.181669} \approx 0.785448$$
  $$p_{\text{new}} = 0.785448 + (1 - 0.785448) \cdot 0.10 \approx \mathbf{0.806903} \quad (\rightarrow \text{Target: } \mathbf{Hard})$$
- **Q4 (Hard, Wrong):**
  $$\text{posterior} = \frac{0.806903 \cdot 0.15}{(0.806903 \cdot 0.15) + (0.193097 \cdot 0.80)} = \frac{0.121035}{0.275513} \approx 0.439310$$
  $$p_{\text{new}} = 0.439310 + (1 - 0.439310) \cdot 0.10 \approx \mathbf{0.495379} \quad (\rightarrow \text{Target: } \mathbf{Medium})$$

### Trace 2: Cold Start ($p = 0.30$) Rapid Progression
- **Initial:** $p = 0.3000 \rightarrow$ Target: **Easy**
- **Q1 (Easy, Correct):**
  $$p_{\text{new}} = \mathbf{0.618182} \quad (\rightarrow \text{Target: } \mathbf{Medium})$$
- **Q2 (Medium, Correct):**
  $$p_{\text{new}} = \mathbf{0.868201} \quad (\rightarrow \text{Target: } \mathbf{Hard})$$

### Trace 3: Cold Start ($p = 0.30$) Repeated Errors
- **Initial:** $p = 0.3000 \rightarrow$ Target: **Easy**
- **Q1 (Easy, Wrong):**
  $$p_{\text{new}} = \mathbf{0.126733} \quad (\rightarrow \text{Target: } \mathbf{Easy})$$
- **Q2 (Easy, Wrong):**
  $$p_{\text{new}} = \mathbf{0.109234} \quad (\rightarrow \text{Target: } \mathbf{Easy})$$

*(Note: Maximum deviation between specified prompt values and recomputed values is $0.000048$, well below the $0.0005$ tolerance threshold).*

---

## 5. Question Selection Algorithm

When selecting the question for step $s \in \{1, \dots, 8\}$:

### 5.1 Candidate Pool & Cost Metric
1. **Intra-Attempt Exclusion:** Any question already served in the current attempt (`step_number < s`) is strictly excluded.
2. **Cost Calculation:** For every other question $q$ in the target topic:
   $$\text{cost}(q) = |\text{rank}(q) - \text{target\_rank}| + \text{seen\_penalty}(q)$$
   where:
   - $\text{rank}(q) \in \{0, 1, 2\}$ for `easy`, `medium`, `hard`.
   - $\text{seen\_penalty}(q) = 1$ if the learner has answered question $q$ in any prior quiz attempt on the platform; otherwise $0$.

### 5.2 Tie-Breaking Hierarchy
Questions are sorted by $\text{cost}(q)$ ascending. Ties are broken in strict order:
1. **Unseen First:** Questions with $\text{seen\_penalty} = 0$ beat questions with $\text{seen\_penalty} = 1$.
2. **Easier Level First:** Lower difficulty rank wins ($\text{rank}(q)$ ascending).
3. **Least Recently Answered:** For seen questions, the question with the oldest historical `answered_at` timestamp is selected.
4. **Random Selection:** Deterministic random selection using an injectable `random.Random` instance (for test reproducibility).

### 5.3 Selection Reasons (`selection_reason`)
Each selected question is tagged with an audit string:
- `unseen_at_target`: $\text{rank}(q) == \text{target\_rank}$ and $\text{seen\_penalty}(q) == 0$.
- `unseen_other_level`: $\text{rank}(q) \ne \text{target\_rank}$ and $\text{seen\_penalty}(q) == 0$.
- `seen_reused`: $\text{seen\_penalty}(q) == 1$ (reused due to exhaustion of unseen items).

### 5.4 Canonical Selection Example
- **Scenario:** Current target is **Hard** (`target_rank = 2`). All hard questions in this topic have been seen in prior attempts. Unseen medium questions exist.
- **Evaluation:**
  - Candidate A (Unseen Medium): $|\text{rank}(1) - 2| + 0 = 1 + 0 = \mathbf{1}$.
  - Candidate B (Seen Hard): $|\text{rank}(2) - 2| + 1 = 0 + 1 = \mathbf{1}$.
- **Result:** Both candidates tie with $\text{cost} = 1$. Candidate A wins on tie-breaker criterion 1 (Unseen First).
- **Assigned Reason:** `unseen_other_level`.

---

## 6. End-of-Quiz Consistency & Transactional Atomicity

1. **Role of Running Mastery:** $p_{\text{running}}$ exists strictly in-memory and in step logs to guide real-time question difficulty targeting.
2. **Immediate Storage of Responses:** Each answer is persisted immediately to `quiz_responses` as it is submitted.
3. **Atomicity on the 8th Answer:** On submission of the 8th answer, inside a single database transaction:
   - The canonical `apply_attempt(...)` service is executed.
   - It acquires a pessimistic row lock (`SELECT ... FOR UPDATE`) on the user's `topic_mastery` row for this topic.
   - It processes all 8 responses in order, updating `topic_mastery` and appending an immutable `topic_mastery_history` record.
   - The `quiz_attempts` row is updated: `status = 'completed'`, `completed_at = NOW()`, `score` set to total correct answers, and `total_questions = 8`.
   - The transaction commits atomically.
4. **Mathematical Equivalence:** Because `apply_attempt` applies the identical BKT transition sequentially to the 8 responses, the final `TopicMastery.mastery_probability` is guaranteed to equal the 8th step's running estimate $p_8$.
5. **Zero Duplicate Logic:** The adaptive quiz path must never reimplement BKT mathematical equations or question answer verification; it directly invokes the tested domain services from Phase 5.

---

## 7. Anti-Skip, Concurrency & Lifecycle Guarantees

### 7.1 Immediate Feedback
After each valid answer submission, the endpoint returns whether the answer was correct, the uppercase string of the correct answer, and either the next pending question or the final completion summary.

### 7.2 Pending Question State
The system identifies the active pending step as the `adaptive_quiz_steps` row for this attempt where `answered_at IS NULL`. Exactly one step can be pending at any time.

### 7.3 Conflict Handling (HTTP 409)
The answer endpoint rejects requests with `409 Conflict` under the following conditions:
- **Wrong Question:** `question_id` in request body does not match the pending step's `question_id`.
- **Already Answered:** The specified question or step has already been answered.
- **Attempt Completed:** The attempt is already marked `status = 'completed'`.
- **Pool Underflow:** Attempting to start an adaptive quiz for a topic with fewer than 8 total questions in the database.

### 7.4 Ownership & Validation (HTTP 404 & 422)
- **HTTP 404 Not Found:** If the requested `attempt_id` does not exist or belongs to another user (`attempt.user_id != current_user.id`), or if `topic_id` does not exist.
- **HTTP 422 Unprocessable Entity:** If the submission payload fails Pydantic schema validation.

### 7.5 Resume Capability
Calling `POST /api/quiz/adaptive/start` for a topic where the learner already has an `in_progress` adaptive attempt **resumes** that session:
- Does NOT create a new attempt.
- Returns the current pending question with **HTTP 200 OK**.
- (A newly created attempt returns **HTTP 201 Created**).

### 7.6 Double-Submit Prevention
The `POST /api/quiz/adaptive/{attempt_id}/answer` endpoint begins by locking the `quiz_attempts` row using `SELECT ... FOR UPDATE`. Concurrent duplicate submissions from the same learner are serialized, with the second request returning `409 Conflict`.

### 7.7 Abandoned Attempts
- Attempts abandoned prior to the 8th answer remain `status = 'in_progress'` indefinitely.
- Abandoned attempts **never invoke `apply_attempt`** and **never affect topic mastery**.
- Phase 8 analytical queries and aggregations must explicitly filter `status = 'completed'`.

---

## 8. Relational Data Architecture

### 8.1 Modifications to Existing Table: `quiz_attempts`
Three new columns and one partial unique index are added:

```sql
ALTER TABLE quiz_attempts 
    ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'fixed' 
        CONSTRAINT chk_quiz_attempts_mode CHECK (mode IN ('fixed', 'adaptive')),
    ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'completed' 
        CONSTRAINT chk_quiz_attempts_status CHECK (status IN ('in_progress', 'completed')),
    ADD COLUMN topic_id INTEGER NULL 
        REFERENCES topics(id) ON DELETE CASCADE;

CREATE UNIQUE INDEX uq_adaptive_quiz_in_progress 
ON quiz_attempts (user_id, topic_id) 
WHERE mode = 'adaptive' AND status = 'in_progress';
```

#### Handling Existing NOT NULL Columns in `QuizAttempt`
- `course_id`: Set to `topic.course_id` (derived from the chosen topic).
- `score`: Initialized to `0` when the adaptive attempt is created; updated to actual correct count on step 8 completion.
- `total_questions`: Initialized to `8` (`ADAPTIVE_QUIZ_LENGTH`).
- `quiz_type`: Set to `"ADAPTIVE"` (retaining string type).
- `started_at`: Set to current timestamp (`NOW()`).
- `completed_at`: Initialized to `NULL` for in-progress attempts; populated with `NOW()` upon step 8 completion.
- Existing historical rows automatically become `mode = 'fixed'` and `status = 'completed'` via column defaults.

### 8.2 New Table: `adaptive_quiz_steps`

```sql
CREATE TABLE adaptive_quiz_steps (
    id SERIAL PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES quiz_attempts(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    target_difficulty VARCHAR(16) NOT NULL,
    served_difficulty VARCHAR(16) NOT NULL,
    selection_reason VARCHAR(32) NOT NULL,
    mastery_before DOUBLE PRECISION NOT NULL,
    mastery_after DOUBLE PRECISION NULL,
    selected_answer VARCHAR(1) NULL,
    is_correct BOOLEAN NULL,
    served_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    answered_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_adaptive_steps_attempt_step UNIQUE (attempt_id, step_number),
    CONSTRAINT uq_adaptive_steps_attempt_question UNIQUE (attempt_id, question_id)
);

CREATE INDEX ix_adaptive_quiz_steps_attempt ON adaptive_quiz_steps (attempt_id);
```

### 8.3 Row Level Security (RLS)
In accordance with platform security standards:
```sql
ALTER TABLE adaptive_quiz_steps ENABLE ROW LEVEL SECURITY;
```
RLS is enabled with no public policies, restricting direct PostgREST access while allowing backend connection pool access.

---

## 9. API Specification

All adaptive quiz endpoints require authentication via `current_user: User = Depends(get_current_user)`.

### 9.1 `POST /api/quiz/adaptive/start`
Starts a new 8-question adaptive quiz for the specified topic, or resumes an existing in-progress attempt.

- **Request Body (`AdaptiveQuizStartRequest`):**
  ```json
  {
    "topic_id": 14
  }
  ```
- **Response Structure (201 Created for new, 200 OK for resumed):**
  ```json
  {
    "attempt_id": 105,
    "topic_id": 14,
    "mode": "adaptive",
    "total_questions": 8,
    "question_number": 1,
    "question": {
      "question_id": 78,
      "topic_id": 14,
      "question_text": "What is the primary function of an inverted page table?",
      "option_a": "To track pages per process",
      "option_b": "To maintain one entry per physical frame in memory",
      "option_c": "To eliminate the need for virtual memory",
      "option_d": "To accelerate secondary storage paging"
    }
  }
  ```
  *(Note: Correct answer and difficulty rating are strictly withheld from the client).*

### 9.2 `POST /api/quiz/adaptive/{attempt_id}/answer`
Submits an answer for the currently pending step.

- **Request Body (`AdaptiveQuizAnswerRequest`):**
  ```json
  {
    "question_id": 78,
    "selected_answer": "B"
  }
  ```
- **Intermediate Response (Steps 1 to 7 — 200 OK):**
  ```json
  {
    "attempt_id": 105,
    "question_id": 78,
    "is_correct": true,
    "correct_answer": "B",
    "question_number": 1,
    "finished": false,
    "next_question": {
      "question_id": 83,
      "topic_id": 14,
      "question_text": "How does segmentation handle address translation?",
      "option_a": "Using fixed segment sizes",
      "option_b": "Through segment table base and limit registers",
      "option_c": "Via direct cache indexing",
      "option_d": "By hashing the virtual segment offset"
    },
    "result": null
  }
  ```
- **Final Response (Step 8 — 200 OK):**
  ```json
  {
    "attempt_id": 105,
    "question_id": 92,
    "is_correct": true,
    "correct_answer": "A",
    "question_number": 8,
    "finished": true,
    "next_question": null,
    "result": {
      "attempt_id": 105,
      "topic_id": 14,
      "score": 6,
      "total_questions": 8,
      "percentage": 75.0,
      "correct_answers": 6,
      "incorrect_answers": 2,
      "mastery_before": 0.40,
      "mastery_after": 0.8124,
      "status": "strong"
    }
  }
  ```

---

## 10. Telemetry & Phase 8 Preparation

Adaptive quizzing logs all operational data directly to the relational schema without extra infrastructure:
1. `quiz_attempts.mode`: Categorizes quizzes as `'fixed'` vs `'adaptive'`.
2. `quiz_attempts.status`: Differentiates `'completed'` from `'in_progress'`.
3. `adaptive_quiz_steps`: Comprehensive per-question audit row containing:
   - `target_difficulty`
   - `served_difficulty`
   - `selection_reason`
   - `mastery_before`
   - `mastery_after`
   - `served_at` and `answered_at` (latencies)

No additional tables or logging mechanisms are introduced.

---

## 11. Test Requirements

Phase 7 requires comprehensive test coverage spanning engine mechanics, edge cases, and API transactions.

| Test Name | Verification Objective |
| :--- | :--- |
| `test_adaptive_engine_worked_example` | Replicate Trace 1 step-by-step with exact numerical BKT assertions. |
| `test_adaptive_good_learner_trends_up` | Strong learner (100% correct) rapidly escalates from Easy/Medium to Hard questions. |
| `test_adaptive_bad_learner_stays_easy` | Struggling learner (0% correct) remains locked at Easy difficulty. |
| `test_adaptive_no_repeats_within_quiz` | An 8-question quiz never serves duplicate questions in the same attempt. |
| `test_adaptive_seen_unseen_cost_rule` | Cost formula prioritizes unseen items over previously answered items. |
| `test_adaptive_fallback_level_exhausted` | Fallback gracefully selects nearest available difficulty when target rank is exhausted. |
| `test_adaptive_cold_start` | Unattempted topic initializes at $P_{\text{INIT}} = 0.30$ and targets Easy. |
| `test_adaptive_anti_skip_conflict` | 409 returned when submitting wrong question, duplicate answer, or to completed quiz. |
| `test_adaptive_ownership_authorization` | 404 returned when attempting to access or answer another user's quiz attempt. |
| `test_adaptive_resume_in_progress` | Calling start on an in-progress quiz returns HTTP 200 and the existing pending question. |
| `test_adaptive_final_mastery_matches_running` | Final `TopicMastery.mastery_probability` exactly equals step 8's running posterior. |
| `test_fixed_course_quiz_unchanged` | Existing 20-question course quiz routes and calculations remain 100% functional. |
| `test_adaptive_atomic_rollback_on_failure` | Injected failure during step 8 completion rolls back mastery updates completely. |

---

## 12. Known Limitations

The adaptive quizzing system is subject to the following known constraints:
1. **Heuristic BKT Parameters:** Parameters ($P_T = 0.10, s \in [0.05, 0.15], g \in [0.20, 0.30]$) are grounded in literature baselines rather than empirically fit from student telemetry.
2. **Catalog Question Depth:** With topics seeded with ~20 questions each, repeated questions will naturally appear by the learner's 2nd or 3rd adaptive quiz on that topic.
3. **Single Topic Focus:** Quizzes evaluate one topic at a time; multi-topic adaptive testing is out of scope.
4. **Fixed-Length Termination:** The stopping rule is fixed at 8 questions; confidence-interval early stopping is omitted.
5. **Abandoned Attempt Retention:** In-progress abandoned attempts do not auto-expire via background tasks.
6. **Parallel Quiz Completion Discrepancy:** Running mastery $p$ is initialized from the learner's topic mastery when the adaptive quiz starts. If the learner completes another quiz (e.g. a fixed course quiz) on the same topic while an adaptive quiz is in-progress, the final stored mastery (computed from all recorded attempts by `apply_attempt`) can differ slightly from the last in-session running estimate.
7. **Phase 8 Analytics Filtering:** Because in-progress adaptive attempts exist in `quiz_attempts`, Phase 8 analytics and reporting dashboards must explicitly filter `QuizAttempt.status == 'completed'`.
8. **Synthetic Verification Scope:** Synthetic testing demonstrates algorithmic correctness and data integrity, not human learning efficacy.
9. **Subjective Difficulty Labels:** Question difficulty ratings are author-assigned labels rather than calibrated Item Response Theory parameters.

---

## 13. Deviations from Initial Specification

1. **`completed_at` Model Default & Fixed Quiz Resolution:** `server_default=func.now()` was removed from `QuizAttempt.completed_at` in the SQLAlchemy model (`backend/app/models/quiz_attempt.py`) during Chunk 7.3 so that Python could explicitly set `completed_at=None` when creating in-progress adaptive quiz attempts. While the PostgreSQL column default remains `DEFAULT now()`, SQLAlchemy's omitted parameter behavior caused fixed quiz submissions (`POST /api/quiz/submit` in `backend/app/routes/quiz.py`) to send `completed_at: None`, resulting in `completed_at = NULL`. This was diagnosed in Chunk 7.4 and fixed in Chunk 7.5 by explicitly setting `completed_at` to the current UTC timestamp across every completed-attempt creator (`backend/app/routes/quiz.py`, `backend/app/seeds/seed_synthetic_learners.py`, and test fixtures in `backend/tests/test_mastery_service.py` and `backend/tests/test_adaptive_quiz_schema.py`). The model's nullable definition without `server_default` was retained so adaptive in-progress attempts remain `completed_at = NULL`.
2. **Extra `'resumed'` Boolean in Start Response:** `POST /api/quiz/adaptive/start` includes a `resumed: bool` field (`False` for newly created attempts, `True` when resuming an active in-progress attempt).
3. **Extra `'explanation'` Attribute in Answer Schema:** `AdaptiveAnswerResponse` includes `explanation: str | None = None`, allowing the API to return the revealed answer explanation alongside `correct_answer`.
4. **Explicit `status == 'completed'` Queries:** Added `.filter(QuizAttempt.status == 'completed')` in `backend/app/seeds/backfill_mastery.py` and `backend/app/recommender/service.py` to ensure in-progress adaptive attempts are never counted in historical mastery backfills or candidate recommendations.
5. **Unified Correctness Helper Extraction:** Extracted `check_answer_correctness(selected_answer, correct_answer) -> bool` into `backend/app/services/quiz.py` to establish a single canonical correctness evaluator across both fixed course quizzes and single-topic adaptive quizzes.
6. **Adaptive Quiz Type Tagging:** `QuizAttempt.quiz_type` is assigned `"ADAPTIVE"` for adaptive quiz attempts, while `mode` (`'adaptive'` vs `'fixed'`) serves as the primary relational discriminator.
7. **Explicit `started_at` in `submit_quiz`:** In `backend/app/routes/quiz.py`, `started_at=now` was explicitly set on `QuizAttempt` alongside `completed_at=now` upon attempt creation for timestamp consistency.
8. **Test Fixture Cleanup in `conftest.py`:** Added `from app.models.adaptive_quiz_step import AdaptiveQuizStep` and `session.query(AdaptiveQuizStep).delete()` in `backend/tests/conftest.py` `db_session()` fixture to ensure step records are purged between test invocations.
9. **TOC Synchronization in `docs/KNOWLEDGE_MODEL.md`:** Updated Table of Contents in `docs/KNOWLEDGE_MODEL.md` to include Section 12 (*Synthetic Learner Population & Simulation Engine*).

---

## 14. Implementation Roadmap

- [x] **7.0 Specification:** `docs/ADAPTIVE_QUIZ.md`
- [x] **7.1 Schema & Migration:** Alembic migration, `quiz_attempts` alterations, `AdaptiveQuizStep` model.
- [x] **7.2 Selection Engine:** Pure selection & cost engine (`backend/app/services/adaptive.py`), worked example unit tests.
- [x] **7.3 Services & API:** `POST /api/quiz/adaptive/start` and `/answer` endpoints, state machine, anti-skip tests.
- [x] **7.4 Simulation & Demo:** End-to-end synthetic learner simulations, verification checks, demo script.
- [x] **7.5 Regression Fix:** Explicit completed_at assignment across attempt creators, end-to-end logging assertion.

---

## 15. How to Demo

Walkthrough commands to demonstrate adaptive quizzing locally against the local test database (`localhost:5433`). 

> [!NOTE]
> Always run demo commands against the local test DB using a freshly registered test account so production / synthetic learner baselines remain untouched.

### Step 0: Start the Backend against Local Test DB
In `backend/`:
```bash
DATABASE_URL="<LOCAL_TEST_DATABASE_URL>" venv/bin/uvicorn app.main:app --port 8000
```
*(Where `<LOCAL_TEST_DATABASE_URL>` is `postgresql+psycopg2://learnwise_user:learnwise_password@localhost:5433/learnwise_test`)*

### Step 1: Register Fresh Demo Learner and Obtain Token
```bash
DEMO_EMAIL="demo-learner-adaptive@example.com"
DEMO_PASS="<DEMO_PASSWORD>"

# Register a new isolated test account
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"${DEMO_EMAIL}\", \"password\": \"${DEMO_PASS}\", \"full_name\": \"Adaptive Demo Learner\"}" \
  | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))")

# If already registered, login instead:
if [ -z "$TOKEN" ]; then
  TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d "{\"email\": \"${DEMO_EMAIL}\", \"password\": \"${DEMO_PASS}\"}" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
fi
echo "Token: $TOKEN"
```

### Step 2: Start an Adaptive Quiz for Topic 1 (Network Fundamentals)
```bash
START_RESP=$(curl -s -X POST http://localhost:8000/api/quiz/adaptive/start \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"topic_id": 1}')
echo "$START_RESP" | jq .

ATTEMPT_ID=$(echo "$START_RESP" | jq -r .attempt_id)
QUESTION_ID=$(echo "$START_RESP" | jq -r .question.question_id)
```

### Step 3: Answer Step 1 Question
```bash
ANSWER_RESP=$(curl -s -X POST "http://localhost:8000/api/quiz/adaptive/${ATTEMPT_ID}/answer" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"question_id\": ${QUESTION_ID}, \"selected_answer\": \"A\"}")
echo "$ANSWER_RESP" | jq .
```

### Step 4: Complete the Remaining Steps
For each subsequent step until `finished == true`:
```bash
NEXT_QID=$(echo "$ANSWER_RESP" | jq -r .next_question.question_id)

ANSWER_RESP=$(curl -s -X POST "http://localhost:8000/api/quiz/adaptive/${ATTEMPT_ID}/answer" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"question_id\": ${NEXT_QID}, \"selected_answer\": \"B\"}")
echo "$ANSWER_RESP" | jq .
```

### Step 5: Verify the Audit Trail in PostgreSQL
Inspect the progression, difficulty shifts, and posterior updates stored in `adaptive_quiz_steps`:
```sql
SELECT step_number, question_id, target_difficulty, served_difficulty, 
       selection_reason, ROUND(mastery_before::numeric, 4) AS p_before, 
       ROUND(mastery_after::numeric, 4) AS p_after, selected_answer, is_correct
FROM adaptive_quiz_steps
WHERE attempt_id = <ATTEMPT_ID>
ORDER BY step_number ASC;
```

