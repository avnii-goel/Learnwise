import random
from typing import Sequence
from app.models.question import Question


def select_quiz_questions(
    questions: Sequence[Question],
    topic_ids: Sequence[int],
    target_count: int = 20,
    rng: random.Random | None = None
) -> list[Question]:
    """Selects quiz questions ensuring all topics are represented, then filling up to target_count.

    Replicates the canonical LearnWise quiz generation logic:
    1. Groups questions by topic_id.
    2. Selects at least 1 random question per topic to ensure full topic representation.
    3. Fills remaining quota (up to target_count) from remaining pool.
    4. Falls back to random sample of all questions if needed.
    5. Shuffles the final selection.

    Args:
        questions: Pool of available Question objects for the course.
        topic_ids: List of topic IDs that must be represented in the quiz.
        target_count: Total questions to select (default 20).
        rng: Optional random.Random instance for deterministic reproducibility.
             If None, standard random module is used.

    Returns:
        list[Question]: Shuffled list of selected questions.
    """
    rand = rng if rng is not None else random

    questions_by_topic: dict[int, list[Question]] = {}
    for q in questions:
        questions_by_topic.setdefault(q.topic_id, []).append(q)

    selected_questions: list[Question] = []
    remaining_pool: list[Question] = []

    for t_id in topic_ids:
        q_list = questions_by_topic.get(t_id, [])
        if q_list:
            picked = rand.choice(q_list)
            selected_questions.append(picked)
            remaining_pool.extend([item for item in q_list if item.id != picked.id])

    needed = target_count - len(selected_questions)
    if needed > 0 and len(remaining_pool) >= needed:
        selected_questions.extend(rand.sample(remaining_pool, needed))
    elif needed > 0:
        selected_questions = rand.sample(list(questions), target_count)

    rand.shuffle(selected_questions)
    return selected_questions
