import { Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthProvider'
import { RequireAuth, RequireRole } from './auth/guards'
import { Layout } from './components/Layout'
import { ChangePasswordPage } from './pages/ChangePasswordPage'
import { CourseFilePage } from './pages/CourseFilePage'
import { FlagsPage } from './pages/FlagsPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { QueriesPage } from './pages/QueriesPage'
import { QueryPage } from './pages/QueryPage'
import { ChecklistPage } from './pages/setup/ChecklistPage'
import { CourseFilesSetupPage } from './pages/setup/CourseFilesSetupPage'
import { DeadlinesPage } from './pages/setup/DeadlinesPage'
import { DepartmentsPage } from './pages/setup/DepartmentsPage'
import { SemestersPage } from './pages/setup/SemestersPage'
import { SetupLayout } from './pages/setup/SetupLayout'
import { SubjectsPage } from './pages/setup/SubjectsPage'
import { UsersPage } from './pages/setup/UsersPage'
import { WeightsPage } from './pages/setup/WeightsPage'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/change-password" element={<ChangePasswordPage />} />
          <Route element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="course-files/:id" element={<CourseFilePage />} />
            <Route path="queries" element={<QueriesPage />} />
            <Route path="queries/:id" element={<QueryPage />} />
            <Route element={<RequireRole roles={['HOD', 'DEAN']} />}>
              <Route path="flags" element={<FlagsPage />} />
            </Route>
            <Route path="setup" element={<SetupLayout />}>
              <Route path="departments" element={<DepartmentsPage />} />
              <Route path="semesters" element={<SemestersPage />} />
              <Route path="semesters/:id/deadlines" element={<DeadlinesPage />} />
              <Route path="subjects" element={<SubjectsPage />} />
              <Route path="checklist" element={<ChecklistPage />} />
              <Route path="users" element={<UsersPage />} />
              <Route path="course-files" element={<CourseFilesSetupPage />} />
              <Route path="weights" element={<WeightsPage />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </AuthProvider>
  )
}
