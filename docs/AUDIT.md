# LearnWise Project Comprehensive Codebase Audit (Phases 1–4)

**Date:** 2026-10-15  
**Auditor:** Takeover Engineer  
**Scope:** Architecture, Models, Routes, Quiz Engine, Seeding, Security, Handover Validation  
**Current Branch:** `main` (clean working tree, up to date with `origin/main`)

---

## 1. SQLAlchemy Models

The backend uses SQLAlchemy 2.0 with the declarative base located at [`backend/app/database.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/database.py). All models inherit from `Base` and are defined across 7 files in [`backend/app/models/`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/models/).

### 1.1 `User`
- **File:** [`backend/app/models/user.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/models/user.py)
- **Table Name:** `users`
- **Columns:**
  | Column Name | Type | Constraints / Defaults | Description |
  |---|---|---|---|
  | `id` | `Integer` | `primary_key=True`, `index=True` | Unique user ID |
  | `name` | `String(100)` | `nullable=False` | Full name |
  | `email` | `String(255)` | `unique=True`, `nullable=False`, `index=True` | User email address |
  | `password_hash` | `String(255)` | `nullable=False` | Argon2 password hash |
  | `role` | `String(20)` | `nullable=False`, `default="learner"` | Role (`"learner"` or `"instructor"`) |
  | `created_at` | `DateTime(timezone=True)` | `server_default=func.now()` | Timestamp of registration |
- **Foreign Keys:** None
- **Relationships:** None defined (missing back-reference to `QuizAttempt`)

---

### 1.2 `Course`
- **File:** [`backend/app/models/course.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/models/course.py)
- **Table Name:** `courses`
- **Columns:**
  | Column Name | Type | Constraints / Defaults | Description |
  |---|---|---|---|
  | `id` | `Integer` | `primary_key=True`, `index=True` | Unique course ID |
  | `title` | `String(150)` | `nullable=False` | Course title |
  | `description` | `Text` | `nullable=True` | Optional course description |
  | `created_at` | `DateTime(timezone=True)` | `server_default=func.now()` | Creation timestamp |
- **Foreign Keys:** None
- **Relationships:**
  - `topics`: `relationship("Topic", back_populates="course", cascade="all, delete-orphan")`
  - *(Missing relationships to `QuizAttempt` and indirect questions)*

---

### 1.3 `Topic`
- **File:** [`backend/app/models/topic.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/models/topic.py)
- **Table Name:** `topics`
- **Columns:**
  | Column Name | Type | Constraints / Defaults | Description |
  |---|---|---|---|
  | `id` | `Integer` | `primary_key=True`, `index=True` | Unique topic ID |
  | `course_id` | `Integer` | `ForeignKey("courses.id", ondelete="CASCADE")`, `nullable=False` | Parent course reference |
  | `title` | `String(150)` | `nullable=False` | Topic title |
  | `description` | `Text` | `nullable=True` | Optional topic description |
  | `order` | `Integer` | `nullable=False`, `default=1` | Display order sequence |
- **Foreign Keys:**
  - `courses.id` on `course_id` with `ON DELETE CASCADE`
- **Relationships:**
  - `course`: `relationship("Course", back_populates="topics")`
  - `resources`: `relationship("LearningResource", back_populates="topic", cascade="all, delete-orphan")`
  - `questions`: `relationship("Question", back_populates="topic", cascade="all, delete-orphan")`
  - `responses`: `relationship("QuizResponse", back_populates="topic")`

---

