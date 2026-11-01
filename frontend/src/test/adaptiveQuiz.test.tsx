import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AdaptiveQuizPage } from '../pages/AdaptiveQuizPage'
import { TOKEN_STORAGE_KEY } from '../api/client'

function renderAdaptiveQuiz(topicId = '10') {
  return render(
    <MemoryRouter initialEntries={[`/quiz/adaptive/${topicId}`]}>
      <Routes>
        <Route path="/quiz/adaptive/:topicId" element={<AdaptiveQuizPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('Adaptive Quiz Flow', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(TOKEN_STORAGE_KEY, 'test-learner-jwt')
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders Question 1 of 8, submits answer with correct payload, displays feedback, and shows final result card', async () => {
    const user = userEvent.setup()

    const mockFetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      // 1. Start adaptive quiz
      if (url.includes('/api/quiz/adaptive/start')) {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({
            attempt_id: 77,
            topic_id: 10,
            mode: 'adaptive',
            total_questions: 8,
            question_number: 1,
            resumed: false,
            question: {
              question_id: 101,
              topic_id: 10,
              question_text: 'What layer does IP operate at?',
              option_a: 'Transport',
              option_b: 'Network',
              option_c: 'Data Link',
              option_d: 'Application',
            },
          }),
        })
      }

      // 2. Answer question 1
      if (url.includes('/api/quiz/adaptive/77/answer')) {
        const body = JSON.parse(init?.body as string)

        if (body.question_id === 101) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              attempt_id: 77,
              question_id: 101,
              is_correct: true,
              correct_answer: 'B',
              explanation: 'IP is the primary protocol in the Network layer.',
              question_number: 1,
              finished: false,
              next_question: {
                question_id: 102,
                topic_id: 10,
                question_text: 'What protocol resolves IP to MAC?',
                option_a: 'DNS',
                option_b: 'ARP',
                option_c: 'DHCP',
                option_d: 'BGP',
              },
              result: null,
            }),
          })
        }

        // 3. Answer question 2 (finishing quiz)
        if (body.question_id === 102) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              attempt_id: 77,
              question_id: 102,
              is_correct: true,
              correct_answer: 'B',
              explanation: 'ARP resolves network layer addresses to link layer addresses.',
              question_number: 2,
              finished: true,
              next_question: null,
              result: {
                attempt_id: 77,
                topic_id: 10,
                score: 2,
                total_questions: 8,
                percentage: 25.0,
                correct_answers: 2,
                incorrect_answers: 0,
                mastery_before: 0.15,
                mastery_after: 0.65,
                status: 'developing',
              },
            }),
          })
        }
      }

      return Promise.reject(new Error(`Unhandled url: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    renderAdaptiveQuiz('10')

    // Initial render: Question 1 of 8
    await waitFor(() => {
      expect(screen.getByText(/Question 1 of 8/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/What layer does IP operate at\?/i)).toBeInTheDocument()

    // Submit button should be disabled before an option is selected
    const submitBtn = screen.getByRole('button', { name: /submit answer/i })
    expect(submitBtn).toBeDisabled()

    // Select option B
    const optionB = screen.getByLabelText(/Network/i)
    await user.click(optionB)
    expect(submitBtn).toBeEnabled()

    // Submit question 1 answer
    await user.click(submitBtn)

    // Verify correct submission payload
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/quiz/adaptive/77/answer'),
        expect.objectContaining({
          body: JSON.stringify({
            question_id: 101,
            selected_answer: 'B',
          }),
        })
      )
    })

    // Feedback should be visible
    expect(screen.getByText(/Correct!/i)).toBeInTheDocument()
    expect(screen.getByText(/Correct answer:/i)).toBeInTheDocument()
    expect(screen.getByText(/IP is the primary protocol in the Network layer/i)).toBeInTheDocument()

    // Click Next question
    const nextBtn = screen.getByRole('button', { name: /next question/i })
    await user.click(nextBtn)

    // Second question rendered
    await waitFor(() => {
      expect(screen.getByText(/Question 2 of 8/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/What protocol resolves IP to MAC\?/i)).toBeInTheDocument()

    // Select Option B (ARP) and submit
    const optionArp = screen.getByLabelText(/ARP/i)
    await user.click(optionArp)
    const submitBtn2 = screen.getByRole('button', { name: /submit answer/i })
    await user.click(submitBtn2)

    // Result card appears
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 2, name: /quiz complete!/i })).toBeInTheDocument()
    })

    // Score, percentage, and mastery transition displayed
    expect(screen.getByText('2 / 8')).toBeInTheDocument()
    expect(screen.getByText('25%')).toBeInTheDocument()
    expect(screen.getByText(/15\.0% → 65\.0%/)).toBeInTheDocument()
    expect(screen.getByText(/developing/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to dashboard/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /quiz another topic/i })).toBeInTheDocument()
  })

  it('handles adaptive 409 on answer by displaying the error message and the Reload button', async () => {
    const user = userEvent.setup()

    let startCallCount = 0
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/quiz/adaptive/start')) {
        startCallCount += 1
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            attempt_id: 88,
            topic_id: 10,
            mode: 'adaptive',
            total_questions: 8,
            question_number: 1,
            resumed: true,
            question: {
              question_id: 105,
              topic_id: 10,
              question_text: 'Sample question text?',
              option_a: 'Opt A',
              option_b: 'Opt B',
              option_c: 'Opt C',
              option_d: 'Opt D',
            },
          }),
        })
      }

      if (url.includes('/api/quiz/adaptive/88/answer')) {
        return Promise.resolve({
          ok: false,
          status: 409,
          statusText: 'Conflict',
          json: async () => ({
            detail: 'Attempt 88 is not an in-progress adaptive quiz.',
          }),
        })
      }

      return Promise.reject(new Error(`Unhandled url: ${url}`))
    })
    vi.stubGlobal('fetch', mockFetch)

    renderAdaptiveQuiz('10')

    await waitFor(() => {
      expect(screen.getByText(/Question 1 of 8/i)).toBeInTheDocument()
    })

    // Select option A and submit
    const optionA = screen.getByLabelText(/Opt A/i)
    await user.click(optionA)
    const submitBtn = screen.getByRole('button', { name: /submit answer/i })
    await user.click(submitBtn)

    // 409 conflict message and reload button appear
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        /attempt 88 is not an in-progress adaptive quiz/i
      )
    })

    const reloadBtn = screen.getByRole('button', { name: /reload quiz/i })
    expect(reloadBtn).toBeInTheDocument()

    // Clicking Reload re-calls start
    await user.click(reloadBtn)

    await waitFor(() => {
      expect(startCallCount).toBe(2)
      expect(screen.getByText(/Question 1 of 8/i)).toBeInTheDocument()
    })
  })
})

