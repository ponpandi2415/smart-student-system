# Smart Students Data Management System

Final year project - Python Flask + SQLite + Bootstrap + Chart.js

## Run (Windows / Linux / Mac)
```
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

The database (`database.db`) and demo data are created automatically on first run.
To reset everything, delete `database.db` and run again.

## Demo logins
| Role    | Username   | Password   |
|---------|------------|------------|
| Admin   | admin      | admin123   |
| Teacher | teacher    | teacher123 |
| Student | 21CSE101   | 21CSE101   |

(Every student added through the app gets a login: roll number = username = password.)

## Modules
1. Login with role based access (Admin / Teacher / Student), hashed passwords
2. Student management: add, edit, delete, search by name / roll no, filter by department
3. Subject management
4. Attendance: subject and date wise, bulk mark, per-subject % and overall %
5. Marks: Internal 1, Internal 2, Model, Semester; grade and 10-point GPA
6. Dashboard: totals, average attendance, toppers, charts
7. Reports: CSV export (opens in Excel) for students and marks

## "Smart" features
- Low attendance alert (below 75%) on dashboard, report and student page, with one-click email draft
- Result prediction: next exam mark predicted by linear regression on previous exams
- Risk status per student: On track / Needs attention / High risk
- Performance trend chart per student
- Student portal: students see only their own data

## Database tables
students, users, subjects, attendance, marks (see SCHEMA in app.py)
- users.student_id -> students.id
- attendance.student_id -> students.id, attendance.subject_id -> subjects.id
- marks.student_id -> students.id, marks.subject_id -> subjects.id
- UNIQUE(student, subject, date) in attendance and UNIQUE(student, subject, exam) in marks

## Before submission
- Change `app.secret_key` in app.py
- Run with `debug=False`
