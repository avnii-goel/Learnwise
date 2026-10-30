# LearnWise

**AI-Based Personalized Learning Path Recommendation & Adaptive Assessment System**

LearnWise is a full-stack learning platform designed to assess learner competencies and deliver personalized learning pathways. It features JWT-based role authentication, hierarchical course/topic structures, curated learning resources, dynamic quiz generation, and server-side assessment.

---

## Tech Stack

- **Backend:** [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy 2.0](https://www.sqlalchemy.org/), [Pydantic v2](https://docs.pydantic.dev/), [Argon2-cffi](https://argon2-cffi.readthedocs.io/), [PyJWT](https://pyjwt.readthedocs.io/)
- **Frontend:** [React 19](https://react.dev/), [TypeScript](https://www.typescriptlang.org/), [Vite](https://vite.dev/)
- **Database & Infrastructure:** [PostgreSQL](https://www.postgresql.org/) (hosted on Supabase Cloud), [Docker Compose](https://docs.docker.com/compose/) (optional for local development)

---

## macOS Setup & Running Locally

### Prerequisites
- macOS with **Python 3.10+** (verify with `python3 --version`)
- Node.js 18+ (for frontend)
- Git

### 1. Backend Setup

All backend commands should be run from the `backend/` directory:

```zsh
cd backend
```

#### Step 1: Create and Activate Virtual Environment
Make sure you use Python 3.10 or higher:
```zsh
python3 -m venv venv
source venv/bin/activate
```

#### Step 2: Install Dependencies
```zsh
pip install --upgrade pip
pip install -r requirements.txt
```

#### Step 3: Configure Environment Variables
Copy the template `.env.example` to `.env`:
```zsh
cp .env.example .env
```
Edit `backend/.env` with your actual credentials:
- **`DATABASE_URL`**: Your Supabase Session pooler connection string. Ensure special characters in passwords are URL-encoded.
- **`JWT_SECRET_KEY`**: A secure 32+ character key (generate with `openssl rand -hex 32`).
- **`JWT_ALGORITHM`**: Defaults to `HS256`.
- **`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`**: Token expiration in minutes (e.g. `60`).
- **`CORS_ORIGINS`**: Frontend URLs, e.g. `http://localhost:5173,http://127.0.0.1:5173`.
- **`INSTRUCTOR_INVITE_CODE`**: Required code to register instructor accounts.

#### Step 4: Run the Backend Server
From within the `backend/` directory with the virtual environment activated:
```zsh
uvicorn app.main:app --reload --port 8000
```
- Interactive API Docs (Swagger): [http://localhost:8000/docs](http://localhost:8000/docs)
- Health Check: [http://localhost:8000/health](http://localhost:8000/health)

---

## Database & Seeding

All database migrations are managed with **Alembic**, and initial course/topic/question data is seeded via idempotent scripts.

### 1. Apply Migrations
From the `backend/` directory with your virtual environment activated:
```zsh
alembic upgrade head
```

### 2. Seed Initial Data
Run the idempotent seed script to populate courses, topics, and questions (safe to re-run at any time without duplicating rows):
```zsh
python -m app.seeds.seed_all
```

### 3. Creating a New Migration (Teammate Workflow)
When adding or updating SQLAlchemy models in `app/models/`:
1. Modify your SQLAlchemy models.
2. Autogenerate a new migration script:
   ```zsh
   alembic revision --autogenerate -m "describe_your_changes"
   ```
3. Review the generated file in `alembic/versions/` to verify constraints, indexes, and column types.
4. Apply the migration to your database:
   ```zsh
   alembic upgrade head
   ```
5. Commit the new revision file in `alembic/versions/` so teammates can apply it via `alembic upgrade head`.

---

## Knowledge Model & Competency Tracking (Phase 5)

LearnWise incorporates a Bayesian Knowledge Tracing (BKT) engine that models learner mastery per topic dynamically as quizzes are completed:

- **BKT Parameter Matrix:** Prior $P(\text{Init}) = 0.30$, Transition $P(\text{Transit}) = 0.10$, bounded by $[\text{MIN\_P}=0.01, \text{MAX\_P}=0.99]$. Slip and guess rates are calibrated per question difficulty:
  - **Easy:** Slip $s = 0.05$, Guess $g = 0.30$
  - **Medium:** Slip $s = 0.10$, Guess $g = 0.25$
  - **Hard:** Slip $s = 0.15$, Guess $g = 0.20$
- **Dynamic Competency Classification:** Topics are dynamically classified on read (never stored) into four mutually exclusive statuses:
  - `not_attempted`: $\text{total\_answers} == 0$ (including unrecorded topics)
  - `weak`: $\text{total\_answers} > 0$ and $p < 0.40$
  - `developing`: $0.40 \le p < 0.80$, or ($p \ge 0.80$ with $\text{total\_answers} < 3$)
  - `strong`: $p \ge 0.80$ and $\text{total\_answers} \ge 3$
- **Transactional Persistence:** Live quiz submissions (`POST /api/quiz/submit`) atomically calculate BKT progression and persist updates to `topic_mastery` and audit ledgers in `topic_mastery_history` using pessimistic row locking (`SELECT FOR UPDATE`).
- **Learner Mastery Endpoints (`/api/mastery`):**
  - `GET /api/mastery/me`: Global mastery status of all topics across all courses (single joined query).
  - `GET /api/mastery/me/courses/{course_id}`: Course summary with status counts, average mastery over attempted topics, and topic breakdown (single joined query).
  - `GET /api/mastery/me/topics/{topic_id}`: Single topic status with chronological progression history (`created_at ASC`, oldest first).
- **Personalized Recommendations Endpoints (`/api/recommendations`):**
  - `POST /api/recommendations/me`: Generates personalized learning resource recommendations for the authenticated learner using hybrid or content-only strategy, audit logging impressions to `recommendation_impressions`.
  - `POST /api/recommendations/impressions/{impression_id}/click`: Records learner engagement click idempotently against an impression.
- **Historical Backfill Script:**
  To replay pre-existing quiz attempts into the mastery tables:
  ```zsh
  # Dry-run simulation (rolls back transaction, zero writes)
  python -m app.seeds.backfill_mastery --dry-run

  # Execute backfill for users without existing mastery records
  python -m app.seeds.backfill_mastery

  # Atomic wipe & rebuild for a specific user ID
  python -m app.seeds.backfill_mastery --rebuild-user <user_id>
  ```
- **Synthetic Learner Population Generator:**
  Generates deterministic synthetic learners across 5 structured archetypes (Groups A–E) using an independent 3PL IRT logistic response model ($P(\text{correct}) = 0.25 + 0.75 \cdot \sigma(4(\theta - b))$) for demonstration, collaborative filtering, and A/B evaluation:
  ```zsh
  # Dry run (rolls back transaction, zero writes)
  SYNTHETIC_PASSWORD="YourPasswordHere" python -m app.seeds.seed_synthetic_learners --dry-run

  # Seed 50 synthetic learners (default)
  SYNTHETIC_PASSWORD="YourPasswordHere" python -m app.seeds.seed_synthetic_learners

  # Seed a custom number of learners (e.g., 20)
  SYNTHETIC_PASSWORD="YourPasswordHere" python -m app.seeds.seed_synthetic_learners --learners 20

  # Reset/delete all synthetic learners (@synthetic.learnwise.test) safely
  python -m app.seeds.seed_synthetic_learners --reset-synthetic --yes
  ```
  *(Note: This synthetic data demonstrates pipeline integrity and provides latent structure for collaborative filtering; it does not represent real pedagogical learning gains).*

---

## Database Configuration & Docker

- **Shared Cloud Database:** The primary database for LearnWise is a shared cloud PostgreSQL database hosted on **Supabase**. Connections should use the Supabase Session pooler connection string on port 5432 or 6543.
- **Row Level Security (RLS):** All application tables have RLS enabled. The FastAPI backend connects as the database owner, ensuring uninterrupted operations while preventing unauthorized direct access through Supabase's auto-generated REST/GraphQL APIs.
- **Docker Compose (Optional):** The `docker-compose.yml` file in the root directory is strictly **optional for local-only offline experiments**. If you choose to run local Postgres via `docker compose up -d`, note that it maps container port 5432 to host port **5433** (`postgresql://learnwise_user:learnwise_password@localhost:5433/learnwise`).

---

## Testing

The test suite runs with **pytest** and **FastAPI TestClient**.

### Test Database Safety Guarantee
Tests **never** run against the shared Supabase database. The test harness strictly checks that `TEST_DATABASE_URL` is set, is not identical to `DATABASE_URL`, and does not point to `supabase.com`. If any safety condition fails, the test suite aborts immediately.

### Running Tests Locally

1. **Start the local test database via Docker:**
   ```zsh
   docker compose up -d
   ```
   *(Local Postgres runs on host port 5433).*

2. **Ensure `TEST_DATABASE_URL` is set in `backend/.env`:**
   ```env
   TEST_DATABASE_URL=postgresql+psycopg2://learnwise_user:learnwise_password@localhost:5433/learnwise_test
   ```

3. **Run the test suite from `backend/`:**
   ```zsh
   cd backend
   pytest -v
   ```
   *(The test suite automatically applies all Alembic migrations to the test database and seeds baseline courses, topics, and questions before running tests).*
