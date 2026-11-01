import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch, ApiError } from '../api/client'
import type { TopicMasteryItemResponse } from '../api/types'

interface CourseGroup {
  courseId: number
  courseTitle: string
  topics: TopicMasteryItemResponse[]
}

export function QuizPickerPage() {
  const [courses, setCourses] = useState<CourseGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadMastery = async () => {
    setLoading(true)
    setError(null)
    try {
      const items = await apiFetch<TopicMasteryItemResponse[]>('/api/mastery/me')

      // Group topics by course preserving order
      const courseMap = new Map<number, CourseGroup>()
      for (const item of items) {
        if (!courseMap.has(item.course_id)) {
          courseMap.set(item.course_id, {
            courseId: item.course_id,
            courseTitle: item.course_title,
            topics: [],
          })
        }
        courseMap.get(item.course_id)!.topics.push(item)
      }

      setCourses(Array.from(courseMap.values()))
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to load courses. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadMastery()
  }, [])

  if (loading) {
    return <div className="loading-state">Loading courses and topics...</div>
  }

  if (error) {
    return (
      <div className="page-container">
        <div className="alert alert-error" role="alert">
          {error}
        </div>
        <button type="button" onClick={loadMastery} className="btn btn-primary">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>Quiz Hub</h1>
        <p className="page-subtitle">
          Choose a comprehensive course quiz or practice a specific topic with adaptive questions.
        </p>
      </div>

      <div className="course-list">
        {courses.map((course) => (
          <div key={course.courseId} className="card course-card">
            <div className="course-card-header">
              <div>
                <h2>{course.courseTitle}</h2>
                <p className="course-topic-count">
                  {course.topics.length} topics available
                </p>
              </div>
              <Link
                to={`/quiz/fixed/${course.courseId}`}
                className="btn btn-primary"
              >
                Take 20-question course quiz
              </Link>
            </div>

            <div className="topic-list">
              {course.topics.map((topic) => {
                const isUnattempted =
                  topic.status === 'not_attempted' || topic.total_answers === 0

                return (
                  <div key={topic.topic_id} className="topic-row">
                    <div className="topic-info">
                      <span className="topic-title">{topic.topic_title}</span>
                      <span className={`status-badge status-${topic.status}`}>
                        {topic.status.replace('_', ' ')}
                      </span>
                    </div>
                    <Link
                      to={`/quiz/adaptive/${topic.topic_id}`}
                      className="btn btn-secondary btn-sm"
                    >
                      {isUnattempted
                        ? 'Start initial quiz (8 questions)'
                        : 'Start adaptive quiz (8 questions)'}
                    </Link>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

