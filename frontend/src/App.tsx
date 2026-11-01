import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { Layout } from './components/Layout'
import { RequireAuth, RequireRole, RootRedirect } from './components/RouteGuards'
import { LoginPage } from './pages/Login'
import { RegisterPage } from './pages/Register'
import { LearnerDashboard } from './pages/LearnerDashboard'
import { InstructorDashboard } from './pages/InstructorDashboard'
import { QuizPickerPage } from './pages/QuizPicker'
import { AdaptiveQuizPage } from './pages/AdaptiveQuizPage'
import { FixedQuizPage } from './pages/FixedQuizPage'
import { NotFoundPage } from './pages/NotFound'
import './index.css'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<RootRedirect />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />

        {/* Authenticated routes */}
        <Route element={<RequireAuth />}>
          {/* Learner routes */}
          <Route element={<RequireRole allowedRole="learner" />}>
            <Route path="/dashboard" element={<LearnerDashboard />} />
            <Route path="/quiz" element={<QuizPickerPage />} />
            <Route path="/quiz/adaptive/:topicId" element={<AdaptiveQuizPage />} />
            <Route path="/quiz/fixed/:courseId" element={<FixedQuizPage />} />
          </Route>

          {/* Instructor routes */}
          <Route element={<RequireRole allowedRole="instructor" />}>
            <Route path="/instructor" element={<InstructorDashboard />} />
          </Route>
        </Route>

        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
