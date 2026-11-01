import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiFetch, apiFetchWithStatus, ApiError } from '../api/client'
import type {
  AdaptiveAnswerResponse,
  AdaptiveQuestionView,
  AdaptiveResultSummary,
  AdaptiveStartResponse,
} from '../api/types'

export function AdaptiveQuizPage() {
  const { topicId } = useParams<{ topicId: string }>()
  const numericTopicId = Number(topicId)

  const startedRef = useRef(false)

  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [errorStatus, setErrorStatus] = useState<number | null>(null)

  const [attemptId, setAttemptId] = useState<number | null>(null)
  const [totalQuestions, setTotalQuestions] = useState(8)
  const [questionNumber, setQuestionNumber] = useState(1)
  const [currentQuestion, setCurrentQuestion] = useState<AdaptiveQuestionView | null>(null)
  const [selectedAnswer, setSelectedAnswer] = useState<string>('')
  const [feedback, setFeedback] = useState<AdaptiveAnswerResponse | null>(null)
  const [isFinished, setIsFinished] = useState(false)
  const [result, setResult] = useState<AdaptiveResultSummary | null>(null)
  const [resumed, setResumed] = useState(false)

  const startQuiz = async () => {
    setLoading(true)
    setError(null)
    setErrorStatus(null)
    setFeedback(null)
    setIsFinished(false)
    setResult(null)
    setSelectedAnswer('')

    try {
      const resp = await apiFetchWithStatus<AdaptiveStartResponse>(
        '/api/quiz/adaptive/start',
        {
          method: 'POST',
          body: JSON.stringify({ topic_id: numericTopicId }),
        }
      )

      setAttemptId(resp.data.attempt_id)
      setTotalQuestions(resp.data.total_questions || 8)
      setQuestionNumber(resp.data.question_number || 1)
      setCurrentQuestion(resp.data.question)
      setResumed(resp.data.resumed || resp.status === 200)
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorStatus(err.status)
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to start adaptive quiz.')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    startQuiz()
  }, [topicId])

  const handleSubmitAnswer = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!attemptId || !currentQuestion || !selectedAnswer || submitting) {
      return
    }

    setSubmitting(true)
    setError(null)

    try {
      const resp = await apiFetch<AdaptiveAnswerResponse>(
        `/api/quiz/adaptive/${attemptId}/answer`,
        {
          method: 'POST',
          body: JSON.stringify({
            question_id: currentQuestion.question_id,
            selected_answer: selectedAnswer,
          }),
        }
      )

      setFeedback(resp)

      if (resp.finished) {
        setIsFinished(true)
        if (resp.result) {
          setResult(resp.result)
        }
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorStatus(err.status)
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to submit answer.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleNextQuestion = () => {
    if (!feedback || !feedback.next_question) return
    setCurrentQuestion(feedback.next_question)
    setQuestionNumber((prev) => prev + 1)
    setSelectedAnswer('')
    setFeedback(null)
  }

  if (loading) {
    return <div className="loading-state">Starting adaptive quiz session...</div>
  }

  // Handle 409 Conflict
  if (errorStatus === 409) {
    return (
      <div className="page-container">
        <div className="card text-center">
          <div className="alert alert-warning" role="alert">
            {error}
          </div>
          <p style={{ margin: '1rem 0' }}>
            You can reload this quiz to synchronize with your active session.
          </p>
          <button type="button" onClick={startQuiz} className="btn btn-primary">
            Reload quiz
          </button>
        </div>
      </div>
    )
  }

  // Handle 404 Not Found
  if (errorStatus === 404) {
    return (
      <div className="page-container">
        <div className="card text-center">
          <div className="alert alert-error" role="alert">
            {error || 'Topic not found.'}
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

  // Generic start error
  if (error && !currentQuestion && !isFinished) {
    return (
      <div className="page-container">
        <div className="card text-center">
          <div className="alert alert-error" role="alert">
            {error}
          </div>
          <button type="button" onClick={startQuiz} className="btn btn-primary" style={{ marginTop: '1rem' }}>
            Try Again
          </button>
        </div>
      </div>
    )
  }

  // Finished state: Result summary card
  if (isFinished && result) {
    const masteryBeforePct = (result.mastery_before * 100).toFixed(1)
    const masteryAfterPct = (result.mastery_after * 100).toFixed(1)

    return (
      <div className="page-container">
        <div className="card result-card">
          <h2>Quiz complete!</h2>
          <p className="card-subtitle">
            You have completed the 8-question adaptive assessment for this topic.
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
              <span className="stat-label">Mastery</span>
              <span className="stat-value">
                {masteryBeforePct}% &rarr; {masteryAfterPct}%
              </span>
            </div>

            <div className="result-stat-box">
              <span className="stat-label">Competency Status</span>
              <span className={`status-badge status-${result.status}`}>
                {result.status.replace('_', ' ')}
              </span>
            </div>
          </div>

          <div className="result-actions">
            <Link to="/dashboard" className="btn btn-secondary">
              Back to dashboard
            </Link>
            <Link to="/quiz" className="btn btn-primary">
              Quiz another topic
            </Link>
          </div>
        </div>
      </div>
    )
  }

  // Active question state
  if (!currentQuestion) {
    return <div className="loading-state">No question available.</div>
  }

  const options: Array<{ key: 'A' | 'B' | 'C' | 'D'; text: string }> = [
    { key: 'A', text: currentQuestion.option_a },
    { key: 'B', text: currentQuestion.option_b },
    { key: 'C', text: currentQuestion.option_c },
    { key: 'D', text: currentQuestion.option_d },
  ]

  return (
    <div className="page-container">
      <div className="card quiz-runner-card">
        <div className="quiz-header">
          <span className="question-progress">
            Question {questionNumber} of {totalQuestions}
          </span>
          {resumed && (
            <span className="badge badge-info">Resumed session</span>
          )}
        </div>

        {error && (
          <div className="alert alert-error" role="alert">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmitAnswer} className="question-form">
          <h2 className="question-text">{currentQuestion.question_text}</h2>

          <div className="options-container" role="radiogroup">
            {options.map((opt) => {
              const isSelected = selectedAnswer === opt.key
              return (
                <label
                  key={opt.key}
                  className={`option-label ${isSelected ? 'option-selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="adaptive-quiz-option"
                    value={opt.key}
                    checked={isSelected}
                    onChange={() => setSelectedAnswer(opt.key)}
                    disabled={submitting || feedback !== null}
                  />
                  <span className="option-key">{opt.key}</span>
                  <span className="option-text">{opt.text}</span>
                </label>
              )
            })}
          </div>

          {!feedback ? (
            <div className="question-actions">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={!selectedAnswer || submitting}
              >
                {submitting ? 'Submitting...' : 'Submit answer'}
              </button>
            </div>
          ) : (
            <div className="feedback-section">
              <div
                className={`feedback-banner ${
                  feedback.is_correct ? 'feedback-correct' : 'feedback-incorrect'
                }`}
              >
                <strong>{feedback.is_correct ? 'Correct!' : 'Incorrect'}</strong>
                <span className="correct-answer-text">
                  Correct answer: <strong>{feedback.correct_answer}</strong>
                </span>
              </div>

              {feedback.explanation && (
                <p className="feedback-explanation">{feedback.explanation}</p>
              )}

              {!feedback.finished && (
                <div className="feedback-actions">
                  <button
                    type="button"
                    onClick={handleNextQuestion}
                    className="btn btn-primary"
                  >
                    Next question
                  </button>
                </div>
              )}
            </div>
          )}
        </form>
      </div>
    </div>
  )
}

