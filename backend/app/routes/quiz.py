import random
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.course import Course
from app.models.topic import Topic
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse as QuizResponseModel
from app.models.user import User
from app.schemas.quiz import QuizResponse, QuizQuestionResponse, QuizSubmission, QuizResult
from app.services.mastery import apply_attempt
from app.services.quiz import select_quiz_questions
from app.utils.dependencies import get_current_user

router = APIRouter(
    prefix="/api/quiz",
    tags=["Quiz"]
)

@router.post(
    "/generate/course/{course_id}",
    response_model=QuizResponse
)
def generate_course_quiz(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    course = (
        db.query(Course)
        .filter(Course.id == course_id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )

    # Get all topics for this course
    topics = (
        db.query(Topic)
        .filter(Topic.course_id == course_id)
        .all()
    )

    if not topics:
        raise HTTPException(
            status_code=404,
            detail="No topics found for this course"
        )

    topic_ids = [topic.id for topic in topics]

    # Get all questions belonging to these topics
    questions = (
        db.query(Question)
        .filter(Question.topic_id.in_(topic_ids))
        .all()
    )

    if len(questions) < 20:
        raise HTTPException(
            status_code=400,
            detail="Not enough questions available for this course"
        )

    selected_questions = select_quiz_questions(questions, topic_ids, target_count=20)

    # Prepare response without correct answers
    quiz_questions = []

    for question in selected_questions:

        quiz_questions.append(
            QuizQuestionResponse(
                question_id=question.id,
                topic_id=question.topic_id,
                question_text=question.question_text,
                option_a=question.option_a,
                option_b=question.option_b,
                option_c=question.option_c,
                option_d=question.option_d
            )
        )

    return QuizResponse(
        course_id=course_id,
        questions=quiz_questions
    )

@router.post(
    "/submit",
    response_model=QuizResult
)
def submit_quiz(
    submission: QuizSubmission,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Check that the course exists
    course = (
        db.query(Course)
        .filter(Course.id == submission.course_id)
        .first()
    )

    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )

    # Make sure answers were submitted
    if not submission.answers:
        raise HTTPException(
            status_code=400,
            detail="No answers submitted"
        )

    # Get all submitted question IDs
    question_ids = [
        answer.question_id
        for answer in submission.answers
    ]

    # Reject duplicate question answers in the same submission
    if len(set(question_ids)) != len(question_ids):
        raise HTTPException(
            status_code=400,
            detail="Duplicate questions submitted in quiz attempt"
        )

    # Fetch questions from database
    questions = (
        db.query(Question)
        .filter(Question.id.in_(question_ids))
        .all()
    )

    # Make sure every submitted question exists
    if len(questions) != len(question_ids):
        raise HTTPException(
            status_code=400,
            detail="One or more questions are invalid"
        )

    # Verify all submitted questions belong to topics of this course
    course_topic_ids = {
        t.id for t in db.query(Topic.id).filter(Topic.course_id == submission.course_id).all()
    }
    for question in questions:
        if question.topic_id not in course_topic_ids:
            raise HTTPException(
                status_code=400,
                detail="One or more questions do not belong to the selected course"
            )

    # Map question ID -> question
    question_map = {
        question.id: question
        for question in questions
    }

    correct_count = 0
    responses_in_order = []

    try:
        # Create quiz attempt first
        attempt = QuizAttempt(
            user_id=current_user.id,
            course_id=submission.course_id,
            quiz_type="INITIAL",
            score=0,
            total_questions=len(submission.answers)
        )

        db.add(attempt)
        db.flush()

        # Evaluate each answer
        for answer in submission.answers:
            question = question_map[answer.question_id]

            selected_answer = answer.selected_answer.upper()

            is_correct = (
                selected_answer == question.correct_answer.upper()
            )

            if is_correct:
                correct_count += 1

            response = QuizResponseModel(
                attempt_id=attempt.id,
                question_id=question.id,
                topic_id=question.topic_id,
                selected_answer=selected_answer,
                is_correct=is_correct
            )

            db.add(response)
            responses_in_order.append(response)

        total_questions = len(submission.answers)
        incorrect_count = total_questions - correct_count

        percentage = (
            correct_count / total_questions
        ) * 100

        # Update final score
        attempt.score = correct_count
        db.flush()

        # Apply BKT topic mastery update inside the same transaction
        apply_attempt(db, current_user.id, attempt, responses_in_order)

        db.commit()
        db.refresh(attempt)
    except Exception:
        db.rollback()
        raise

    return QuizResult(
        attempt_id=attempt.id,
        course_id=submission.course_id,
        score=correct_count,
        total_questions=total_questions,
        percentage=round(percentage, 2),
        correct_answers=correct_count,
        incorrect_answers=incorrect_count
    )