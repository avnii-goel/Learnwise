"""Database-backed service operations for single-topic adaptive quizzing.

Reference: docs/ADAPTIVE_QUIZ.md Sections 6, 7, 8, 9.
Handles transactional lifecycle, in-progress resume, step progression, and
atomic mastery updates upon quiz completion.
"""

from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.bkt import P_INIT
from app.models.adaptive_quiz_step import AdaptiveQuizStep
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.schemas.quiz import (
    AdaptiveAnswerResponse,
    AdaptiveQuestionView,
    AdaptiveResultSummary,
    AdaptiveStartResponse,
)
from app.services.adaptive import (
    ADAPTIVE_QUIZ_LENGTH,
    advance_running_mastery,
    choose_next_question,
    target_difficulty,
)
from app.services.bkt import classify
from app.services.mastery import apply_attempt
from app.services.quiz import check_answer_correctness


def start_or_resume_adaptive_quiz(
    db: Session,
    user_id: int,
    topic_id: int,
) -> tuple[AdaptiveStartResponse, int]:
    """Starts a new 8-question adaptive quiz for the specified topic, or resumes an in-progress attempt.

    Returns:
        tuple[AdaptiveStartResponse, int]: The response schema and the HTTP status code (201 or 200).

    Raises:
        HTTPException: 404 if topic missing; 409 if topic has fewer than ADAPTIVE_QUIZ_LENGTH questions.
    """
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topic {topic_id} not found."
        )

    total_questions_count = db.query(Question).filter(Question.topic_id == topic_id).count()
    if total_questions_count < ADAPTIVE_QUIZ_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Topic '{topic.title}' has {total_questions_count} questions, "
                f"but an adaptive quiz requires at least {ADAPTIVE_QUIZ_LENGTH}."
            ),
        )

    # 1. Check for an active in-progress adaptive attempt for this user and topic
    existing_attempt = (
        db.query(QuizAttempt)
        .filter(
            QuizAttempt.user_id == user_id,
            QuizAttempt.topic_id == topic_id,
            QuizAttempt.mode == "adaptive",
            QuizAttempt.status == "in_progress",
        )
        .first()
    )

    if existing_attempt:
        pending_step = (
            db.query(AdaptiveQuizStep)
            .filter(
                AdaptiveQuizStep.attempt_id == existing_attempt.id,
                AdaptiveQuizStep.answered_at.is_(None),
            )
            .order_by(AdaptiveQuizStep.step_number.asc())
            .first()
        )
        if pending_step:
            q = db.query(Question).filter(Question.id == pending_step.question_id).first()
            resp = AdaptiveStartResponse(
                attempt_id=existing_attempt.id,
                topic_id=topic_id,
                mode="adaptive",
                total_questions=ADAPTIVE_QUIZ_LENGTH,
                question_number=pending_step.step_number,
                resumed=True,
                question=AdaptiveQuestionView(
                    question_id=q.id,
                    topic_id=q.topic_id,
                    question_text=q.question_text,
                    option_a=q.option_a,
                    option_b=q.option_b,
                    option_c=q.option_c,
                    option_d=q.option_d,
                ),
            )
            return resp, status.HTTP_200_OK

    # 2. Starting a brand new adaptive attempt
    topic_mastery = (
        db.query(TopicMastery)
        .filter(TopicMastery.user_id == user_id, TopicMastery.topic_id == topic_id)
        .first()
    )
    if topic_mastery and topic_mastery.total_answers > 0:
        current_p = float(topic_mastery.mastery_probability)
    else:
        current_p = P_INIT

    target = target_difficulty(current_p)
    all_questions = db.query(Question).filter(Question.topic_id == topic_id).all()

    # Query questions answered by this learner in earlier attempts of this topic
    earlier_seen = (
        db.query(QuizResponse.question_id, QuizAttempt.started_at)
        .join(QuizAttempt, QuizResponse.attempt_id == QuizAttempt.id)
        .filter(
            QuizAttempt.user_id == user_id,
            QuizResponse.topic_id == topic_id,
        )
        .all()
    )
    seen_ids = set()
    last_seen_at = {}
    for qid, started_at in earlier_seen:
        seen_ids.add(qid)
        if qid not in last_seen_at or (started_at and started_at < last_seen_at[qid]):
            last_seen_at[qid] = started_at

    selection = choose_next_question(
        candidates=all_questions,
        target=target,
        seen_ids=seen_ids,
        last_seen_at=last_seen_at,
    )
    q1 = selection.question

    try:
        attempt = QuizAttempt(
            user_id=user_id,
            course_id=topic.course_id,
            topic_id=topic.id,
            quiz_type="ADAPTIVE",
            mode="adaptive",
            status="in_progress",
            score=0,
            total_questions=ADAPTIVE_QUIZ_LENGTH,
            completed_at=None,
        )
        db.add(attempt)
        db.flush()

        step1 = AdaptiveQuizStep(
            attempt_id=attempt.id,
            step_number=1,
            question_id=q1.id,
            target_difficulty=target,
            served_difficulty=q1.difficulty.lower(),
            selection_reason=selection.selection_reason,
            mastery_before=current_p,
            mastery_after=None,
            selected_answer=None,
            is_correct=None,
            answered_at=None,
        )
        db.add(step1)
        db.commit()
        db.refresh(attempt)
        db.refresh(step1)

        resp = AdaptiveStartResponse(
            attempt_id=attempt.id,
            topic_id=topic_id,
            mode="adaptive",
            total_questions=ADAPTIVE_QUIZ_LENGTH,
            question_number=1,
            resumed=False,
            question=AdaptiveQuestionView(
                question_id=q1.id,
                topic_id=q1.topic_id,
                question_text=q1.question_text,
                option_a=q1.option_a,
                option_b=q1.option_b,
                option_c=q1.option_c,
                option_d=q1.option_d,
            ),
        )
        return resp, status.HTTP_201_CREATED

    except IntegrityError:
        db.rollback()
        # Handle concurrent start race caught by partial unique index uq_adaptive_quiz_in_progress
        resumed = (
            db.query(QuizAttempt)
            .filter(
                QuizAttempt.user_id == user_id,
                QuizAttempt.topic_id == topic_id,
                QuizAttempt.mode == "adaptive",
                QuizAttempt.status == "in_progress",
            )
            .first()
        )
        if resumed:
            pending = (
                db.query(AdaptiveQuizStep)
                .filter(
                    AdaptiveQuizStep.attempt_id == resumed.id,
                    AdaptiveQuizStep.answered_at.is_(None),
                )
                .order_by(AdaptiveQuizStep.step_number.asc())
                .first()
            )
            if pending:
                q = db.query(Question).filter(Question.id == pending.question_id).first()
                resp = AdaptiveStartResponse(
                    attempt_id=resumed.id,
                    topic_id=topic_id,
                    mode="adaptive",
                    total_questions=ADAPTIVE_QUIZ_LENGTH,
                    question_number=pending.step_number,
                    resumed=True,
                    question=AdaptiveQuestionView(
                        question_id=q.id,
                        topic_id=q.topic_id,
                        question_text=q.question_text,
                        option_a=q.option_a,
                        option_b=q.option_b,
                        option_c=q.option_c,
                        option_d=q.option_d,
                    ),
                )
                return resp, status.HTTP_200_OK
        raise


