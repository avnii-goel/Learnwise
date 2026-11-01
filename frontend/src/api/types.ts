// TypeScript types for Chunk 8.3 endpoints copied from backend/app/schemas

// --- Auth Endpoints (/api/auth) ---

export interface UserLoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface UserResponse {
  id: number
  name: string
  email: string
  role: 'learner' | 'instructor'
  created_at: string
}

// --- Mastery Endpoint (GET /api/mastery/me) ---

export interface TopicMasteryItemResponse {
  course_id: number
  course_title: string
  topic_id: number
  topic_title: string
  order: number
  mastery_probability: number | null
  status: string
  total_answers: number
  correct_answers: number
  last_answered_at: string | null
}

// --- Fixed Course Quiz Endpoints (/api/quiz/generate/course/{id}, /api/quiz/submit) ---

export interface QuizQuestionResponse {
  question_id: number
  topic_id: number
  question_text: string
  option_a: string
  option_b: string
  option_c: string
  option_d: string
}

export interface QuizResponse {
  course_id: number
  questions: QuizQuestionResponse[]
}

export interface QuizAnswer {
  question_id: number
  selected_answer: string
}

export interface QuizSubmission {
  course_id: number
  answers: QuizAnswer[]
}

export interface QuizResult {
  attempt_id: number
  course_id: number
  score: number
  total_questions: number
  percentage: number
  correct_answers: number
  incorrect_answers: number
}

// --- Adaptive Quiz Endpoints (/api/quiz/adaptive/start, /api/quiz/adaptive/{id}/answer) ---

export interface AdaptiveStartRequest {
  topic_id: number
}

export interface AdaptiveQuestionView {
  question_id: number
  topic_id: number
  question_text: string
  option_a: string
  option_b: string
  option_c: string
  option_d: string
}

export interface AdaptiveStartResponse {
  attempt_id: number
  topic_id: number
  mode: string
  total_questions: number
  question_number: number
  resumed: boolean
  question: AdaptiveQuestionView
}

export interface AdaptiveAnswerRequest {
  question_id: number
  selected_answer: string
}

export interface AdaptiveResultSummary {
  attempt_id: number
  topic_id: number
  score: number
  total_questions: number
  percentage: number
  correct_answers: number
  incorrect_answers: number
  mastery_before: number
  mastery_after: number
  status: string
}

export interface AdaptiveAnswerResponse {
  attempt_id: number
  question_id: number
  is_correct: boolean
  correct_answer: string
  explanation: string | null
  question_number: number
  finished: boolean
  next_question: AdaptiveQuestionView | null
  result: AdaptiveResultSummary | null
}

// --- Learner Dashboard Endpoints (/api/dashboard/me*) ---

export interface StatusCounts {
  strong: number
  developing: number
  weak: number
  not_attempted: number
}

export interface LearnerOverview {
  total_topics: number
  attempted_topics: number
  progress_percent: number
  avg_mastery_attempted: number | null
  status_counts: StatusCounts
  completed_quizzes: number
}

export interface TopicProgressItem {
  topic_id: number
  topic_title: string
  order: number
  mastery_probability: number | null
  status: string
  attempted: boolean
}

export interface CourseProgressItem {
  course_id: number
  course_title: string
  total_topics: number
  attempted_topics: number
  progress_percent: number
  avg_mastery_attempted: number | null
  topics: TopicProgressItem[]
}

export interface TopicHighlightItem {
  topic_id: number
  topic_title: string
  course_title: string
  mastery_probability: number
}

export interface CurrentPathItem {
  rank: number
  topic_id: number
  topic_title: string
  course_title: string
  status: string
  mastery_probability: number | null
}

export interface LearnerDashboardResponse {
  overview: LearnerOverview
  courses: CourseProgressItem[]
  strengths: TopicHighlightItem[]
  weaknesses: TopicHighlightItem[]
  current_path: CurrentPathItem[]
}

export interface QuizHistoryItem {
  attempt_id: number
  mode: string
  course_title: string
  topic_title: string | null
  score: number
  total_questions: number
  percentage: number | null
  completed_at: string
}

export interface QuizHistoryResponse {
  items: QuizHistoryItem[]
}

export interface QuizScoreTrendPoint {
  attempt_id: number
  date: string
  mode: string
  percentage: number
}

export interface MasteryProgressTrendPoint {
  attempt_id: number
  date: string
  avg_mastery: number
}

export interface LearnerTrendsResponse {
  quiz_scores: QuizScoreTrendPoint[]
  mastery_progress: MasteryProgressTrendPoint[]
}

// --- Recommendations Endpoints (/api/recommendations/me, /api/recommendations/impressions/{id}/click) ---

export interface ResourceDetail {
  id: number
  title: string
  description: string | null
  resource_type: string
  url: string
  difficulty: string
}

export interface TopicDetail {
  id: number
  title: string
}

export interface RecommendationComponents {
  need: number
  semantic: number
  difficulty_fit: number
  collaborative: number
}

export interface RecommendationItemResponse {
  impression_id: number
  rank: number
  resource: ResourceDetail
  topic: TopicDetail
  score: number
  mastery: number | null
  status: string
  reason: string
  components: RecommendationComponents
}

export interface RecommendationResponse {
  request_id: string
  strategy: string
  collaborative_available: boolean
  items: RecommendationItemResponse[]
}

export interface ImpressionClickResponse {
  impression_id: number
  resource_url: string
  clicked_at: string
}

// --- Instructor Dashboard Endpoints (/api/dashboard/instructor/*) ---

export interface InstructorStatusCounts {
  strong: number
  developing: number
  weak: number
}

export interface InstructorCourseOverview {
  course_id: number
  course_title: string
  active_learners: number
  completed_attempts: number
  avg_quiz_percentage: number | null
}

export interface InstructorOverviewResponse {
  total_learners: number
  active_learners: number
  completed_attempts: number
  avg_quiz_percentage: number | null
  avg_mastery_attempted: number | null
  courses: InstructorCourseOverview[]
}

export interface InstructorLearnerItem {
  user_id: number
  name: string
  email: string
  attempted_topics: number
  avg_mastery_attempted: number | null
  completed_attempts: number
  avg_quiz_percentage: number | null
  last_active: string | null
}

export interface InstructorLearnersResponse {
  total_topics: number
  items: InstructorLearnerItem[]
}

export interface InstructorTopicItem {
  topic_id: number
  topic_title: string
  course_id: number
  course_title: string
  learners_attempted: number
  avg_mastery: number | null
  accuracy_percent: number | null
  weak_share_percent: number | null
  status_counts: InstructorStatusCounts
}

export interface InstructorTopicsResponse {
  min_learners_for_difficult: number
  topics: InstructorTopicItem[]
  difficult_topics: InstructorTopicItem[]
}