### 1.4 `LearningResource`
- **File:** [`backend/app/models/learningresource.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/models/learningresource.py)
- **Table Name:** `learning_resources`
- **Columns:**
  | Column Name | Type | Constraints / Defaults | Description |
  |---|---|---|---|
  | `id` | `Integer` | `primary_key=True`, `index=True` | Unique resource ID |
  | `topic_id` | `Integer` | `ForeignKey("topics.id", ondelete="CASCADE")`, `nullable=False` | Parent topic reference |
  | `title` | `String(200)` | `nullable=False` | Resource title |
  | `description` | `Text` | `nullable=True` | Optional resource description |
  | `resource_type` | `String(50)` | `nullable=False` | Type of resource (e.g. video, article) |
  | `url` | `String(255)` | `nullable=False` | Resource link/URL |
  | `order` | `Integer` | `nullable=False`, `default=1` | Ordering index within topic |
- **Foreign Keys:**
  - `topics.id` on `topic_id` with `ON DELETE CASCADE`
- **Relationships:**
  - `topic`: `relationship("Topic", back_populates="resources")`

---

### 1.5 `Question`
- **File:** [`backend/app/models/question.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/models/question.py)
- **Table Name:** `questions`
- **Columns:**
  | Column Name | Type | Constraints / Defaults | Description |
  |---|---|---|---|
  | `id` | `Integer` | `primary_key=True`, `index=True` | Unique question ID |
  | `topic_id` | `Integer` | `ForeignKey("topics.id", ondelete="CASCADE")`, `nullable=False` | Linked topic ID |
  | `question_text` | `Text` | `nullable=False` | The question prompt text |
  | `option_a` | `String(500)` | `nullable=False` | Choice A |
  | `option_b` | `String(500)` | `nullable=False` | Choice B |
  | `option_c` | `String(500)` | `nullable=False` | Choice C |
  | `option_d` | `String(500)` | `nullable=False` | Choice D |
  | `correct_answer` | `String(1)` | `nullable=False` | Correct option letter ('A', 'B', 'C', 'D') |
  | `difficulty` | `String(20)` | `nullable=False`, `default="Medium"` | Difficulty level |
- **Foreign Keys:**
  - `topics.id` on `topic_id` with `ON DELETE CASCADE`
- **Relationships:**
  - `topic`: `relationship("Topic", back_populates="questions")`
  - `responses`: `relationship("QuizResponse", back_populates="question")`

---

### 1.6 `QuizAttempt`
- **File:** [`backend/app/models/quiz_attempt.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/models/quiz_attempt.py)
- **Table Name:** `quiz_attempts`
- **Columns:**
  | Column Name | Type | Constraints / Defaults | Description |
  |---|---|---|---|
  | `id` | `Integer` | `primary_key=True`, `index=True` | Unique attempt ID |
  | `user_id` | `Integer` | `ForeignKey("users.id", ondelete="CASCADE")`, `nullable=False` | User who took the quiz |
  | `course_id` | `Integer` | `ForeignKey("courses.id", ondelete="CASCADE")`, `nullable=False` | Evaluated course |
  | `quiz_type` | `String(20)` | `nullable=False`, `default="INITIAL"` | Quiz stage (e.g. "INITIAL") |
  | `score` | `Integer` | `nullable=False` | Number of correct answers |
  | `total_questions` | `Integer` | `nullable=False` | Total questions attempted |
  | `started_at` | `DateTime(timezone=True)` | `server_default=func.now()` | Start timestamp |
  | `completed_at` | `DateTime(timezone=True)` | `server_default=func.now()` | Completion timestamp (defaults to creation time) |
- **Foreign Keys:**
  - `users.id` on `user_id` with `ON DELETE CASCADE`
  - `courses.id` on `course_id` with `ON DELETE CASCADE`
- **Relationships:**
  - `responses`: `relationship("QuizResponse", back_populates="attempt", cascade="all, delete-orphan")`
  - *(Missing `relationship("User")` and `relationship("Course")`)*

---

### 1.7 `QuizResponse`
- **File:** [`backend/app/models/quiz_response.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/models/quiz_response.py)
- **Table Name:** `quiz_responses`
- **Columns:**
  | Column Name | Type | Constraints / Defaults | Description |
  |---|---|---|---|
  | `id` | `Integer` | `primary_key=True`, `index=True` | Unique response record ID |
  | `attempt_id` | `Integer` | `ForeignKey("quiz_attempts.id", ondelete="CASCADE")`, `nullable=False` | Parent attempt reference |
  | `question_id` | `Integer` | `ForeignKey("questions.id", ondelete="CASCADE")`, `nullable=False` | Question reference |
  | `topic_id` | `Integer` | `ForeignKey("topics.id", ondelete="CASCADE")`, `nullable=False` | Topic reference |
  | `selected_answer` | `String(1)` | `nullable=False` | Selected choice ('A', 'B', 'C', 'D') |
  | `is_correct` | `Boolean` | `nullable=False` | Boolean correctness result |
