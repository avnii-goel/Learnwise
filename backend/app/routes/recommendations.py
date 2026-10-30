"""Recommendations router for LearnWise.

Provides endpoints to generate personalized learning resource recommendations
and capture learner engagement clicks.
Reference: docs/RECOMMENDER.md Section 13.
"""

from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.recommendation_impression import RecommendationImpression
from app.models.user import User
from app.recommender.config import STRATEGIES
from app.recommender.embedding import get_embedder
from app.recommender.service import recommend_for_user
from app.schemas.recommendations import (
    ImpressionClickResponse,
    RecommendationComponents,
    RecommendationItemResponse,
    RecommendationResponse,
    ResourceDetail,
    TopicDetail,
)
from app.utils.dependencies import get_current_user

router = APIRouter(
    prefix="/api/recommendations",
    tags=["Recommendations"]
)


@router.post("/me", response_model=RecommendationResponse)
def get_recommendations_for_me(
    strategy: str = Query("hybrid", description="Recommendation strategy ('hybrid' or 'content_only')"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generates personalized learning resource recommendations for the authenticated learner.

    Logs an impression audit row for each recommended item in a single database transaction.
    """
    if strategy not in STRATEGIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown recommendation strategy '{strategy}'. Supported strategies: {list(STRATEGIES.keys())}"
        )

    # Execute recommendation pipeline (read-only)
    embedder = get_embedder()
    rec_result = recommend_for_user(db, current_user.id, strategy=strategy, embedder=embedder)

    request_id = uuid.uuid4()
    impressions_to_create: list[RecommendationImpression] = []

    for item in rec_result.items:
        imp = RecommendationImpression(
            user_id=current_user.id,
            resource_id=item.resource_id,
            topic_id=item.topic_id,
            request_id=request_id,
            strategy=strategy,
            rank=item.rank,
            score=item.score,
            mastery_at_shown=item.mastery,
            components=item.components,
            reason=item.reason,
            is_synthetic=False,
        )
        impressions_to_create.append(imp)

    if impressions_to_create:
        db.add_all(impressions_to_create)
        db.commit()
        for imp in impressions_to_create:
            db.refresh(imp)

    response_items: list[RecommendationItemResponse] = []
    for item, imp in zip(rec_result.items, impressions_to_create):
        # Resolve topic details from relationship or object
        res_topic = item.resource.topic
        topic_id = res_topic.id if res_topic else item.topic_id
        topic_title = res_topic.title if res_topic else f"Topic {item.topic_id}"

        response_items.append(
            RecommendationItemResponse(
                impression_id=imp.id,
                rank=item.rank,
                resource=ResourceDetail(
                    id=item.resource.id,
                    title=item.resource.title,
                    description=item.resource.description,
                    resource_type=item.resource.resource_type,
                    url=item.resource.url,
                    difficulty=item.resource.difficulty,
                ),
                topic=TopicDetail(
                    id=topic_id,
                    title=topic_title,
                ),
                score=item.score,
                mastery=item.mastery,
                status=item.status,
                reason=item.reason,
                components=RecommendationComponents(**item.components),
            )
        )

    return RecommendationResponse(
        request_id=request_id,
        strategy=strategy,
        collaborative_available=rec_result.collaborative_available,
        items=response_items,
    )


@router.post("/impressions/{impression_id}/click", response_model=ImpressionClickResponse)
def click_impression(
    impression_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Records learner engagement against an existing impression.

    Idempotent: retains the initial click timestamp if already clicked.
    Returns 404 if impression does not exist or belongs to another user.
    """
    imp = (
        db.query(RecommendationImpression)
        .filter(
            RecommendationImpression.id == impression_id,
            RecommendationImpression.user_id == current_user.id
        )
        .first()
    )
    if not imp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Impression not found"
        )

    if imp.clicked_at is None:
        imp.clicked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(imp)

    return ImpressionClickResponse(
        impression_id=imp.id,
        resource_url=imp.resource.url,
        clicked_at=imp.clicked_at,
    )

