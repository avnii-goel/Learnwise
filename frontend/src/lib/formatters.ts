import type {
  CourseProgressItem,
  InstructorCourseOverview,
  InstructorLearnerItem,
  InstructorTopicItem,
  MasteryProgressTrendPoint,
  QuizScoreTrendPoint,
} from '../api/types'

/**
 * Formats a 0..100 percentage number.
 * Returns "—" for null or undefined.
 */
export function formatPercent(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined) {
    return '—'
  }
  return `${x.toFixed(digits)}%`
}

/**
 * Formats a 0..1 mastery probability to percentage string.
 * Example: 0.5482 -> "54.8%". Returns "—" for null.
 */
export function formatMastery(p: number | null | undefined): string {
  if (p === null || p === undefined) {
    return '—'
  }
  return `${(p * 100).toFixed(1)}%`
}

/**
 * Formats an ISO datetime string into a clean, short human-readable date.
 * Avoids timezone shifts by using standard date display in user's locale.
 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return String(iso)
  return d.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

/**
 * Human-friendly label for competency status.
 */
export function statusLabel(status: string): string {
  switch (status) {
    case 'strong':
      return 'Strong'
    case 'developing':
      return 'Developing'
    case 'weak':
      return 'Weak'
    case 'not_attempted':
      return 'Not attempted'
    default:
      return status.replace(/_/g, ' ')
  }
}

/**
 * Color mapping for competency status:
 * strong green, developing amber, weak red, not_attempted grey.
 */
export function statusColor(status: string): string {
  switch (status) {
    case 'strong':
      return '#16a34a'
    case 'developing':
      return '#d97706'
    case 'weak':
      return '#dc2626'
    case 'not_attempted':
    default:
      return '#64748b'
  }
}

export interface RadarDataPoint {
  topic: string
  fullTitle: string
  mastery: number
  attempted: boolean
}

/**
 * Converts course progress items to Recharts RadarChart data.
 * Truncates labels to 14 chars + "…".
 * Rounds mastery percentage to 1 decimal; sets 0 if null.
 */
export function toRadarData(course: CourseProgressItem): RadarDataPoint[] {
  return course.topics.map((t) => {
    const fullTitle = t.topic_title
    const topic = fullTitle.length > 14 ? `${fullTitle.slice(0, 14)}…` : fullTitle

    let mastery = 0
    if (t.mastery_probability !== null && t.mastery_probability !== undefined) {
      mastery = Math.round(t.mastery_probability * 1000) / 10
    }

    return {
      topic,
      fullTitle,
      mastery,
      attempted: t.attempted,
    }
  })
}

export interface TrendDataPoint {
  date: string
  value: number
  rawDate: string
}

/**
 * Maps trend points to Recharts LineChart data.
 * mastery_progress (0..1) -> scaled to 0..100 with 1 decimal.
 * quiz_scores (0..100) -> percentage passes through directly.
 */
export function toTrendData(
  points: QuizScoreTrendPoint[] | MasteryProgressTrendPoint[],
  key: 'percentage' | 'avg_mastery'
): TrendDataPoint[] {
  return points.map((p) => {
    let value = 0
    if (key === 'avg_mastery' && 'avg_mastery' in p) {
      value = Math.round(p.avg_mastery * 1000) / 10
    } else if (key === 'percentage' && 'percentage' in p) {
      value = Math.round(p.percentage * 10) / 10
    }

    return {
      date: formatDate(p.date),
      value,
      rawDate: p.date,
    }
  })
}

// --- Instructor Dashboard Pure Helpers ---

/**
 * Pure helper for sorting instructor learners table.
 * - Null values always sort last in both asc and desc directions.
 * - Name sort is case-insensitive.
 * - Returns a new sorted array.
 */
export function sortLearners(
  items: InstructorLearnerItem[],
  key: keyof InstructorLearnerItem,
  direction: 'asc' | 'desc'
): InstructorLearnerItem[] {
  return [...items].sort((a, b) => {
    const valA = a[key]
    const valB = b[key]

    // Null values always sort last regardless of direction
    if (valA === null && valB === null) return 0
    if (valA === null) return 1
    if (valB === null) return -1

    let cmp = 0
    if (typeof valA === 'string' && typeof valB === 'string') {
      cmp = valA.toLowerCase().localeCompare(valB.toLowerCase())
    } else if (typeof valA === 'number' && typeof valB === 'number') {
      cmp = valA - valB
    } else {
      cmp = String(valA).toLowerCase().localeCompare(String(valB).toLowerCase())
    }

    return direction === 'asc' ? cmp : -cmp
  })
}

export interface TopicBarDataPoint {
  label: string
  fullTitle: string
  courseTitle: string
  value: number | null
  learnersAttempted: number
  accuracy: number | null
  weakShare: number | null
}

/**
 * Converts instructor topics to Recharts BarChart data.
 * Truncates labels to ~16 chars + '…'.
 * Converts avg_mastery to scaled percentage rounded to 1 decimal place, or null if null.
 */
export function toTopicBarData(topics: InstructorTopicItem[]): TopicBarDataPoint[] {
  return topics.map((t) => {
    const fullTitle = t.topic_title
    const label = fullTitle.length > 16 ? `${fullTitle.slice(0, 16)}…` : fullTitle
    const value =
      t.avg_mastery !== null && t.avg_mastery !== undefined
        ? Math.round(t.avg_mastery * 1000) / 10
        : null

    return {
      label,
      fullTitle,
      courseTitle: t.course_title,
      value,
      learnersAttempted: t.learners_attempted,
      accuracy: t.accuracy_percent,
      weakShare: t.weak_share_percent,
    }
  })
}

export interface CourseBarDataPoint {
  courseId: number
  courseTitle: string
  label: string
  value: number | null
  activeLearners: number
  completedAttempts: number
}

/**
 * Converts instructor course overview list to Recharts BarChart data.
 * Converts avg_quiz_percentage to 1 decimal place, or null if null.
 */
export function toCourseBarData(courses: InstructorCourseOverview[]): CourseBarDataPoint[] {
  return courses.map((c) => ({
    courseId: c.course_id,
    courseTitle: c.course_title,
    label: c.course_title,
    value:
      c.avg_quiz_percentage !== null && c.avg_quiz_percentage !== undefined
        ? Math.round(c.avg_quiz_percentage * 10) / 10
        : null,
    activeLearners: c.active_learners,
    completedAttempts: c.completed_attempts,
  }))
}