- **Foreign Keys:**
  - `quiz_attempts.id` on `attempt_id` with `ON DELETE CASCADE`
  - `questions.id` on `question_id` with `ON DELETE CASCADE`
  - `topics.id` on `topic_id` with `ON DELETE CASCADE`
- **Relationships:**
  - `attempt`: `relationship("QuizAttempt", back_populates="responses")`
  - `question`: `relationship("Question", back_populates="responses")`
  - `topic`: `relationship("Topic", back_populates="responses")`

---

## 2. API Routes Matrix

All routes registered on the FastAPI application in [`backend/app/main.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/main.py):

| Method | Path | Auth Required? | Role / Guard | Handler Function | File | Notes / Issues |
|---|---|---|---|---|---|---|
| `GET` | `/` | **No** | None | `root` | `main.py` | Welcome payload |
| `GET` | `/health` | **No** | None | `health_check` | `main.py` | Pings database via `SELECT 1` |
| `POST` | `/api/auth/register` | **No** | None | `register` | `routes/auth.py` | Creates user; returns status 201 |
| `POST` | `/api/auth/login` | **No** | None | `login` | `routes/auth.py` | Verifies password; returns Bearer JWT |
| `GET` | `/api/auth/me` | **YES** | Bearer Token (`get_current_user`) | `get_me` | `routes/auth.py` | **Only protected endpoint in app** |
| `POST` | `/api/courses/` | **No** | None | `create_course` | `routes/course.py` | Unprotected course creation |
| `GET` | `/api/courses/` | **No** | None | `get_courses` | `routes/course.py` | Lists all courses |
| `GET` | `/api/courses/{course_id}` | **No** | None | `get_course` | `routes/course.py` | Retrieves single course by ID |
| `POST` | `/api/courses/{course_id}/topics/` | **No** | None | `create_topic` | `routes/topic.py` | Unprotected topic creation |
| `GET` | `/api/courses/{course_id}/topics/` | **No** | None | `get_topics` | `routes/topic.py` | Lists topics for a course |
| `GET` | `/api/courses/{course_id}/topics/{topic_id}` | **No** | None | `get_topic` | `routes/topic.py` | Retrieves single topic |
| `POST` | `/api/courses/{course_id}/topics/{topic_id}/resources/` | **No** | None | `create_resource` | `routes/learningresource.py` | Unprotected resource creation |
| `GET` | `/api/courses/{course_id}/topics/{topic_id}/resources/` | **No** | None | `get_resources` | `routes/learningresource.py` | Lists resources ordered by `order` |
| `GET` | `/api/courses/{course_id}/topics/{topic_id}/resources/{resource_id}` | **No** | None | `get_resource` | `routes/learningresource.py` | Retrieves single resource |
| `POST` | `/quiz/generate/course/{course_id}` | **No** | None | `generate_course_quiz` | `routes/quiz.py` | Route lacks `/api` prefix |
| `POST` | `/quiz/submit` | **No** | None | `submit_quiz` | `routes/quiz.py` | Route lacks `/api` prefix; hardcodes user ID 1 |

> [!WARNING]
> Only 1 endpoint (`/api/auth/me`) has authentication enabled. All administrative mutations (creating courses, adding topics, adding resources) and quiz actions are completely unauthenticated and public. In addition, quiz routes do not conform to the `/api` route prefix convention.

---

## 3. Quiz Generation & Submission Mechanism

Analyzed from [`backend/app/routes/quiz.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/routes/quiz.py):

