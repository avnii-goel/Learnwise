import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { LearnerDashboard } from '../pages/LearnerDashboard'
import {
  formatMastery,
  toRadarData,
  toTrendData,
} from '../lib/formatters'
import type {
  CourseProgressItem,
  LearnerDashboardResponse,
  LearnerTrendsResponse,
  MasteryProgressTrendPoint,
  QuizHistoryResponse,
  QuizScoreTrendPoint,
  RecommendationResponse,
} from '../api/types'

// Stub Recharts per spec
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  RadarChart: ({
    data,
    children,
  }: {
    data?: unknown
    children?: React.ReactNode
  }) => (
    <div data-testid="radar-chart" data-chart={JSON.stringify(data)}>
      {children}
    </div>
  ),
  PolarGrid: () => <div data-testid="polar-grid" />,
  PolarAngleAxis: () => <div data-testid="polar-angle-axis" />,
  PolarRadiusAxis: () => <div data-testid="polar-radius-axis" />,
  Radar: () => <div data-testid="radar" />,
  LineChart: ({
    data,
    children,
  }: {
    data?: unknown
    children?: React.ReactNode
  }) => (
    <div data-testid="line-chart" data-chart={JSON.stringify(data)}>
      {children}
    </div>
  ),
  Line: () => <div data-testid="line" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
}))

