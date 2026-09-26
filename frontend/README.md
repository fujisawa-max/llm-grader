# Instructor Web UI

Next.js App Router UI for the existing FastAPI domain API. Set
`NEXT_PUBLIC_API_BASE_URL` to the backend `/api/v1` URL and
`NEXT_PUBLIC_STUDENT_ID` only when viewing the optional student result
projection. Teacher and admin pages authenticate with the HttpOnly session
cookie issued by `/auth/login`; no development user ID is selected in the
browser. Grading remains in the separate worker.
