import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { InstructorDashboard } from '../pages/InstructorDashboard'
import {
  sortLearners,
  toCourseBarData,
  toTopicBarData,
} from '../lib/formatters'
import type {
  InstructorLearnerItem,
  InstructorLearnersResponse,
  InstructorOverviewResponse,
  InstructorTopicItem,
  InstructorTopicsResponse,
} from '../api/types'

// Stub Recharts per spec
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  BarChart: ({
    data,
    children,
  }: {
    data?: unknown
    children?: React.ReactNode
  }) => (
    <div data-testid="bar-chart" data-chart={JSON.stringify(data)}>
      {children}
    </div>
  ),
  Bar: () => <div data-testid="bar" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
}))

describe('Instructor Dashboard & Pure Helpers', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // TEST B1: sortLearners helper
  it('B1. sortLearners: sorts asc/desc, nulls last in both directions, case-insensitive name', () => {
    const items: InstructorLearnerItem[] = [
      {
        user_id: 1,
        name: 'bob',
        email: 'bob@example.com',
        attempted_topics: 2,
        avg_mastery_attempted: null,
        completed_attempts: 1,
        avg_quiz_percentage: 50.0,
        last_active: '2026-10-20T10:00:00Z',
      },
      {
        user_id: 2,
        name: 'Alice',
        email: 'alice@example.com',
        attempted_topics: 10,
        avg_mastery_attempted: 0.85,
        completed_attempts: 5,
        avg_quiz_percentage: 80.0,
        last_active: '2026-10-25T10:00:00Z',
      },
      {
        user_id: 3,
        name: 'charlie',
        email: 'charlie@example.com',
        attempted_topics: 5,
        avg_mastery_attempted: 0.45,
        completed_attempts: 3,
        avg_quiz_percentage: 65.0,
        last_active: null,
      },
    ]

    // Case-insensitive name sort asc
    const byNameAsc = sortLearners(items, 'name', 'asc')
    expect(byNameAsc.map((i) => i.name)).toEqual(['Alice', 'bob', 'charlie'])

    // Case-insensitive name sort desc
    const byNameDesc = sortLearners(items, 'name', 'desc')
    expect(byNameDesc.map((i) => i.name)).toEqual(['charlie', 'bob', 'Alice'])

    // Numerical sort with null: asc (non-nulls asc, nulls at end)
    const byMasteryAsc = sortLearners(items, 'avg_mastery_attempted', 'asc')
    expect(byMasteryAsc.map((i) => i.name)).toEqual(['charlie', 'Alice', 'bob'])
    expect(byMasteryAsc[2].avg_mastery_attempted).toBeNull()

    // Numerical sort with null: desc (non-nulls desc, nulls at end)
    const byMasteryDesc = sortLearners(items, 'avg_mastery_attempted', 'desc')
    expect(byMasteryDesc.map((i) => i.name)).toEqual(['Alice', 'charlie', 'bob'])
    expect(byMasteryDesc[2].avg_mastery_attempted).toBeNull()

    // String date sort with null: asc
    const byDateAsc = sortLearners(items, 'last_active', 'asc')
    expect(byDateAsc.map((i) => i.name)).toEqual(['bob', 'Alice', 'charlie'])
    expect(byDateAsc[2].last_active).toBeNull()

    // String date sort with null: desc
    const byDateDesc = sortLearners(items, 'last_active', 'desc')
    expect(byDateDesc.map((i) => i.name)).toEqual(['Alice', 'bob', 'charlie'])
    expect(byDateDesc[2].last_active).toBeNull()
  })

  // TEST B2: toTopicBarData worked example
  it('B2. toTopicBarData worked example: avg_mastery 0.5482 -> 54.8, null -> null; long titles truncated', () => {
    const topics: InstructorTopicItem[] = [
      {
        topic_id: 1,
        topic_title: 'OSI Model',
        course_id: 1,
        course_title: 'Computer Networks',
        learners_attempted: 3,
        avg_mastery: 0.5482,
        accuracy_percent: 83.3,
        weak_share_percent: 33.3,
        status_counts: { strong: 1, developing: 1, weak: 1 },
      },
      {
        topic_id: 2,
        topic_title: 'TCP/IP Protocol Suite',
        course_id: 1,
        course_title: 'Computer Networks',
        learners_attempted: 0,
        avg_mastery: null,
        accuracy_percent: null,
        weak_share_percent: null,
        status_counts: { strong: 0, developing: 0, weak: 0 },
      },
      {
        topic_id: 3,
        topic_title: 'Network Address Translation and Port Forwarding Techniques',
        course_id: 1,
        course_title: 'Computer Networks',
        learners_attempted: 10,
        avg_mastery: 0.725,
        accuracy_percent: 75.0,
        weak_share_percent: 10.0,
        status_counts: { strong: 6, developing: 3, weak: 1 },
      },
    ]

    const result = toTopicBarData(topics)
    expect(result).toHaveLength(3)

    // Worked example 0.5482 -> 54.8
    expect(result[0].value).toBe(54.8)
    expect(result[0].fullTitle).toBe('OSI Model')
    expect(result[0].label).toBe('OSI Model')

    // Null mastery -> null value
    expect(result[1].value).toBeNull()

    // Long title truncated to ~16 chars + '…'
    expect(result[2].fullTitle).toBe(
      'Network Address Translation and Port Forwarding Techniques'
    )
    expect(result[2].label).toBe('Network Address …')
    expect(result[2].label.length).toBeLessThanOrEqual(18)
    expect(result[2].value).toBe(72.5)

    // Test toCourseBarData pure helper
    const courseBar = toCourseBarData([
      {
        course_id: 1,
        course_title: 'Computer Networks',
        active_learners: 2,
        completed_attempts: 10,
        avg_quiz_percentage: 78.46,
      },
      {
        course_id: 2,
        course_title: 'Operating Systems',
        active_learners: 0,
        completed_attempts: 0,
        avg_quiz_percentage: null,
      },
    ])
    expect(courseBar[0].value).toBe(78.5)
    expect(courseBar[1].value).toBeNull()
  })

  // TEST B3: Instructor dashboard renders a mocked data set
  it('B3. Instructor dashboard renders a mocked data set: overview numbers, learners table, difficult topic with note, and topic chart stub receives mapped data', async () => {
    const mockOverview: InstructorOverviewResponse = {
      total_learners: 3,
      active_learners: 2,
      completed_attempts: 15,
      avg_quiz_percentage: 75.5,
      avg_mastery_attempted: 0.5482,
      courses: [
        {
          course_id: 1,
          course_title: 'Computer Networks',
          active_learners: 2,
          completed_attempts: 10,
          avg_quiz_percentage: 78.0,
        },
      ],
    }

    const mockLearners: InstructorLearnersResponse = {
      total_topics: 24,
      items: [
        {
          user_id: 101,
          name: 'Synthetic Learner 01',
          email: 'synthetic-01@synthetic.learnwise.test',
          attempted_topics: 24,
          avg_mastery_attempted: 0.825,
          completed_attempts: 12,
          avg_quiz_percentage: 84.5,
          last_active: '2026-10-31T18:00:00Z',
        },
        {
          user_id: 102,
          name: 'Synthetic Learner 02',
          email: 'synthetic-02@synthetic.learnwise.test',
          attempted_topics: 12,
          avg_mastery_attempted: 0.45,
          completed_attempts: 3,
          avg_quiz_percentage: 62.0,
          last_active: '2026-10-30T12:00:00Z',
        },
        {
          user_id: 103,
          name: 'Inactive Learner',
          email: 'inactive@example.com',
          attempted_topics: 0,
          avg_mastery_attempted: null,
          completed_attempts: 0,
          avg_quiz_percentage: null,
          last_active: null,
        },
      ],
    }

    const mockTopics: InstructorTopicsResponse = {
      min_learners_for_difficult: 5,
      topics: [
        {
          topic_id: 1,
          topic_title: 'OSI Model',
          course_id: 1,
          course_title: 'Computer Networks',
          learners_attempted: 3,
          avg_mastery: 0.5482,
          accuracy_percent: 83.3,
          weak_share_percent: 33.3,
          status_counts: { strong: 1, developing: 1, weak: 1 },
        },
      ],
      difficult_topics: [
        {
          topic_id: 3,
          topic_title: 'Subnetting',
          course_id: 1,
          course_title: 'Computer Networks',
          learners_attempted: 35,
          avg_mastery: 0.3214,
          accuracy_percent: 41.2,
          weak_share_percent: 68.6,
          status_counts: { strong: 2, developing: 9, weak: 24 },
        },
      ],
    }

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/instructor/overview')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockOverview })
      }
      if (url.includes('/api/dashboard/instructor/learners')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockLearners })
      }
      if (url.includes('/api/dashboard/instructor/topics')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockTopics })
      }
      return Promise.reject(new Error(`Unhandled: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    render(
      <MemoryRouter>
        <InstructorDashboard />
      </MemoryRouter>
    )

    // 1. Overview cards render numbers
    await waitFor(() => {
      expect(screen.getByText('75.5%')).toBeInTheDocument()
    })
    expect(screen.getByText('54.8%')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()

    // 2. Learners table renders all 3 rows
    expect(screen.getByText('Synthetic Learner 01')).toBeInTheDocument()
    expect(screen.getByText('Synthetic Learner 02')).toBeInTheDocument()
    expect(screen.getByText('Inactive Learner')).toBeInTheDocument()
    expect(screen.getByText('24 / 24')).toBeInTheDocument()
    expect(screen.getByText('0 / 24')).toBeInTheDocument()

    // 3. Difficult topic renders with min-learners note
    expect(screen.getByText('Subnetting')).toBeInTheDocument()
    expect(
      screen.getByText(/Shown for topics attempted by at least 5 learners\./i)
    ).toBeInTheDocument()
    expect(screen.getByText('32.1%')).toBeInTheDocument() // 0.3214 -> 32.1%

    // 4. Topic chart stub received mapped data (54.8% for OSI Model)
    const chartStubs = screen.getAllByTestId('bar-chart')
    expect(chartStubs.length).toBeGreaterThanOrEqual(2)
    const topicChart = chartStubs.find((c) =>
      c.getAttribute('data-chart')?.includes('OSI Model')
    )
    expect(topicChart).toBeDefined()
    expect(topicChart?.getAttribute('data-chart')).toContain('"value":54.8')
  })

  // TEST B4: Empty platform
  it('B4. Empty platform (0 learners, null averages, empty lists): "—" values and empty messages, no crash', async () => {
    const mockOverview: InstructorOverviewResponse = {
      total_learners: 0,
      active_learners: 0,
      completed_attempts: 0,
      avg_quiz_percentage: null,
      avg_mastery_attempted: null,
      courses: [],
    }

    const mockLearners: InstructorLearnersResponse = {
      total_topics: 24,
      items: [],
    }

    const mockTopics: InstructorTopicsResponse = {
      min_learners_for_difficult: 5,
      topics: [],
      difficult_topics: [],
    }

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/instructor/overview')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockOverview })
      }
      if (url.includes('/api/dashboard/instructor/learners')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockLearners })
      }
      if (url.includes('/api/dashboard/instructor/topics')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockTopics })
      }
      return Promise.reject(new Error(`Unhandled: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    render(
      <MemoryRouter>
        <InstructorDashboard />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
    })

    // Empty state messages render cleanly
    expect(
      screen.getByText(/No topic has enough learners yet\./i)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/No learners registered yet\./i)
    ).toBeInTheDocument()
  })

  // TEST B5: Isolation
  it('B5. Isolation: /topics returns 500 -> overview cards and learners table still render, topics section shows error; /learners 403 -> "Instructor access required" in that section only', async () => {
    const mockOverview: InstructorOverviewResponse = {
      total_learners: 10,
      active_learners: 8,
      completed_attempts: 25,
      avg_quiz_percentage: 70.0,
      avg_mastery_attempted: 0.65,
      courses: [],
    }

    // Subtest 1: /topics returns 500
    const mockFetch500 = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/instructor/overview')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockOverview })
      }
      if (url.includes('/api/dashboard/instructor/learners')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            total_topics: 24,
            items: [
              {
                user_id: 1,
                name: 'Test Student',
                email: 'test@student.com',
                attempted_topics: 5,
                avg_mastery_attempted: 0.6,
                completed_attempts: 2,
                avg_quiz_percentage: 75.0,
                last_active: null,
              },
            ],
          }),
        })
      }
      if (url.includes('/api/dashboard/instructor/topics')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: 'Internal Server Error',
          json: async () => ({ detail: 'Topics microservice error' }),
        })
      }
      return Promise.reject(new Error(`Unhandled: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch500)

    const { unmount } = render(
      <MemoryRouter>
        <InstructorDashboard />
      </MemoryRouter>
    )

    // Overview cards still render
    await waitFor(() => {
      expect(screen.getByText('70.0%')).toBeInTheDocument()
    })
    expect(screen.getByText('65.0%')).toBeInTheDocument()

    // Learners table still renders
    expect(screen.getByText('Test Student')).toBeInTheDocument()

    // Topics section shows error banner
    expect(
      screen.getAllByText(/Topics microservice error/i).length
    ).toBeGreaterThanOrEqual(1)

    unmount()

    // Subtest 2: /learners returns 403
    const mockFetch403 = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/instructor/overview')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockOverview })
      }
      if (url.includes('/api/dashboard/instructor/learners')) {
        return Promise.resolve({
          ok: false,
          status: 403,
          statusText: 'Forbidden',
          json: async () => ({ detail: 'Forbidden' }),
        })
      }
      if (url.includes('/api/dashboard/instructor/topics')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            min_learners_for_difficult: 5,
            topics: [],
            difficult_topics: [],
          }),
        })
      }
      return Promise.reject(new Error(`Unhandled: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch403)

    render(
      <MemoryRouter>
        <InstructorDashboard />
      </MemoryRouter>
    )

    // Overview cards still render
    await waitFor(() => {
      expect(screen.getByText('70.0%')).toBeInTheDocument()
    })

    // Learners section shows "Instructor access required"
    expect(screen.getByText('Instructor access required')).toBeInTheDocument()
  })

  // TEST B6: Clicking "Avg mastery" header reorders rows
  it('B6. Clicking the "Avg mastery" header reorders the rows, clicking again reverses them', async () => {
    const user = userEvent.setup()

    const mockOverview: InstructorOverviewResponse = {
      total_learners: 3,
      active_learners: 2,
      completed_attempts: 10,
      avg_quiz_percentage: 65.0,
      avg_mastery_attempted: 0.55,
      courses: [],
    }

    const mockLearners: InstructorLearnersResponse = {
      total_topics: 24,
      items: [
        {
          user_id: 1,
          name: 'Learner A',
          email: 'a@example.com',
          attempted_topics: 10,
          avg_mastery_attempted: 0.85,
          completed_attempts: 5,
          avg_quiz_percentage: 85.0,
          last_active: '2026-10-31T12:00:00Z',
        },
        {
          user_id: 2,
          name: 'Learner B',
          email: 'b@example.com',
          attempted_topics: 5,
          avg_mastery_attempted: 0.4,
          completed_attempts: 2,
          avg_quiz_percentage: 60.0,
          last_active: '2026-10-30T12:00:00Z',
        },
        {
          user_id: 3,
          name: 'Learner C',
          email: 'c@example.com',
          attempted_topics: 0,
          avg_mastery_attempted: null,
          completed_attempts: 0,
          avg_quiz_percentage: null,
          last_active: null,
        },
      ],
    }

    const mockTopics: InstructorTopicsResponse = {
      min_learners_for_difficult: 5,
      topics: [],
      difficult_topics: [],
    }

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/instructor/overview')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockOverview })
      }
      if (url.includes('/api/dashboard/instructor/learners')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockLearners })
      }
      if (url.includes('/api/dashboard/instructor/topics')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => mockTopics })
      }
      return Promise.reject(new Error(`Unhandled: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    render(
      <MemoryRouter>
        <InstructorDashboard />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Learner A')).toBeInTheDocument()
    })

    // Initially sorted by name asc: Learner A, Learner B, Learner C
    let rows = screen.getAllByRole('row')
    // row 0 is header
    expect(rows[1]).toHaveTextContent('Learner A')
    expect(rows[2]).toHaveTextContent('Learner B')
    expect(rows[3]).toHaveTextContent('Learner C')

    // Click "Avg Mastery" header -> sort asc: Learner B (0.4), Learner A (0.85), Learner C (null last)
    const masteryHeader = screen.getByRole('columnheader', { name: /Avg Mastery/i })
    await user.click(masteryHeader)

    rows = screen.getAllByRole('row')
    expect(rows[1]).toHaveTextContent('Learner B')
    expect(rows[2]).toHaveTextContent('Learner A')
    expect(rows[3]).toHaveTextContent('Learner C')

    // Click "Avg Mastery" header again -> reverses to desc: Learner A (0.85), Learner B (0.4), Learner C (null last)
    await user.click(masteryHeader)

    rows = screen.getAllByRole('row')
    expect(rows[1]).toHaveTextContent('Learner A')
    expect(rows[2]).toHaveTextContent('Learner B')
    expect(rows[3]).toHaveTextContent('Learner C')
  })
})