### 3.1 Quiz Generation (`POST /quiz/generate/course/{course_id}`)
1. **Questions Selected Count:** Exactly **20 questions**.
   - The route checks: `if len(questions) < 20: raise HTTPException(400, "Not enough questions available for this course")`.
   - If 20 or more exist, it invokes `random.sample(questions, 20)`.
2. **Randomness:** **Yes**, questions are selected randomly via Python's standard `random.sample`.
   - Selection draws from all questions belonging to all topics of the given course.
   - It does *not* enforce equal distribution across topics (e.g., one topic could have 10 questions selected while another has 0).
3. **Data Protection / Omission of Answers:**
   - The response schema `QuizQuestionResponse` returns: `question_id`, `topic_id`, `question_text`, `option_a`, `option_b`, `option_c`, `option_d`.
   - `correct_answer` is strictly omitted from the payload returned to the frontend.

### 3.2 Quiz Submission (`POST /quiz/submit`)
1. **Server-Side Scoring:** **Yes**, answers are evaluated strictly on the backend:
   - Client sends `QuizSubmission` containing `course_id` and list of `QuizAnswer(question_id, selected_answer)`.
   - Backend queries all submitted `question_ids` from the database.
   - For each answer, it converts `selected_answer.upper()` and compares it against `question.correct_answer.upper()`.
   - It tallies `correct_count`, computes `percentage = (correct_count / total_questions) * 100`, records each individual response in `quiz_responses`, and records total score in `quiz_attempts`.
2. **User Linkage:**
   - While the `QuizAttempt` table has a `user_id` column linked via foreign key to `users.id`, the endpoint **hardcodes `user_id = 1`** on line 153:
     ```python
     attempt = QuizAttempt(
         user_id=1,  # temporary until authentication is connected
         course_id=submission.course_id,
         quiz_type="INITIAL",
         score=0,
         total_questions=len(submission.answers)
     )
     ```
   - If user ID `1` does not exist in the database (e.g., in a newly spun up instance), submitting a quiz will fail with a foreign key constraint violation (`psycopg2.errors.ForeignKeyViolation`).
3. **Question Linkage (Topic vs Course):**
   - Questions are linked **strictly to a `topic_id`**, NOT directly to a `course_id`.
   - In `Question`, the column is `topic_id = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)`.
   - Course association is indirect: `Question -> Topic -> Course`.
   - When generating quizzes, the route queries `Topic` by `course_id`, extracts topic IDs, and queries `Question.topic_id.in_(topic_ids)`.
   - When storing responses, `QuizResponse` records `topic_id=question.topic_id`.

---

## 4. Seed Scripts & Idempotency Analysis

Two seed scripts are located in `backend/app/`:

### 4.1 `backend/app/seed_courses_topics.py`
- **Purpose:** Associates predefined topics with courses ("Computer Networks", "OOPS", "SQL/DBMS", "Operating Systems").
- **Flaw (Missing Course Creation):** Lines 45–52 query `db.query(Course).filter(Course.title == course_title).first()`. If the course does not exist, it prints `"Course not found"` and skips it! **It does NOT create the course.** On an empty database, this script executes and inserts 0 topics.
- **Idempotency & Destructive Behavior:**
  - For each course found, it executes:
    ```python
    db.query(Topic).filter(Topic.course_id == course.id).delete()
    ```
  - **Not safely idempotent:** While it does not duplicate rows (because it deletes first), it is **destructive**. Due to `ondelete="CASCADE"`, deleting topics wipes all existing `learning_resources`, `questions`, and `quiz_responses` attached to those topics. In addition, primary keys (`Topic.id`) are permanently incremented on re-run.

