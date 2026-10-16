from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.course import Course
from app.models.user import User
from app.schemas.course import CourseCreate, CourseResponse
from app.utils.dependencies import get_current_user, require_role

router = APIRouter(
    prefix="/api/courses",
    tags=["Courses"]
)

@router.post("/", response_model=CourseResponse)
def create_course(
    course: CourseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("instructor"))
):
    new_course = Course(
        title = course.title,
        description = course.description
    )
    db.add(new_course)
    db.commit()
    db.refresh(new_course)
    return new_course

@router.get("/", response_model=list[CourseResponse])
def get_courses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    courses = db.query(Course).all()
    return courses

@router.get("/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=404, 
            detail="Course not found"
        )
    return course