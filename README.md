# LearnWise

**AI-Based Personalized Learning Path Recommendation & Adaptive Assessment System**

LearnWise is an AI-powered personalized learning and adaptive assessment platform that models student knowledge in real time. It pairs Bayesian Knowledge Tracing (BKT) and hybrid resource recommendations with single-topic adaptive quizzing and cohort-wide analytics dashboards. The system delivers personalized learning pathways for students while providing instructors with actionable cohort competency insights.

---

## Tech Stack

- **Backend:** [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy 2.0](https://www.sqlalchemy.org/), [Pydantic v2](https://docs.pydantic.dev/), [Argon2-cffi](https://argon2-cffi.readthedocs.io/), [PyJWT](https://pyjwt.readthedocs.io/), [pgvector](https://github.com/pgvector/pgvector-python)
- **Frontend:** [React 19](https://react.dev/), [TypeScript](https://www.typescriptlang.org/) (strict mode), [Vite](https://vite.dev/), [React Router v7](https://reactrouter.com/), [Recharts](https://recharts.org/)
- **Database & Infrastructure:** [PostgreSQL 16](https://www.postgresql.org/) (hosted on Supabase Cloud with Row Level Security; local test DB on port 5433 via Docker Compose)

---

## Repository Layout

```
Learnwise/
├── backend/
│   ├── alembic/              # Database migration versions and env configuration
│   ├── app/
│   │   ├── models/           # SQLAlchemy declarative ORM models
│   │   ├── routes/           # FastAPI REST API route endpoints
│   │   ├── schemas/          # Pydantic v2 request and response schemas
│   │   ├── seeds/            # Idempotent data seeding & synthetic learner generator
│   │   ├── services/         # Business logic: BKT, adaptive quiz, recommender, dashboards
│   │   └── utils/            # JWT auth, dependencies, password hashing
│   ├── tests/                # Pytest test suite (179 tests, runs on local test DB)
│   └── requirements.txt      # Python backend dependencies
├── frontend/
│   ├── src/
│   │   ├── api/              # API fetch client and strict TypeScript types
│   │   ├── auth/             # React AuthContext, token management, session state
│   │   ├── components/       # Layout, header, navigation, and role route guards
│   │   ├── lib/              # Pure formatting and data mapping helpers
│   │   ├── pages/            # LearnerDashboard, InstructorDashboard, quiz runners, Login
│   │   └── test/             # Vitest + React Testing Library test suite (23 tests)
│   └── package.json          # Node dependencies and build scripts
├── docs/                     # Technical specifications and architectural references
│   ├── KNOWLEDGE_MODEL.md    # BKT mathematical specification and data architecture
│   ├── ADAPTIVE_QUIZ.md      # Adaptive assessment engine specification
│   ├── RECOMMENDER.md        # Hybrid recommendation system specification
│   └── DASHBOARDS.md         # Dashboards, metrics, worked examples, and demo guide
├── scripts/                  # Data ingestion, embedding, simulation, and verification scripts
│   └── verify_phase8.py      # Read-only Supabase database verification script
└── docker-compose.yml        # Local isolated test PostgreSQL container configuration
```

---

## Getting Started & Local Setup

### Prerequisites
- macOS or Linux with **Python 3.10+**
- **Node.js 18+** & **npm**
- **Docker** (for local test database)

---

### 1. Backend Setup

All backend commands run from the `backend/` directory:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

#### Environment Configuration
Copy the template `.env.example` to `backend/.env`:

```bash
cp .env.example .env
```

Configure `backend/.env` with your environment variables (see `.env.example` for details; **use placeholders only; never commit real credentials**):

```env
DATABASE_URL=<DATABASE_URL>
TEST_DATABASE_URL=<TEST_DATABASE_URL>
JWT_KEY=<JWT_SIGNING_KEY>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
INSTRUCTOR_INVITE_CODE=<INSTRUCTOR_INVITE_CODE>
SYNTHETIC_PASSWORD=<SYNTHETIC_PASSWORD>
```

#### Apply Database Migrations & Seed Baseline Data
```bash
alembic upgrade head
python -m app.seeds.seed_all
```

#### Run Backend Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- Interactive Swagger API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health Check: [http://localhost:8000/health](http://localhost:8000/health)

---

### 2. Frontend Setup

All frontend commands run from the `frontend/` directory:

```bash
cd frontend
npm install
```

#### Environment Configuration
Copy `frontend/.env.example` to `frontend/.env`:

```bash
cp .env.example .env
```

Ensure the API base URL points to the backend:
```env
VITE_API_BASE_URL=http://localhost:8000
```

#### Run Frontend Dev Server
```bash
npm run dev
```
Open your browser at [http://localhost:5173](http://localhost:5173).

---

## Testing

### Local Test Database Safety Guarantee
Tests **never** run against the shared Supabase cloud database. The pytest test harness enforces that `TEST_DATABASE_URL` is configured, does not match `DATABASE_URL`, and never points to a remote `supabase` domain.

### 1. Run Backend Test Suite (179 tests)
Start the local isolated PostgreSQL test container on port 5433:

```bash
docker compose up -d
cd backend
source venv/bin/activate
pytest -v
```

### 2. Run Frontend Test Suite (23 tests)
```bash
cd frontend
npm run test
npm run typecheck
npm run build
```

---

## Automated Supabase Audit Script (`scripts/verify_phase8.py`)

A standalone, strictly **read-only** verification script is provided to audit live database metrics against independent raw SQL calculations without persisting any changes.

### Running the Audit Script
Run from the repository root:

```bash
source backend/venv/bin/activate
export DATABASE_URL="<SUPABASE_SESSION_POOLER_URL>"
PYTHONPATH=backend python scripts/verify_phase8.py
```

### Safety Guarantee
- Operates under `SET TRANSACTION READ ONLY`.
- Contains zero `INSERT`, `UPDATE`, or `DELETE` statements.
- Never invokes `commit()`, and always issues an explicit `rollback()`.
- Does not automatically read `.env` configuration; requires explicit `DATABASE_URL` in the environment.

### Checks Performed
1. **V1: Total Learners Count:** Validates `GET /api/dashboard/instructor/overview.total_learners` against `SELECT count(*) FROM users WHERE role = 'learner'`.
2. **V2: Cohort Completed Attempts & Quiz Average:** Validates `completed_attempts`, `active_learners`, and `avg_quiz_percentage` against independent SQL aggregates over completed attempts (`qa.status = 'completed'`).
3. **V3: Per-Topic Cohort Metrics:** Checks `learners_attempted`, `avg_mastery`, and question `accuracy_percent` across every topic against `topic_mastery`.
4. **V4: Per-Course Quiz Averages & Attempts:** Checks course-level `avg_quiz_percentage` and `completed_attempts` against SQL grouped by `course_id`.
5. **V5: Instructor Learners Directory:** Checks each learner's `attempted_topics`, `avg_mastery`, `completed_attempts`, and `avg_quiz_percentage` without row fan-out.
6. **V6: Learner Dashboard Consistency:** Asserts that each active learner's `status_counts` (`strong` + `developing` + `weak` + `not_attempted`) sums to total topics dynamically counted from the database, and validates individual progress and mastery against SQL.
7. **V7: Trend vs Overview Alignment (WARN level):** Checks whether the latest cumulative mastery point in `get_learner_trends` aligns with `avg_mastery_attempted` in `get_learner_dashboard_overview`.
8. **V8: Synthetic Learner Archetypes:** Validates archetype separation across synthetic cohorts:
   - Group 01–10 mean mastery exceeds Group 11–20 by $\ge 0.15$.
   - Group 21–30 Systems ("Computer Networks", "Operating Systems") mastery exceeds Apps ("OOPS", "SQL/DBMS") by $\ge 0.15$.
   - Group 31–40 Apps mastery exceeds Systems by $\ge 0.15$.
   *(Skips cleanly with PASS if fewer than 40 synthetic accounts exist in the database).*
9. **V9: Completed Attempts completed_at Integrity (WARN level):** Checks for NULL `completed_at` timestamps on completed quiz attempts to confirm `COALESCE(completed_at, started_at)` query safety.

---

## Project Phases Summary (Phases 1–8)

| Phase | Title | Scope & Highlights |
| :--- | :--- | :--- |
| **Phase 1** | Database & Auth Foundation | User authentication with Argon2 password hashing, JWT bearer tokens, role-based authorization (`learner`, `instructor`), SQLAlchemy declarative models, Alembic migrations. |
| **Phase 2** | Course & Topic Hierarchy | Core CS curriculum structure: 4 courses (Computer Networks, Operating Systems, OOPS, SQL/DBMS), 24 topics, idempotent seeding. |
| **Phase 3** | Resource Repository & Search | 72 curated multi-format, multi-difficulty learning resources, PostgreSQL full-text search, Row Level Security (RLS) enforcement. |
| **Phase 4** | Assessment Engine | Dynamic 20-question course quiz generator, deterministic scoring, answer verification, response ledger persistence. |
| **Phase 5** | Knowledge Model (BKT) | Bayesian Knowledge Tracing engine, calibrated difficulty parameters (easy/medium/hard slip & guess rates), dynamic competency classification (`weak`, `developing`, `strong`), mastery REST APIs, atomic attempt application with row locks, 50 structured synthetic learners across 5 archetypes. |
| **Phase 6** | Adaptive Testing Engine | 8-question single-topic adaptive quizzes, calibrated Dirichlet item selection with target difficulty cutoff, item-level BKT updates, resume idempotency. |
| **Phase 7** | Recommendation Pipeline | Hybrid recommendation system combining collaborative filtering, semantic embeddings (pgvector), and BKT need scoring; impression audit logging and click tracking. |
| **Phase 8** | Dashboards & Frontend | End-to-end React single-page application with role routing, interactive adaptive and fixed quiz runners, learner dashboard (overview, Recharts radar/trends, recommendations panel, history table), instructor dashboard (cohort stats, course comparison, topic mastery, difficult topics, sortable learners directory), and automated verification suite. |

---

## Documentation Pointers

Detailed architectural specifications and mathematical models are maintained in `docs/`:
- [`docs/KNOWLEDGE_MODEL.md`](docs/KNOWLEDGE_MODEL.md): BKT mathematical formulation, parameter matrix, update dynamics, transactional execution, and dynamic status derivation.
- [`docs/ADAPTIVE_QUIZ.md`](docs/ADAPTIVE_QUIZ.md): Single-topic adaptive testing engine, Dirichlet difficulty sampling, and runtime attempt state machine.
- [`docs/RECOMMENDER.md`](docs/RECOMMENDER.md): Multi-strategy recommendation engine, hybrid ranking formula, impression audit logging, and click telemetry.
- [`docs/DASHBOARDS.md`](docs/DASHBOARDS.md): Full Phase 8 specification, metric definitions, worked examples, API schemas, frontend architecture, and live demo guide.

---

## Known Limitations

1. **Recommendation Impression Logging:** Every visit to the learner dashboard dispatches `POST /api/recommendations/me` (guarded to once per mount), generating fresh impression audit rows in `recommendation_impressions`.
2. **Client-Side Token Persistence:** JWT access tokens are stored in browser `localStorage`. This is appropriate for single-page application demonstrations; production environments should transition to `HttpOnly` secure cookies.
3. **Unpaginated Instructor Directory:** The instructor learners table renders all cohort students with client-side sorting, designed for standard cohort sizes (up to ~100 learners). Very large cohorts will require server-side pagination.
4. **Bundle Size:** The production frontend bundle size is approximately 707 kB (~205 kB gzipped) due to the bundled Recharts visualization library. Future iterations can introduce dynamic route code-splitting (`React.lazy`).
5. **Synthetic Learner Data Scope:** Synthetic learner response patterns prove pipeline integrity, mathematical aggregation accuracy, and archetype clustering; they do not assert real human learning gains.
6. **Heuristic Difficult Topic Cutoff:** The threshold of 5 learners (`MIN_LEARNERS_FOR_DIFFICULT = 5`) for difficult topic inclusion is a heuristic cutoff.

---

## Future Scope

The following capabilities are reserved for post-Phase 8 project iterations:
1. **A/B Testing Framework:** Controlled evaluation of single-topic adaptive quizzes versus fixed course quizzes, and hybrid recommendation versus content-only recommendation strategies. (Data hooks are preserved in `quiz_attempts.mode` and `recommendation_impressions.strategy`).
2. **LMS Interoperability:** LTI 1.3 integration with learning management platforms (Canvas, Blackboard, Moodle) for single sign-on and gradebook passback.
3. **Instructor Learner Drill-Down:** Dedicated per-learner deep-dive modal or sub-route allowing instructors to inspect an individual learner's question-by-question timeline and mastery history.
4. **Temporal Mastery Decay:** Integrating Ebbinghaus forgetting curves into BKT to model knowledge decay over prolonged inactivity.
5. **Empirical Parameter Calibration:** Baum-Welch or Expectation-Maximization parameter fitting from live student response telemetry.
