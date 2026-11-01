import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiFetch, ApiError } from '../api/client'
import type {
  InstructorLearnerItem,
  InstructorLearnersResponse,
  InstructorOverviewResponse,
  InstructorTopicsResponse,
} from '../api/types'
import {
  formatDate,
  formatMastery,
  formatPercent,
  sortLearners,
  toCourseBarData,
  toTopicBarData,
  type CourseBarDataPoint,
  type TopicBarDataPoint,
} from '../lib/formatters'

interface CourseTooltipProps {
  active?: boolean
  payload?: Array<{ payload: CourseBarDataPoint }>
}

function CourseCustomTooltip({ active, payload }: CourseTooltipProps) {
  if (active && payload && payload.length) {
    const item = payload[0].payload
    return (
      <div className="chart-tooltip">
        <strong>{item.courseTitle}</strong>
        <div>
          Score avg: {item.value !== null ? `${item.value.toFixed(1)}%` : 'No attempts yet'}
        </div>
        <div>Active learners: {item.activeLearners}</div>
        <div>Completed attempts: {item.completedAttempts}</div>
      </div>
    )
  }
  return null
}

interface TopicTooltipProps {
  active?: boolean
  payload?: Array<{ payload: TopicBarDataPoint }>
}

function TopicCustomTooltip({ active, payload }: TopicTooltipProps) {
  if (active && payload && payload.length) {
    const item = payload[0].payload
    return (
      <div className="chart-tooltip">
        <strong>{item.fullTitle}</strong>
        <div className="table-subtext">{item.courseTitle}</div>
        <div>
          Avg mastery: {item.value !== null ? `${item.value.toFixed(1)}%` : 'No data'}
        </div>
        <div>Learners attempted: {item.learnersAttempted}</div>
        <div>Accuracy: {formatPercent(item.accuracy)}</div>
        <div>Weak share: {formatPercent(item.weakShare)}</div>
      </div>
    )
  }
  return null
}

function formatError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 403) {
      return 'Instructor access required'
    }
    return err.message
  }
  return fallback
}

