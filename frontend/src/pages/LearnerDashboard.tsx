import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CartesianGrid,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiFetch, ApiError } from '../api/client'
import type {
  LearnerDashboardResponse,
  LearnerTrendsResponse,
  QuizHistoryResponse,
  RecommendationResponse,
} from '../api/types'
import {
  formatDate,
  formatMastery,
  formatPercent,
  statusLabel,
  toRadarData,
  toTrendData,
  type RadarDataPoint,
} from '../lib/formatters'

interface RadarTooltipProps {
  active?: boolean
  payload?: Array<{ payload: RadarDataPoint }>
}

function CustomRadarTooltip({ active, payload }: RadarTooltipProps) {
  if (active && payload && payload.length) {
    const data = payload[0].payload
    return (
      <div className="chart-tooltip">
        <strong>{data.fullTitle}</strong>
        <div>{data.attempted ? `${data.mastery.toFixed(1)}%` : 'Not attempted'}</div>
      </div>
    )
  }
  return null
}

export function LearnerDashboard() {
  // 1. Primary Dashboard Data (/api/dashboard/me)
  const [dashboardData, setDashboardData] = useState<LearnerDashboardResponse | null>(null)
  const [dashboardLoading, setDashboardLoading] = useState(true)
  const [dashboardError, setDashboardError] = useState<string | null>(null)

  // 2. Quiz History (/api/dashboard/me/history?limit=10)
  const [historyData, setHistoryData] = useState<QuizHistoryResponse | null>(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)

  // 3. Trends Data (/api/dashboard/me/trends)
  const [trendsData, setTrendsData] = useState<LearnerTrendsResponse | null>(null)
  const [trendsLoading, setTrendsLoading] = useState(true)
  const [trendsError, setTrendsError] = useState<string | null>(null)

  // 4. Recommendations (/api/recommendations/me)
  const [recData, setRecData] = useState<RecommendationResponse | null>(null)
  const [recLoading, setRecLoading] = useState(true)
  const [recError, setRecError] = useState<string | null>(null)

  const recCalledRef = useRef(false)
  const initialLoadedRef = useRef(false)

  // Parallel data fetching for independent sections
  useEffect(() => {
    if (initialLoadedRef.current) return
    initialLoadedRef.current = true

    // Section 1: Dashboard
    apiFetch<LearnerDashboardResponse>('/api/dashboard/me')
      .then((res) => {
        setDashboardData(res)
      })
      .catch((err) => {
        setDashboardError(err instanceof ApiError ? err.message : 'Failed to load dashboard overview.')
      })
      .finally(() => setDashboardLoading(false))

    // Section 2: History
    apiFetch<QuizHistoryResponse>('/api/dashboard/me/history?limit=10')
      .then((res) => {
        setHistoryData(res)
      })
      .catch((err) => {
        setHistoryError(err instanceof ApiError ? err.message : 'Failed to load quiz history.')
      })
      .finally(() => setHistoryLoading(false))

    // Section 3: Trends
    apiFetch<LearnerTrendsResponse>('/api/dashboard/me/trends')
      .then((res) => {
        setTrendsData(res)
      })
      .catch((err) => {
        setTrendsError(err instanceof ApiError ? err.message : 'Failed to load progress trends.')
      })
      .finally(() => setTrendsLoading(false))
  }, [])

  // Call POST /api/recommendations/me exactly ONCE per dashboard mount
  useEffect(() => {
    if (recCalledRef.current) return
    recCalledRef.current = true

    apiFetch<RecommendationResponse>('/api/recommendations/me', {
      method: 'POST',
    })
      .then((res) => {
        setRecData(res)
        // When recommendations request succeeds, refetch GET /api/dashboard/me once
        // to update current_path with the newly generated recommendations
        return apiFetch<LearnerDashboardResponse>('/api/dashboard/me')
          .then((updatedDash) => {
            setDashboardData(updatedDash)
          })
          .catch(() => {
            // Keep existing dashboardData if refetch fails
          })
      })
      .catch((err) => {
        setRecError(err instanceof ApiError ? err.message : 'Failed to load recommendations.')
      })
      .finally(() => setRecLoading(false))
  }, [])

  const handleRecommendationClick = (impressionId: number) => {
    // Fire and forget without awaiting; ignore failures so popups/navigation are never blocked
    apiFetch(`/api/recommendations/impressions/${impressionId}/click`, {
      method: 'POST',
    }).catch(() => {})
  }

  const overview = dashboardData?.overview
  const isBrandNewLearner =
    overview && overview.attempted_topics === 0 && overview.completed_quizzes === 0

  return (
    <div className="page-container learner-dashboard">
      <div className="page-header">
        <h1>Learner Dashboard</h1>
        <p className="page-subtitle">Track your knowledge mastery, recent quizzes, and targeted study path.</p>
      </div>

      {/* Prominent Empty State Card for New Learners */}
      {isBrandNewLearner && (
        <div className="card welcome-card" data-testid="welcome-card">
          <h2>Take your first quiz</h2>
          <p>
            Welcome to LearnWise! Complete a diagnostic or adaptive quiz to unlock your personalized
            knowledge radar, competency status, and study recommendations.
          </p>
          <div style={{ marginTop: '1rem' }}>
            <Link to="/quiz" className="btn btn-primary">
              Go to Quiz Hub
            </Link>
          </div>
        </div>
      )}

      {/* 1. Overview Section */}
      <section className="dashboard-section">
        {dashboardLoading && <div className="loading-state">Loading overview metrics...</div>}
        {dashboardError && <div className="alert alert-error" role="alert">{dashboardError}</div>}

        {overview && (
          <div className="overview-grid">
            <div className="card stat-card">
              <span className="stat-card-title">Progress</span>
              <span className="stat-card-value">{formatPercent(overview.progress_percent)}</span>
              <span className="stat-card-desc">
                {overview.attempted_topics} of {overview.total_topics} topics attempted
              </span>
            </div>

            <div className="card stat-card">
              <span className="stat-card-title">Average Mastery</span>
              <span className="stat-card-value">{formatMastery(overview.avg_mastery_attempted)}</span>
              <span className="stat-card-desc">Across attempted topics</span>
            </div>

            <div className="card stat-card">
              <span className="stat-card-title">Completed Quizzes</span>
              <span className="stat-card-value">{overview.completed_quizzes}</span>
              <span className="stat-card-desc">Fixed & adaptive attempts</span>
            </div>

            <div className="card stat-card status-chips-card">
              <span className="stat-card-title">Competency Breakdown</span>
              <div className="status-chips-container">
                <span className="status-chip status-chip-strong">
                  Strong: <strong>{overview.status_counts.strong}</strong>
                </span>
                <span className="status-chip status-chip-developing">
                  Developing: <strong>{overview.status_counts.developing}</strong>
                </span>
                <span className="status-chip status-chip-weak">
                  Weak: <strong>{overview.status_counts.weak}</strong>
                </span>
                <span className="status-chip status-chip-not-attempted">
                  Not Attempted: <strong>{overview.status_counts.not_attempted}</strong>
                </span>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 2. Mastery Radars & Path Grid */}
      <div className="dashboard-columns-grid">
        {/* Left Column: Course Radars */}
        <section className="dashboard-column">
          <h2>Course Mastery Radars</h2>
          {dashboardLoading && <div className="loading-state">Loading course radars...</div>}

          {dashboardData?.courses && dashboardData.courses.length > 0 ? (
            <div className="radar-cards-stack">
              {dashboardData.courses.map((course) => {
                const hasEnoughTopics = course.topics.length >= 3
                const radarData = toRadarData(course)

                return (
                  <div key={course.course_id} className="card course-radar-card">
                    <div className="radar-card-header">
                      <h3>{course.course_title}</h3>
                      <span className="badge badge-info">
                        {course.attempted_topics} / {course.total_topics} Attempted
                      </span>
                    </div>

                    {hasEnoughTopics ? (
                      <div className="radar-chart-container" style={{ width: '100%', height: 300 }}>
                        <ResponsiveContainer width="100%" height={300}>
                          <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="75%">
                            <PolarGrid stroke="#e2e8f0" />
                            <PolarAngleAxis dataKey="topic" tick={{ fontSize: 11, fill: '#475569' }} />
                            <PolarRadiusAxis domain={[0, 100]} angle={30} stroke="#cbd5e1" />
                            <Tooltip content={<CustomRadarTooltip />} />
                            <Radar
                              name="Mastery"
                              dataKey="mastery"
                              stroke="#4f46e5"
                              fill="#4f46e5"
                              fillOpacity={0.45}
                            />
                          </RadarChart>
                        </ResponsiveContainer>
                      </div>
                    ) : (
                      <ul className="simple-topic-list">
                        {course.topics.map((t) => (
                          <li key={t.topic_id} className="simple-topic-item">
                            <span>{t.topic_title}</span>
                            <span className={`status-badge status-${t.status}`}>
                              {t.attempted ? formatMastery(t.mastery_probability) : 'Not attempted'}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )
              })}
            </div>
          ) : (
            !dashboardLoading && <p className="empty-msg">No course information available.</p>
          )}
        </section>

        {/* Right Column: Strengths, Weaknesses, Current Path */}
        <section className="dashboard-column sidebar-column">
          {/* Strengths & Weaknesses */}
          <div className="card highlight-card">
            <h3>Top Strengths</h3>
            {dashboardData?.strengths && dashboardData.strengths.length > 0 ? (
              <ul className="highlight-list">
                {dashboardData.strengths.map((s) => (
                  <li key={s.topic_id} className="highlight-item">
                    <div>
                      <strong>{s.topic_title}</strong>
                      <span className="course-subtitle">{s.course_title}</span>
                    </div>
                    <span className="mastery-val strong-val">
                      {formatMastery(s.mastery_probability)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-msg">No strong topics yet.</p>
            )}

            <div className="highlight-divider" />

            <h3>Areas for Improvement</h3>
            {dashboardData?.weaknesses && dashboardData.weaknesses.length > 0 ? (
              <ul className="highlight-list">
                {dashboardData.weaknesses.map((w) => (
                  <li key={w.topic_id} className="highlight-item">
                    <div>
                      <strong>{w.topic_title}</strong>
                      <span className="course-subtitle">{w.course_title}</span>
                    </div>
                    <span className="mastery-val weak-val">
                      {formatMastery(w.mastery_probability)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-msg">No weak topics — keep it up!</p>
            )}
          </div>

          {/* Current Path */}
          <div className="card current-path-card">
            <h3>Current Learning Path</h3>
            {dashboardData?.current_path && dashboardData.current_path.length > 0 ? (
              <ol className="path-list">
                {dashboardData.current_path.map((item) => (
                  <li key={item.topic_id} className="path-item">
                    <span className="path-rank">{item.rank}</span>
                    <div className="path-info">
                      <strong>{item.topic_title}</strong>
                      <span className="course-subtitle">{item.course_title}</span>
                    </div>
                    <div className="path-meta">
                      <span className={`status-badge status-${item.status}`}>
                        {statusLabel(item.status)}
                      </span>
                      <span className="mastery-val">{formatMastery(item.mastery_probability)}</span>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="empty-msg">
                Your path appears once you've viewed recommendations after a quiz.
              </p>
            )}
          </div>
        </section>
      </div>

      {/* 3. Recommendations Panel */}
      <section className="dashboard-section">
        <h2>Targeted Study Recommendations</h2>
        <div className="card recommendations-card">
          {recLoading && <div className="loading-state">Finding personalized resources...</div>}
          {recError && <div className="alert alert-error" role="alert">{recError}</div>}

          {!recLoading && !recError && recData && (
            <>
              {recData.items.length === 0 ? (
                <p className="empty-msg">
                  No recommendations yet — take a quiz so we can see where you need help.
                </p>
              ) : (
                <div className="recommendations-grid">
                  {recData.items.map((item) => (
                    <div key={item.impression_id} className="recommendation-item-card">
                      <div className="rec-header">
                        <h4>{item.resource.title}</h4>
                        <div className="rec-tags">
                          <span className="tag tag-type">{item.resource.resource_type}</span>
                          <span className="tag tag-diff">{item.resource.difficulty}</span>
                        </div>
                      </div>

                      <div className="rec-topic-badge">Topic: {item.topic.title}</div>
                      <p className="rec-reason">{item.reason}</p>

                      <div className="rec-actions">
                        <a
                          href={item.resource.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn-primary btn-sm"
                          onClick={() => handleRecommendationClick(item.impression_id)}
                        >
                          Open resource
                        </a>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </section>

      {/* 4. Trends Section */}
      <section className="dashboard-section">
        <h2>Progress Trends</h2>
        <div className="trends-grid">
          {/* Quiz Score Trend */}
          <div className="card trend-card">
            <h3>Quiz scores (%)</h3>
            {trendsLoading && <div className="loading-state">Loading scores...</div>}
            {trendsError && <div className="alert alert-error" role="alert">{trendsError}</div>}

            {!trendsLoading && !trendsError && trendsData && (
              <>
                {trendsData.quiz_scores.length === 0 ? (
                  <p className="empty-msg">Complete a quiz to see your trends.</p>
                ) : (
                  <div style={{ width: '100%', height: 260 }}>
                    <ResponsiveContainer width="100%" height={260}>
                      <LineChart
                        data={toTrendData(trendsData.quiz_scores, 'percentage')}
                        margin={{ top: 10, right: 20, left: -10, bottom: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                        <Tooltip />
                        <Line
                          type="monotone"
                          dataKey="value"
                          name="Score %"
                          stroke="#4f46e5"
                          strokeWidth={2}
                          dot={{ r: 4, fill: '#4f46e5' }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Average Mastery Trend */}
          <div className="card trend-card">
            <h3>Average mastery (%)</h3>
            {trendsLoading && <div className="loading-state">Loading mastery trends...</div>}
            {trendsError && <div className="alert alert-error" role="alert">{trendsError}</div>}

            {!trendsLoading && !trendsError && trendsData && (
              <>
                {trendsData.mastery_progress.length === 0 ? (
                  <p className="empty-msg">Complete a quiz to see your trends.</p>
                ) : (
                  <div style={{ width: '100%', height: 260 }}>
                    <ResponsiveContainer width="100%" height={260}>
                      <LineChart
                        data={toTrendData(trendsData.mastery_progress, 'avg_mastery')}
                        margin={{ top: 10, right: 20, left: -10, bottom: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                        <Tooltip />
                        <Line
                          type="monotone"
                          dataKey="value"
                          name="Avg Mastery %"
                          stroke="#16a34a"
                          strokeWidth={2}
                          dot={{ r: 4, fill: '#16a34a' }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </section>

      {/* 5. Quiz History Table */}
      <section className="dashboard-section">
        <h2>Recent Quiz History</h2>
        <div className="card history-card">
          {historyLoading && <div className="loading-state">Loading quiz history...</div>}
          {historyError && <div className="alert alert-error" role="alert">{historyError}</div>}

          {!historyLoading && !historyError && historyData && (
            <>
              {historyData.items.length === 0 ? (
                <p className="empty-msg">No completed quizzes yet.</p>
              ) : (
                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Type</th>
                        <th>Course / Topic</th>
                        <th>Score</th>
                        <th>Percentage</th>
                      </tr>
                    </thead>
                    <tbody>
                      {historyData.items.map((item) => (
                        <tr key={item.attempt_id}>
                          <td>{formatDate(item.completed_at)}</td>
                          <td>
                            <span className="badge badge-info">{item.mode}</span>
                          </td>
                          <td>
                            <strong>{item.course_title}</strong>
                            {item.topic_title && (
                              <div className="table-subtext">{item.topic_title}</div>
                            )}
                          </td>
                          <td>
                            {item.score} / {item.total_questions}
                          </td>
                          <td>{formatPercent(item.percentage)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  )
}

