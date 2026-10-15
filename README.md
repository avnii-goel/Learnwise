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

## Database Configuration & Docker

- **Shared Cloud Database:** The primary database for LearnWise is a shared cloud PostgreSQL database hosted on **Supabase**. Connections should use the Supabase Session pooler connection string on port 5432 or 6543.
- **Row Level Security (RLS):** All application tables have RLS enabled. The FastAPI backend connects as the database owner, ensuring uninterrupted operations while preventing unauthorized direct access through Supabase's auto-generated REST/GraphQL APIs.
- **Docker Compose (Optional):** The `docker-compose.yml` file in the root directory is strictly **optional for local-only offline experiments**. If you choose to run local Postgres via `docker compose up -d`, note that it maps container port 5432 to host port **5433** (`postgresql://learnwise_user:learnwise_password@localhost:5433/learnwise`).

---

## Testing

With the backend virtual environment activated:
```zsh
pytest
```