export function InstructorDashboard() {
  // 1. Overview Section
  const [overviewData, setOverviewData] = useState<InstructorOverviewResponse | null>(null)
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [overviewError, setOverviewError] = useState<string | null>(null)

  // 2. Learners Section
  const [learnersData, setLearnersData] = useState<InstructorLearnersResponse | null>(null)
  const [learnersLoading, setLearnersLoading] = useState(true)
  const [learnersError, setLearnersError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<keyof InstructorLearnerItem>('name')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')

  // 3. Topics Section (Topics chart + Difficult topics list)
  const [topicsData, setTopicsData] = useState<InstructorTopicsResponse | null>(null)
  const [topicsLoading, setTopicsLoading] = useState(true)
  const [topicsError, setTopicsError] = useState<string | null>(null)

  // Parallel fetching of the 3 instructor endpoints
  useEffect(() => {
    // 1. Overview
    apiFetch<InstructorOverviewResponse>('/api/dashboard/instructor/overview')
      .then((res) => setOverviewData(res))
      .catch((err) => setOverviewError(formatError(err, 'Failed to load cohort overview.')))
      .finally(() => setOverviewLoading(false))

    // 2. Learners
    apiFetch<InstructorLearnersResponse>('/api/dashboard/instructor/learners')
      .then((res) => setLearnersData(res))
      .catch((err) => setLearnersError(formatError(err, 'Failed to load learners list.')))
      .finally(() => setLearnersLoading(false))

    // 3. Topics
    apiFetch<InstructorTopicsResponse>('/api/dashboard/instructor/topics')
      .then((res) => setTopicsData(res))
      .catch((err) => setTopicsError(formatError(err, 'Failed to load topic analytics.')))
      .finally(() => setTopicsLoading(false))
  }, [])

  const handleSort = (key: keyof InstructorLearnerItem) => {
    if (sortKey === key) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  const sortedLearners = learnersData
    ? sortLearners(learnersData.items, sortKey, sortDirection)
    : []

  const courseBarData = overviewData ? toCourseBarData(overviewData.courses) : []
  const topicBarData = topicsData ? toTopicBarData(topicsData.topics) : []

  return (
    <div className="page-container instructor-dashboard">
      <div className="page-header">
        <h1>Instructor Dashboard</h1>
        <p className="page-subtitle">
          Monitor learner engagement, cohort topic mastery, difficult concepts, and individual progress.
        </p>
      </div>

      {/* SECTION 1: Overview Cards */}
      <section className="dashboard-section">
        <h2>Cohort Overview</h2>
        {overviewError ? (
          <div className="card error-banner">{overviewError}</div>
        ) : overviewLoading ? (
          <div className="card loading-card">Loading cohort statistics…</div>
        ) : (
          <div className="overview-grid">
            <div className="card stat-card">
              <span className="stat-card-title">Total Learners</span>
              <span className="stat-card-value">{overviewData?.total_learners ?? '—'}</span>
              <span className="stat-card-desc">Enrolled student accounts</span>
            </div>
            <div className="card stat-card">
              <span className="stat-card-title">Active Learners</span>
              <span className="stat-card-value">{overviewData?.active_learners ?? '—'}</span>
              <span className="stat-card-desc">≥1 completed quiz</span>
            </div>
            <div className="card stat-card">
              <span className="stat-card-title">Completed Attempts</span>
              <span className="stat-card-value">{overviewData?.completed_attempts ?? '—'}</span>
              <span className="stat-card-desc">Total finished quizzes</span>
            </div>
            <div className="card stat-card">
              <span className="stat-card-title">Avg Quiz Score</span>
              <span className="stat-card-value">
                {formatPercent(overviewData?.avg_quiz_percentage)}
              </span>
              <span className="stat-card-desc">Across all completed attempts</span>
            </div>
            <div className="card stat-card">
              <span className="stat-card-title">Cohort Mastery</span>
              <span className="stat-card-value">
                {formatMastery(overviewData?.avg_mastery_attempted)}
              </span>
              <span className="stat-card-desc">Attempted topic probability</span>
            </div>
          </div>
        )}
      </section>

      {/* SECTION 2: Quiz Performance by Course */}
      <section className="dashboard-section">
        <h2>Quiz Performance by Course</h2>
        {overviewError ? (
          <div className="card error-banner">{overviewError}</div>
        ) : overviewLoading ? (
          <div className="card loading-card">Loading course performance…</div>
        ) : courseBarData.length === 0 ? (
          <div className="card empty-msg">No course performance data available.</div>
        ) : (
          <div className="card">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={courseBarData} margin={{ top: 16, right: 24, left: 0, bottom: 24 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="courseTitle" tick={{ fontSize: 12 }} />
                <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 12 }} />
                <Tooltip content={<CourseCustomTooltip />} />
                <Bar dataKey="value" fill="#4f46e5" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {/* SECTION 3: Topic Mastery Chart */}
      <section className="dashboard-section">
        <h2>Topic Competency Analytics</h2>
        {topicsError ? (
          <div className="card error-banner">{topicsError}</div>
        ) : topicsLoading ? (
          <div className="card loading-card">Loading topic mastery analytics…</div>
        ) : topicBarData.length === 0 ? (
          <div className="card empty-msg">No topic mastery data available.</div>
        ) : (
          <div className="card">
            <ResponsiveContainer width="100%" height={360}>
              <BarChart data={topicBarData} margin={{ top: 16, right: 24, left: 0, bottom: 48 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="label"
                  angle={-30}
                  textAnchor="end"
                  interval={0}
                  tick={{ fontSize: 11 }}
                  height={50}
                />
                <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 12 }} />
                <Tooltip content={<TopicCustomTooltip />} />
                <Bar dataKey="value" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {/* SECTION 4: Difficult Topics Ranking */}
      <section className="dashboard-section">
        <h2>Difficult Topics</h2>
        {topicsError ? (
          <div className="card error-banner">{topicsError}</div>
        ) : topicsLoading ? (
          <div className="card loading-card">Checking difficult topics…</div>
        ) : (
          <div className="card">
            <p className="table-subtext" style={{ marginBottom: '1rem' }}>
              Shown for topics attempted by at least{' '}
              {topicsData?.min_learners_for_difficult ?? 5} learners.
            </p>
            {topicsData && topicsData.difficult_topics.length > 0 ? (
              <div className="difficult-topics-list">
                {topicsData.difficult_topics.map((t) => (
                  <div key={t.topic_id} className="difficult-topic-card">
                    <div className="difficult-topic-info">
                      <h4>{t.topic_title}</h4>
                      <div className="table-subtext">{t.course_title}</div>
                    </div>
                    <div className="difficult-topic-metrics">
                      <div>
                        <strong>Avg Mastery:</strong> {formatMastery(t.avg_mastery)}
                      </div>
                      <div>
                        <strong>Weak Share:</strong> {formatPercent(t.weak_share_percent)}
                      </div>
                      <div>
                        <strong>Learners Attempted:</strong> {t.learners_attempted}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-msg">No topic has enough learners yet.</div>
            )}
          </div>
        )}
      </section>

      {/* SECTION 5: Learners Directory Table */}
      <section className="dashboard-section">
        <h2>Learners Directory</h2>
        {learnersError ? (
          <div className="card error-banner">{learnersError}</div>
        ) : learnersLoading ? (
          <div className="card loading-card">Loading learners directory…</div>
        ) : (
          <div className="card table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th
                    className="sortable"
                    onClick={() => handleSort('name')}
                    title="Click to sort by Name"
                  >
                    Name
                    <span className="sort-indicator">
                      {sortKey === 'name' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
                    </span>
                  </th>
                  <th
                    className="sortable"
                    onClick={() => handleSort('email')}
                    title="Click to sort by Email"
                  >
                    Email
                    <span className="sort-indicator">
                      {sortKey === 'email' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
                    </span>
                  </th>
                  <th
                    className="sortable"
                    onClick={() => handleSort('attempted_topics')}
                    title="Click to sort by Attempted Topics"
                  >
                    Attempted Topics
                    <span className="sort-indicator">
                      {sortKey === 'attempted_topics'
                        ? sortDirection === 'asc'
                          ? '▲'
                          : '▼'
                        : ''}
                    </span>
                  </th>
                  <th
                    className="sortable"
                    onClick={() => handleSort('avg_mastery_attempted')}
                    title="Click to sort by Avg Mastery"
                  >
                    Avg Mastery
                    <span className="sort-indicator">
                      {sortKey === 'avg_mastery_attempted'
                        ? sortDirection === 'asc'
                          ? '▲'
                          : '▼'
                        : ''}
                    </span>
                  </th>
                  <th
                    className="sortable"
                    onClick={() => handleSort('completed_attempts')}
                    title="Click to sort by Completed Quizzes"
                  >
                    Completed Quizzes
                    <span className="sort-indicator">
                      {sortKey === 'completed_attempts'
                        ? sortDirection === 'asc'
                          ? '▲'
                          : '▼'
                        : ''}
                    </span>
                  </th>
                  <th
                    className="sortable"
                    onClick={() => handleSort('avg_quiz_percentage')}
                    title="Click to sort by Avg Quiz %"
                  >
                    Avg Quiz %
                    <span className="sort-indicator">
                      {sortKey === 'avg_quiz_percentage'
                        ? sortDirection === 'asc'
                          ? '▲'
                          : '▼'
                        : ''}
                    </span>
                  </th>
                  <th
                    className="sortable"
                    onClick={() => handleSort('last_active')}
                    title="Click to sort by Last Active"
                  >
                    Last Active
                    <span className="sort-indicator">
                      {sortKey === 'last_active'
                        ? sortDirection === 'asc'
                          ? '▲'
                          : '▼'
                        : ''}
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedLearners.length > 0 ? (
                  sortedLearners.map((learner) => (
                    <tr key={learner.user_id}>
                      <td>
                        <strong>{learner.name}</strong>
                      </td>
                      <td>{learner.email}</td>
                      <td>
                        {learner.attempted_topics} / {learnersData?.total_topics ?? 24}
                      </td>
                      <td>{formatMastery(learner.avg_mastery_attempted)}</td>
                      <td>{learner.completed_attempts}</td>
                      <td>{formatPercent(learner.avg_quiz_percentage)}</td>
                      <td>{formatDate(learner.last_active)}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7} className="empty-msg">
                      No learners registered yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