### 4.2 `backend/app/seed_questions.py`
- **Purpose:** Seeds 480 questions from [`backend/app/question_bank.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/question_bank.py) (20 questions per topic across 24 topics).
- **Idempotency Check:**
  - Lines 13–21 check:
    ```python
    existing_count = db.query(Question).count()
    if existing_count > 0:
        print(f"Questions table already contains {existing_count} questions.")
        print("No new questions were inserted.")
        return
    ```
  - **Safe to re-run:** It is idempotent in that re-running it when questions exist terminates early and does not duplicate rows.
  - **Fragility:** If run against a clean database where courses or topics have not yet been inserted, it raises an unhandled exception: `Exception("Course not found: ...")` or `Exception("Topic not found: ...")`.

### 4.3 Missing Seed Scripts
- **No seed script exists for `Course` records.** Courses must either be manually inserted via SQL or via `POST /api/courses/` before any seed script can function.
- **No seed script exists for `LearningResource` records.**
- **No seed script exists for creating an initial test `User` (specifically user `id=1`), which is required by `quiz.py`.**

---

## 5. Environment Variable & Secret Handling

### 5.1 `DATABASE_URL` Handling
- **File:** [`backend/app/database.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/database.py)
  ```python
  load_dotenv()
  DATABASE_URL = os.getenv("DATABASE_URL")
  engine = create_engine(DATABASE_URL)
  ```
- **Audit Result:** **Unsafe.** If `DATABASE_URL` is omitted from the environment, `os.getenv` returns `None`. SQLAlchemy's `create_engine(None)` fails with an obscure `ArgumentError: Could not parse SQLAlchemy URL from string ''`. There is no explicit fail-fast check or helpful error message notifying the developer that `DATABASE_URL` must be set.

### 5.2 `JWT_SECRET_KEY` Handling
- **File:** [`backend/app/utils/jwt.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/utils/jwt.py)
  ```python
  load_dotenv()
  JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
  JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
  print("JWT SECRET LOADED:", JWT_SECRET_KEY)
  ```
- **Audit Result:** **Unsafe and Security Defect.**
  1. **Does not fail loudly on startup:** If `JWT_SECRET_KEY` is missing, it evaluates to `None`. The server boots without errors and prints `JWT SECRET LOADED: None`. It only fails at runtime when a user hits `/api/auth/login` or `/api/auth/me`.
  2. **Security Vulnerability (Secret Leak):** Line 12 prints the raw secret key directly to standard output / console logs on every startup or reload.

---

## 6. Hardcoded Secrets, Localhost URLs, and Unwanted Files

1. **Plaintext Credentials in `docker-compose.yml`:**
   [`docker-compose.yml`](file:///Users/avnigoel/Desktop/Learnwise/docker-compose.yml) hardcodes:
   - `POSTGRES_DB: learnwise`
   - `POSTGRES_USER: learnwise_user`
   - `POSTGRES_PASSWORD: learnwise_password`
2. **Port Mapping Discrepancy in `docker-compose.yml`:**
   - Docker configuration specifies `ports: - "5433:5432"`.
   - The PostgreSQL service inside the container listens on port 5432, but it is exposed on the host machine at **port 5433**.
   - If a developer assumes standard port 5432 in `DATABASE_URL`, connection will fail.
3. **Hardcoded User ID in Quiz Submission:**
   - [`backend/app/routes/quiz.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/routes/quiz.py) line 153 hardcodes `user_id=1`.