def submit_adaptive_answer(
    db: Session,
    user_id: int,
    attempt_id: int,
    question_id: int,
    selected_answer: str,
) -> AdaptiveAnswerResponse:
    """Processes a submitted answer for the current pending step of an adaptive quiz session.

    Transactional contract:
    - Locks the quiz attempt row using SELECT ... FOR UPDATE.
    - Records the answer and updates step running mastery.
    - If step < 8: chooses next question, writes next step, and commits.
    - If step == 8: marks attempt completed, calls apply_attempt to update TopicMastery,
      and commits atomically. On failure, rolls back completely.
    """
    try:
        attempt = (
            db.query(QuizAttempt)
            .filter(QuizAttempt.id == attempt_id)
            .with_for_update()
            .first()
        )
        if not attempt or attempt.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Adaptive quiz attempt not found.",
            )

        if attempt.mode != "adaptive" or attempt.status != "in_progress":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Attempt {attempt_id} is not an in-progress adaptive quiz.",
            )

        pending_step = (
            db.query(AdaptiveQuizStep)
            .filter(
                AdaptiveQuizStep.attempt_id == attempt.id,
                AdaptiveQuizStep.answered_at.is_(None),
            )
            .order_by(AdaptiveQuizStep.step_number.asc())
            .first()
        )
        if not pending_step:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No pending question to answer for this attempt.",
            )

        if pending_step.question_id != question_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Expected answer for question {pending_step.question_id}, but received {question_id}.",
            )

        question = db.query(Question).filter(Question.id == question_id).first()
        if not question:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question not found.",
            )

        norm_selected = selected_answer.strip().upper()
        is_correct = check_answer_correctness(norm_selected, question.correct_answer)

        # 1. Insert quiz_responses row
        response_row = QuizResponse(
            attempt_id=attempt.id,
            question_id=question.id,
            topic_id=attempt.topic_id,
            selected_answer=norm_selected,
            is_correct=is_correct,
        )
        db.add(response_row)

        # 2. Advance running mastery estimate and update pending step
        now = datetime.now(timezone.utc)
        mastery_after = advance_running_mastery(
            pending_step.mastery_before,
            is_correct,
            pending_step.served_difficulty,
        )
        pending_step.selected_answer = norm_selected
        pending_step.is_correct = is_correct
        pending_step.answered_at = now
        pending_step.mastery_after = mastery_after

        # 3. Check for 8-question stopping rule
        if pending_step.step_number < ADAPTIVE_QUIZ_LENGTH:
            next_target = target_difficulty(mastery_after)

            # Exclude questions already served in this attempt
            served_in_attempt = set(
                row[0]
                for row in db.query(AdaptiveQuizStep.question_id)
                .filter(AdaptiveQuizStep.attempt_id == attempt.id)
                .all()
            )
            served_in_attempt.add(pending_step.question_id)

            available_candidates = (
                db.query(Question)
                .filter(
                    Question.topic_id == attempt.topic_id,
                    ~Question.id.in_(served_in_attempt),
                )
                .all()
            )

            # Seen questions from earlier attempts of this topic
            earlier_seen = (
                db.query(QuizResponse.question_id, QuizAttempt.started_at)
                .join(QuizAttempt, QuizResponse.attempt_id == QuizAttempt.id)
                .filter(
                    QuizAttempt.user_id == user_id,
                    QuizResponse.topic_id == attempt.topic_id,
                    QuizAttempt.id != attempt.id,
                )
                .all()
            )
            seen_ids = set()
            last_seen_at = {}
            for qid, started_at in earlier_seen:
                seen_ids.add(qid)
                if qid not in last_seen_at or (started_at and started_at < last_seen_at[qid]):
                    last_seen_at[qid] = started_at

            selection = choose_next_question(
                candidates=available_candidates,
                target=next_target,
                seen_ids=seen_ids,
                last_seen_at=last_seen_at,
            )
            next_q = selection.question

            next_step = AdaptiveQuizStep(
                attempt_id=attempt.id,
                step_number=pending_step.step_number + 1,
                question_id=next_q.id,
                target_difficulty=next_target,
                served_difficulty=next_q.difficulty.lower(),
                selection_reason=selection.selection_reason,
                mastery_before=mastery_after,
                mastery_after=None,
                selected_answer=None,
                is_correct=None,
                answered_at=None,
            )
            db.add(next_step)
            db.commit()

            return AdaptiveAnswerResponse(
                attempt_id=attempt.id,
                question_id=question.id,
                is_correct=is_correct,
                correct_answer=question.correct_answer.upper(),
                explanation=f"Option {question.correct_answer.upper()} is the correct answer.",
                question_number=pending_step.step_number,
                finished=False,
                next_question=AdaptiveQuestionView(
                    question_id=next_q.id,
                    topic_id=next_q.topic_id,
                    question_text=next_q.question_text,
                    option_a=next_q.option_a,
                    option_b=next_q.option_b,
                    option_c=next_q.option_c,
                    option_d=next_q.option_d,
                ),
                result=None,
            )

        else:
            # 8th question: finalize attempt and update mastery in one transaction
            db.flush()
            all_responses = (
                db.query(QuizResponse)
                .filter(QuizResponse.attempt_id == attempt.id)
                .order_by(QuizResponse.id.asc())
                .all()
            )
            correct_count = sum(1 for r in all_responses if r.is_correct)
            total_count = len(all_responses)
            incorrect_count = total_count - correct_count
            percentage = round((correct_count / total_count) * 100, 2)

            attempt.score = correct_count
            attempt.total_questions = total_count
            attempt.status = "completed"
            attempt.completed_at = now
            db.flush()

            step1 = (
                db.query(AdaptiveQuizStep)
                .filter(AdaptiveQuizStep.attempt_id == attempt.id, AdaptiveQuizStep.step_number == 1)
                .first()
            )
            initial_mastery = step1.mastery_before if step1 else P_INIT

            # Execute canonical BKT mastery update
            apply_attempt(
                db=db,
                user_id=user_id,
                attempt=attempt,
                responses_in_order=all_responses,
                as_of=now,
            )

            # Query final point-in-time topic mastery
            final_tm = (
                db.query(TopicMastery)
                .filter(TopicMastery.user_id == user_id, TopicMastery.topic_id == attempt.topic_id)
                .first()
            )
            final_p = float(final_tm.mastery_probability) if final_tm else mastery_after
            total_ans = final_tm.total_answers if final_tm else total_count
            final_status = classify(final_p, total_ans)

            db.commit()

            return AdaptiveAnswerResponse(
                attempt_id=attempt.id,
                question_id=question.id,
                is_correct=is_correct,
                correct_answer=question.correct_answer.upper(),
                explanation=f"Option {question.correct_answer.upper()} is the correct answer.",
                question_number=pending_step.step_number,
                finished=True,
                next_question=None,
                result=AdaptiveResultSummary(
                    attempt_id=attempt.id,
                    topic_id=attempt.topic_id,
                    score=correct_count,
                    total_questions=total_count,
                    percentage=percentage,
                    correct_answers=correct_count,
                    incorrect_answers=incorrect_count,
                    mastery_before=initial_mastery,
                    mastery_after=final_p,
                    status=final_status,
                ),
            )

    except Exception:
        db.rollback()
        raise
