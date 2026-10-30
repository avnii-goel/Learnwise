from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class ResourceDetail(BaseModel):
    id: int
    title: str
    description: str | None = None
    resource_type: str
    url: str
    difficulty: str

    model_config = ConfigDict(from_attributes=True)


class TopicDetail(BaseModel):
    id: int
    title: str

    model_config = ConfigDict(from_attributes=True)


class RecommendationComponents(BaseModel):
    need: float
    semantic: float
    difficulty_fit: float
    collaborative: float

    model_config = ConfigDict(from_attributes=True)


class RecommendationItemResponse(BaseModel):
    impression_id: int
    rank: int
    resource: ResourceDetail
    topic: TopicDetail
    score: float
    mastery: float | None = None
    status: str
    reason: str
    components: RecommendationComponents

    model_config = ConfigDict(from_attributes=True)


class RecommendationResponse(BaseModel):
    request_id: UUID
    strategy: str
    collaborative_available: bool
    items: list[RecommendationItemResponse]

    model_config = ConfigDict(from_attributes=True)


class ImpressionClickResponse(BaseModel):
    impression_id: int
    resource_url: str
    clicked_at: datetime

    model_config = ConfigDict(from_attributes=True)

