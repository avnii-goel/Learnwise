from pydantic import BaseModel

class QuizQuestionResponse(BaseModel):
    question_id: int
    topic_id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str

class QuizResponse(BaseModel):
    course_id: int
    questions: list[QuizQuestionResponse]

class QuizAnswer(BaseModel):
    question_id: int
    selected_answer: str

class QuizSubmission(BaseModel):
    course_id: int
    answers: list[QuizAnswer]

class QuizResult(BaseModel):
    attempt_id: int
    course_id: int
    score: int
    total_questions: int
    percentage: float
    correct_answers: int
    incorrect_answers: int


# --- Adaptive Quizzing Schemas (Phase 7) ---

class AdaptiveStartRequest(BaseModel):
    topic_id: int


class AdaptiveQuestionView(BaseModel):
    question_id: int
    topic_id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str


class AdaptiveStartResponse(BaseModel):
    attempt_id: int
    topic_id: int
    mode: str
    total_questions: int
    question_number: int
    resumed: bool = False
    question: AdaptiveQuestionView


class AdaptiveAnswerRequest(BaseModel):
    question_id: int
    selected_answer: str


class AdaptiveResultSummary(BaseModel):
    attempt_id: int
    topic_id: int
    score: int
    total_questions: int
    percentage: float
    correct_answers: int
    incorrect_answers: int
    mastery_before: float
    mastery_after: float
    status: str


class AdaptiveAnswerResponse(BaseModel):
    attempt_id: int
    question_id: int
    is_correct: bool
    correct_answer: str
    explanation: str | None = None
    question_number: int
    finished: bool
    next_question: AdaptiveQuestionView | None = None
    result: AdaptiveResultSummary | None = None