describe('Learner Dashboard & Helpers', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('learnwise_token', 'test-jwt')
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // TEST 1: toRadarData with worked example
  it('1. toRadarData with worked example: converts mastery to scaled percent, handles null, truncates long titles', () => {
    const course: CourseProgressItem = {
      course_id: 1,
      course_title: 'Computer Networks',
      total_topics: 4,
      attempted_topics: 3,
      progress_percent: 75.0,
      avg_mastery_attempted: 0.5482,
      topics: [
        {
          topic_id: 1,
          topic_title: 'OSPF Protocol',
          order: 1,
          mastery_probability: 0.85,
          status: 'strong',
          attempted: true,
        },
        {
          topic_id: 2,
          topic_title: 'Subnetting Math',
          order: 2,
          mastery_probability: 0.646,
          status: 'developing',
          attempted: true,
        },
        {
          topic_id: 3,
          topic_title: 'DNS Resolution',
          order: 3,
          mastery_probability: 0.1486,
          status: 'weak',
          attempted: true,
        },
        {
          topic_id: 4,
          topic_title: 'Software Defined Networking and Virtualization',
          order: 4,
          mastery_probability: null,
          status: 'not_attempted',
          attempted: false,
        },
      ],
    }

    const radar = toRadarData(course)
    expect(radar).toHaveLength(4)

    // T1: 0.85 -> 85
    expect(radar[0].mastery).toBe(85)
    expect(radar[0].attempted).toBe(true)

    // T2: 0.646 -> 64.6
    expect(radar[1].mastery).toBe(64.6)
    expect(radar[1].attempted).toBe(true)

    // T3: 0.1486 -> 14.9
    expect(radar[2].mastery).toBe(14.9)
    expect(radar[2].attempted).toBe(true)

    // T4: null -> 0, attempted: false, truncated to 14 chars + "…"
    expect(radar[3].mastery).toBe(0)
    expect(radar[3].attempted).toBe(false)
    expect(radar[3].topic).toBe('Software Defin…')
    expect(radar[3].fullTitle).toBe(
      'Software Defined Networking and Virtualization'
    )
  })

  // TEST 2: toTrendData
  it('2. toTrendData: mastery_progress scaled with 1 decimal, quiz_scores pass through', () => {
    const masteryPoints: MasteryProgressTrendPoint[] = [
      { attempt_id: 1, date: '2026-10-30T10:00:00Z', avg_mastery: 0.646 },
      { attempt_id: 2, date: '2026-10-31T12:00:00Z', avg_mastery: 0.3973 },
      { attempt_id: 3, date: '2026-11-01T14:00:00Z', avg_mastery: 0.5482 },
    ]

    const trendMastery = toTrendData(masteryPoints, 'avg_mastery')
    expect(trendMastery.map((p) => p.value)).toEqual([64.6, 39.7, 54.8])

    const quizPoints: QuizScoreTrendPoint[] = [
      { attempt_id: 1, date: '2026-10-30T10:00:00Z', mode: 'fixed', percentage: 75.0 },
      { attempt_id: 2, date: '2026-10-31T12:00:00Z', mode: 'adaptive', percentage: 87.5 },
    ]

    const trendQuiz = toTrendData(quizPoints, 'percentage')
    expect(trendQuiz.map((p) => p.value)).toEqual([75.0, 87.5])
  })

  // TEST 3: formatMastery
  it('3. formatMastery formats 0.5482 as "54.8%" and null as "—"', () => {
    expect(formatMastery(0.5482)).toBe('54.8%')
    expect(formatMastery(null)).toBe('—')
    expect(formatMastery(undefined)).toBe('—')
  })

  // TEST 4: Dashboard empty state
  it('4. Dashboard empty state: shows "Take your first quiz" and friendly empty messages without crashing', async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/me/history')) {
        const resp: QuizHistoryResponse = { items: [] }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/dashboard/me/trends')) {
        const resp: LearnerTrendsResponse = { quiz_scores: [], mastery_progress: [] }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/recommendations/me')) {
        const resp: RecommendationResponse = {
          request_id: '12345678-1234-5678-1234-567812345678',
          strategy: 'hybrid',
          collaborative_available: false,
          items: [],
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/dashboard/me')) {
        const resp: LearnerDashboardResponse = {
          overview: {
            total_topics: 24,
            attempted_topics: 0,
            progress_percent: 0.0,
            avg_mastery_attempted: null,
            status_counts: { strong: 0, developing: 0, weak: 0, not_attempted: 24 },
            completed_quizzes: 0,
          },
          courses: [],
          strengths: [],
          weaknesses: [],
          current_path: [],
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    render(
      <MemoryRouter>
        <LearnerDashboard />
      </MemoryRouter>
    )

    // Verify prominent empty card
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { level: 2, name: /take your first quiz/i })
      ).toBeInTheDocument()
    })

    // Friendly empty messages rendered across sections
    expect(screen.getByText(/No strong topics yet\./i)).toBeInTheDocument()
    expect(screen.getByText(/No weak topics — keep it up!/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Your path appears once you've viewed recommendations after a quiz\./i)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/No recommendations yet — take a quiz so we can see where you need help\./i)
    ).toBeInTheDocument()
    expect(
      screen.getAllByText(/Complete a quiz to see your trends\./i)
    ).toHaveLength(2)
    expect(screen.getByText(/No completed quizzes yet\./i)).toBeInTheDocument()
  })

  // TEST 5: Dashboard worked example
  it('5. Dashboard worked example shows "12.5%", "54.8%", and strength/weakness topic titles', async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/me/history')) {
        const resp: QuizHistoryResponse = { items: [] }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/dashboard/me/trends')) {
        const resp: LearnerTrendsResponse = { quiz_scores: [], mastery_progress: [] }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/recommendations/me')) {
        const resp: RecommendationResponse = {
          request_id: '12345678-1234-5678-1234-567812345678',
          strategy: 'hybrid',
          collaborative_available: false,
          items: [],
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/dashboard/me')) {
        const resp: LearnerDashboardResponse = {
          overview: {
            total_topics: 24,
            attempted_topics: 3,
            progress_percent: 12.5,
            avg_mastery_attempted: 0.5482,
            status_counts: { strong: 1, developing: 1, weak: 1, not_attempted: 21 },
            completed_quizzes: 3,
          },
          courses: [
            {
              course_id: 1,
              course_title: 'Computer Networks',
              total_topics: 24,
              attempted_topics: 3,
              progress_percent: 12.5,
              avg_mastery_attempted: 0.5482,
              topics: [
                {
                  topic_id: 1,
                  topic_title: 'OSPF Routing',
                  order: 1,
                  mastery_probability: 0.85,
                  status: 'strong',
                  attempted: true,
                },
                {
                  topic_id: 2,
                  topic_title: 'TCP Flow Control',
                  order: 2,
                  mastery_probability: 0.646,
                  status: 'developing',
                  attempted: true,
                },
                {
                  topic_id: 3,
                  topic_title: 'Subnet Masking',
                  order: 3,
                  mastery_probability: 0.1486,
                  status: 'weak',
                  attempted: true,
                },
              ],
            },
          ],
          strengths: [
            {
              topic_id: 1,
              topic_title: 'OSPF Routing',
              course_title: 'Computer Networks',
              mastery_probability: 0.85,
            },
          ],
          weaknesses: [
            {
              topic_id: 3,
              topic_title: 'Subnet Masking',
              course_title: 'Computer Networks',
              mastery_probability: 0.1486,
            },
          ],
          current_path: [],
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    render(
      <MemoryRouter>
        <LearnerDashboard />
      </MemoryRouter>
    )

    // Progress 12.5% and Avg Mastery 54.8%
    await waitFor(() => {
      expect(screen.getByText('12.5%')).toBeInTheDocument()
    })
    expect(screen.getByText('54.8%')).toBeInTheDocument()

    // Strengths and weaknesses topic titles
    expect(screen.getByText('OSPF Routing')).toBeInTheDocument()
    expect(screen.getByText('Subnet Masking')).toBeInTheDocument()
  })

  // TEST 6: Recommendations panel StrictMode guard & impression click
  it('6. Recommendations in StrictMode: called exactly once, shows reason, link has target="_blank" and rel noopener, click triggers impression click endpoint', async () => {
    const user = userEvent.setup()

    let recCallCount = 0
    let clickCalledWith: string | null = null

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/me/history')) {
        const resp: QuizHistoryResponse = { items: [] }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/dashboard/me/trends')) {
        const resp: LearnerTrendsResponse = { quiz_scores: [], mastery_progress: [] }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/recommendations/impressions/')) {
        clickCalledWith = url
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            impression_id: 401,
            resource_url: 'https://example.com/subnetting',
            clicked_at: '2026-11-01T12:00:00Z',
          }),
        })
      }
      if (url.includes('/api/recommendations/me')) {
        recCallCount += 1
        const resp: RecommendationResponse = {
          request_id: 'rec-123',
          strategy: 'hybrid',
          collaborative_available: false,
          items: [
            {
              impression_id: 401,
              rank: 1,
              resource: {
                id: 10,
                title: 'Practical Subnetting Primer',
                description: 'Detailed tutorial',
                resource_type: 'article',
                url: 'https://example.com/subnetting',
                difficulty: 'beginner',
              },
              topic: { id: 3, title: 'Subnetting' },
              score: 0.92,
              mastery: 0.1486,
              status: 'weak',
              reason: 'Recommended because you struggled with Subnetting questions on your last quiz.',
              components: { need: 0.9, semantic: 0.8, difficulty_fit: 1.0, collaborative: 0.0 },
            },
          ],
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/dashboard/me')) {
        const resp: LearnerDashboardResponse = {
          overview: {
            total_topics: 24,
            attempted_topics: 1,
            progress_percent: 4.2,
            avg_mastery_attempted: 0.1486,
            status_counts: { strong: 0, developing: 0, weak: 1, not_attempted: 23 },
            completed_quizzes: 1,
          },
          courses: [],
          strengths: [],
          weaknesses: [],
          current_path: [],
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    render(
      <StrictMode>
        <MemoryRouter>
          <LearnerDashboard />
        </MemoryRouter>
      </StrictMode>
    )

    // In StrictMode, ref guard ensures exactly one call to POST /api/recommendations/me
    await waitFor(() => {
      expect(
        screen.getByText(
          /Recommended because you struggled with Subnetting questions on your last quiz\./i
        )
      ).toBeInTheDocument()
    })
    expect(recCallCount).toBe(1)

    // Link attributes
    const link = screen.getByRole('link', { name: /open resource/i })
    expect(link).toHaveAttribute('href', 'https://example.com/subnetting')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toContain('noopener')

    // Click link fires POST /api/recommendations/impressions/401/click
    await user.click(link)

    await waitFor(() => {
      expect(clickCalledWith).toContain('/api/recommendations/impressions/401/click')
    })
  })

  // TEST 7: Isolation
  it('7. Isolation: if recommendations returns 500, overview and history still render, and error message is displayed', async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/me/history')) {
        const resp: QuizHistoryResponse = {
          items: [
            {
              attempt_id: 55,
              mode: 'fixed',
              course_title: 'Computer Networks',
              topic_title: null,
              score: 18,
              total_questions: 20,
              percentage: 90.0,
              completed_at: '2026-10-31T15:00:00Z',
            },
          ],
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/dashboard/me/trends')) {
        const resp: LearnerTrendsResponse = { quiz_scores: [], mastery_progress: [] }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/recommendations/me')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: 'Internal Server Error',
          json: async () => ({ detail: 'Recommender microservice down' }),
        })
      }
      if (url.includes('/api/dashboard/me')) {
        const resp: LearnerDashboardResponse = {
          overview: {
            total_topics: 24,
            attempted_topics: 5,
            progress_percent: 20.8,
            avg_mastery_attempted: 0.72,
            status_counts: { strong: 3, developing: 2, weak: 0, not_attempted: 19 },
            completed_quizzes: 2,
          },
          courses: [],
          strengths: [],
          weaknesses: [],
          current_path: [],
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    render(
      <MemoryRouter>
        <LearnerDashboard />
      </MemoryRouter>
    )

    // Overview section still renders
    await waitFor(() => {
      expect(screen.getByText('20.8%')).toBeInTheDocument()
    })
    expect(screen.getByText('72.0%')).toBeInTheDocument()

    // History section still renders
    expect(screen.getByText('18 / 20')).toBeInTheDocument()
    expect(screen.getByText('90.0%')).toBeInTheDocument()

    // Recommendations section displays error message
    expect(
      screen.getByText(/Recommender microservice down/i)
    ).toBeInTheDocument()
  })

  // TEST A1: Stale current_path refetch
  it('A1. Stale current_path fix: refetches /me once when recommendations succeed, showing updated path, with exactly 2 /me calls and 1 recommendation call under StrictMode', async () => {
    let dashboardMeCalls = 0
    let recommendationsCalls = 0

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/me/history')) {
        const resp: QuizHistoryResponse = { items: [] }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/dashboard/me/trends')) {
        const resp: LearnerTrendsResponse = { quiz_scores: [], mastery_progress: [] }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/recommendations/me')) {
        recommendationsCalls += 1
        const resp: RecommendationResponse = {
          request_id: 'rec-test-uuid',
          strategy: 'hybrid',
          collaborative_available: true,
          items: [
            {
              impression_id: 991,
              rank: 1,
              resource: {
                id: 101,
                title: 'Deep Dive into Subnetting',
                description: 'CIDR and subnet masks',
                resource_type: 'article',
                url: 'https://example.com/subnetting',
                difficulty: 'medium',
              },
              topic: { id: 3, title: 'Subnetting' },
              score: 0.95,
              mastery: 0.1486,
              status: 'weak',
              reason: 'High need topic',
              components: { need: 0.9, semantic: 0.8, difficulty_fit: 0.85, collaborative: 0.0 },
            },
          ],
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      if (url.includes('/api/dashboard/me')) {
        dashboardMeCalls += 1
        // First call returns empty current_path; second call returns populated current_path
        const currentPath =
          dashboardMeCalls === 1
            ? []
            : [
                {
                  rank: 1,
                  topic_id: 3,
                  topic_title: 'Subnetting',
                  course_title: 'Computer Networks',
                  status: 'weak',
                  mastery_probability: 0.1486,
                },
              ]

        const resp: LearnerDashboardResponse = {
          overview: {
            total_topics: 24,
            attempted_topics: 1,
            progress_percent: 4.2,
            avg_mastery_attempted: 0.1486,
            status_counts: { strong: 0, developing: 0, weak: 1, not_attempted: 23 },
            completed_quizzes: 1,
          },
          courses: [],
          strengths: [],
          weaknesses: [],
          current_path: currentPath,
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => resp })
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    render(
      <StrictMode>
        <MemoryRouter>
          <LearnerDashboard />
        </MemoryRouter>
      </StrictMode>
    )

    // Wait for the refetched current_path to populate and display the topic title
    await waitFor(() => {
      expect(screen.getByText('Subnetting')).toBeInTheDocument()
    })

    // Verify /api/dashboard/me was called exactly twice (initial load + refetch after recs)
    expect(dashboardMeCalls).toBe(2)
    // Verify POST /api/recommendations/me was called exactly once despite StrictMode
    expect(recommendationsCalls).toBe(1)
  })
})
