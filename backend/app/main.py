from app.routes import auth
from app.database import Base, engine
from app.models import user
from app.models.course import Course
from app.models.topic import Topic
from app.models.learningresource import LearningResource
from app.routes.course import router as course_router
from app.routes.topic import router as topic_router
from app.routes.learningresource import router as learningresource_router
from app.models.question import Question
from app.routes.quiz import router as quiz_router
from app.routes.mastery import router as mastery_router
from app.routes.recommendations import router as recommendations_router
from app.routes.dashboard import router as dashboard_router
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

app = FastAPI(
    title="LearnWise API",
    description="AI-Based Personalized Learning Path Recommendation and Adaptive Assessment System",
    version="1.0.0"
)

cors_origins_env = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173"
)
origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(course_router)
app.include_router(topic_router)
app.include_router(learningresource_router)
app.include_router(quiz_router)
app.include_router(mastery_router)
app.include_router(recommendations_router)
app.include_router(dashboard_router)


@app.get("/")
def root():
    return {
        "message": "Welcome to LearnWise API"
    }


@app.get("/health")
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected"
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e)
        }