from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.course import Course
from app.models.topic import Topic
from app.models.learningresource import LearningResource
from app.models.user import User
from app.schemas.learningresource import LearningResourceCreate, LearningResourceResponse
from app.utils.dependencies import get_current_user, require_role

router = APIRouter(
    prefix="/api/courses/{course_id}/topics/{topic_id}/resources",
    tags=["Learning Resources"]
)

@router.post("/", response_model=LearningResourceResponse)
def create_resource(
    course_id: int,
    topic_id: int,
    resource: LearningResourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("instructor"))
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )

    topic = db.query(Topic).filter( Topic.id == topic_id, Topic.course_id == course_id).first()
    
    if not topic:
        raise HTTPException(
            status_code=404,
            detail="Topic not found"
        )

    new_resource = LearningResource(
        topic_id=topic_id,
        title=resource.title,
        description=resource.description,
        resource_type=resource.resource_type,
        url=resource.url,
        order=resource.order
    )

    db.add(new_resource)
    db.commit()
    db.refresh(new_resource)
    return new_resource

@router.get("/", response_model=list[LearningResourceResponse])
def get_resources(
    course_id: int,
    topic_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )

    topic = (
        db.query(Topic)
        .filter(Topic.id == topic_id, Topic.course_id == course_id)
        .first()
    )

    if not topic:
        raise HTTPException(
            status_code=404,
            detail="Topic not found"
        )

    resources = (
        db.query(LearningResource)
        .filter(LearningResource.topic_id == topic_id)
        .order_by(LearningResource.order)
        .all()
    )
    return resources

@router.get("/{resource_id}", response_model=LearningResourceResponse)
def get_resource(
    course_id: int,
    topic_id: int,
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )

    topic = (
        db.query(Topic)
        .filter(
            Topic.id == topic_id,
            Topic.course_id == course_id
        )
        .first()
    )

    if not topic:
        raise HTTPException(
            status_code=404,
            detail="Topic not found"
        )

    resource = (
        db.query(LearningResource)
        .filter(
            LearningResource.id == resource_id,
            LearningResource.topic_id == topic_id
        )
        .first()
    )

    if not resource:
        raise HTTPException(
            status_code=404,
            detail="Learning resource not found"
        )
    return resource