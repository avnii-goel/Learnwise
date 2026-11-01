import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiFetch, ApiError } from '../api/client'
import type {
  QuizQuestionResponse,
  QuizResponse,
  QuizResult,
  QuizSubmission,
} from '../api/types'

export function FixedQuizPage() {
  const { courseId } = useParams<{ courseId: string }>()
  const numericCourseId = Number(courseId)

  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [questions, setQuestions] = useState<QuizQuestionResponse[]>([])
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [result, setResult] = useState<QuizResult | null>(null)

  const loadQuestions = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    setAnswers({})

    try {
      const resp = await apiFetch<QuizResponse>(
        `/api/quiz/generate/course/${numericCourseId}`,
        {
          method: 'POST',
        }
      )
      setQuestions(resp.questions)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to generate course quiz.')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadQuestions()
  }, [courseId])

  const handleSelectOption = (questionId: number, optionKey: string) => {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: optionKey,
    }))
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (questions.length === 0 || submitting) return

    // Require all questions answered per API contract expectations
    if (Object.keys(answers).length !== questions.length) {
      setError('Please answer all questions before submitting.')
      return
    }

    setSubmitting(true)
    setError(null)

    const submission: QuizSubmission = {
      course_id: numericCourseId,
      answers: questions.map((q) => ({
        question_id: q.question_id,
        selected_answer: answers[q.question_id] || '',
      })),
    }

    try {
      const res = await apiFetch<QuizResult>('/api/quiz/submit', {
        method: 'POST',
        body: JSON.stringify(submission),
      })
      setResult(res)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to submit quiz.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <div className="loading-state">Generating 20-question course quiz...</div>
  }

  if (error && questions.length === 0) {
    return (
      <div className="page-container">
        <div className="card text-center">
          <div className="alert alert-error" role="alert">
            {error}
          </div>
          <div style={{ marginTop: '1rem' }}>
            <Link to="/quiz" className="btn btn-primary">
              Back to Quiz Hub
            </Link>
          </div>
        </div>
      </div>
    )
  }

  if (result) {
    return (
      <div className="page-container">
        <div className="card result-card">
          <h2>Course quiz complete!</h2>
          <p className="card-subtitle">
            Your answers have been graded and your topic mastery has been updated.
          </p>

          <div className="result-stats-grid">
            <div className="result-stat-box">
              <span className="stat-label">Score</span>
              <span className="stat-value">
                {result.score} / {result.total_questions}
              </span>
            </div>

            <div className="result-stat-box">
              <span className="stat-label">Percentage</span>
              <span className="stat-value">{result.percentage}%</span>
            </div>

            <div className="result-stat-box">
              <span className="stat-label">Correct</span>
              <span className="stat-value" style={{ color: 'var(--success-color, #16a34a)' }}>
                {result.correct_answers}
              </span>
            </div>

            <div className="result-stat-box">
              <span className="stat-label">Incorrect</span>
              <span className="stat-value" style={{ color: 'var(--danger-color, #dc2626)' }}>
                {result.incorrect_answers}
              </span>
            </div>
          </div>

          <div className="result-actions">
            <Link to="/dashboard" className="btn btn-secondary">
              Back to dashboard
            </Link>
            <Link to="/quiz" className="btn btn-primary">
              Take another quiz
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const answeredCount = Object.keys(answers).length
  const allAnswered = answeredCount === questions.length

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>Course Quiz</h1>
        <p className="notice-banner">
          Note: Refreshing mid-quiz loses answers. Please answer all questions before submitting.
        </p>
      </div>

      {error && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: '1.5rem' }}>
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="fixed-quiz-form">
        <div className="questions-stack">
          {questions.map((q, idx) => {
            const selected = answers[q.question_id]
            const options: Array<{ key: 'A' | 'B' | 'C' | 'D'; text: string }> = [
              { key: 'A', text: q.option_a },
              { key: 'B', text: q.option_b },
              { key: 'C', text: q.option_c },
              { key: 'D', text: q.option_d },
            ]

            return (
              <div key={q.question_id} className="card question-card">
                <div className="question-header">
                  <span className="question-number">Question {idx + 1} of {questions.length}</span>
                </div>

                <h3 className="question-text">{q.question_text}</h3>

                <div className="options-container" role="radiogroup">
                  {options.map((opt) => {
                    const isSelected = selected === opt.key
                    return (
                      <label
                        key={opt.key}
                        className={`option-label ${isSelected ? 'option-selected' : ''}`}
                      >
                        <input
                          type="radio"
                          name={`question-${q.question_id}`}
                          value={opt.key}
                          checked={isSelected}
                          onChange={() => handleSelectOption(q.question_id, opt.key)}
                          disabled={submitting}
                        />
                        <span className="option-key">{opt.key}</span>
                        <span className="option-text">{opt.text}</span>
                      </label>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>

        <div className="quiz-submit-bar card">
          <div className="submit-bar-info">
            <span>
              Progress: <strong>{answeredCount}</strong> of <strong>{questions.length}</strong> questions answered
            </span>
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={!allAnswered || submitting}
          >
            {submitting ? 'Submitting...' : `Submit quiz (${answeredCount}/${questions.length} answered)`}
          </button>
        </div>
      </form>
    </div>
  )
}