4. **Binary / Corrupt File in Git: Root `requirements.txt`:**
   - The root [`requirements.txt`](file:///Users/avnigoel/Desktop/Learnwise/requirements.txt) was generated via a Windows PowerShell pipe (`pip freeze > requirements.txt`), producing a UTF-16LE encoded file with CRLF terminators.
   - Git committed it as a **binary file** (`Bin 0 -> 664 bytes`).
   - Furthermore, it is out of date compared to [`backend/requirements.txt`](file:///Users/avnigoel/Desktop/Learnwise/backend/requirements.txt), missing `argon2-cffi`, `PyJWT`, and `email_validator`.
5. **Missing `.env.example` / Template:**
   - `.gitignore` ignores `.env` and `backend/.env`. However, no `.env.example` file was ever committed to document the required environment variables.
6. **Missing CORS Configuration:**
   - [`backend/app/main.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/main.py) does not install FastAPI `CORSMiddleware`. As a result, the Vite frontend running on `http://localhost:5173` cannot communicate with the backend on `http://localhost:8000` due to browser CORS restrictions.
7. **Empty Root `README.md`:**
   - [`README.md`](file:///Users/avnigoel/Desktop/Learnwise/README.md) is committed as an empty 0-byte file.
8. **Frontend State:**
   - [`frontend/src/App.tsx`](file:///Users/avnigoel/Desktop/Learnwise/frontend/src/App.tsx) remains default Vite starter code. No UI components or API integrations have been built yet for Phases 1–4.

---

## 7. Mismatches Between Models, Handover Claims & Schemas

### 7.1 Handover Documentation Status
- **Missing Documentation:** There are no handover documentation files, architectural design files, or specifications anywhere in the repository. The root directory contained only an empty `README.md`.

### 7.2 `created_at` on `User`
- **Claim vs Reality:**
  - In `backend/app/models/user.py`, the `User` model **does** define `created_at`:
    ```python
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    ```
  - **Schema Mismatch:** In [`backend/app/schemas/user.py`](file:///Users/avnigoel/Desktop/Learnwise/backend/app/schemas/user.py), `created_at` is **omitted from `UserResponse`**:
    ```python
    class UserResponse(BaseModel):
        id: int
        name: str
        email: EmailStr
        role: str
    ```
  - As a result, endpoints returning `UserResponse` (`POST /api/auth/register` and `GET /api/auth/me`) do not serialize `created_at` to the client.

### 7.3 `learning_resources` Column `resource_type`
- **Model Definition:**
  - Defined in `backend/app/models/learningresource.py` as:
    ```python
    resource_type = Column(String(50), nullable=False)
    ```
  - Defined in `backend/app/schemas/learningresource.py` as `resource_type: str`.
- **Mismatches & Observations:**
  - Typical project specifications use the column name `type` rather than `resource_type`, or require an enumerated set (`Enum('video', 'article', 'pdf', 'quiz')`). The current implementation allows arbitrary freeform strings up to 50 characters.
  - The `url` column is restricted to `String(255)`, which may truncate long URLs.

### 7.4 Additional Architectural Mismatches
1. **Pydantic V1 vs V2 Syntax Inconsistency:**
   - `schemas/user.py` uses deprecated Pydantic v1 `class Config: from_attributes = True`.
   - `schemas/course.py`, `schemas/topic.py`, and `schemas/learningresource.py` use Pydantic v2 `model_config = ConfigDict(from_attributes=True)`.
2. **Route Prefix Inconsistency:**
   - Course, topic, and resource routes use the `/api/...` prefix.
   - Quiz routes use `/quiz/...` without `/api`.
3. **Trailing Slash Inconsistency:**
   - `/api/courses/`, `/api/courses/{id}/topics/`, `/api/courses/{id}/topics/{id}/resources/` enforce trailing slashes.
   - `/api/auth/register`, `/api/auth/login`, `/api/auth/me`, `/quiz/generate/course/{course_id}`, `/quiz/submit` do not use trailing slashes.
4. **`QuizAttempt.completed_at` Premature Default:**
   - `QuizAttempt` sets `completed_at = Column(DateTime(timezone=True), server_default=func.now())`. This marks every attempt as completed at the exact second it is started, rather than leaving it `nullable=True` until submission.
5. **Missing Relational Mappings:**
   - `User` has no `quiz_attempts` relationship.
   - `Course` has no `quiz_attempts` relationship.
   - `QuizAttempt` has foreign keys to `users.id` and `courses.id`, but defines no SQLAlchemy `relationship` attributes to either parent model.
