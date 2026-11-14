"""
Smart Students Data Management System
Final Year Project - Flask + SQLite
Roles: admin, teacher, student
"""
import csv
import io
import os
import random
import sqlite3
from datetime import date, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-before-submission")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
EXAM_TYPES = ["Internal 1", "Internal 2", "Model", "Semester"]
ATT_LIMIT = 75  # minimum attendance percentage


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    dept TEXT,
    year INTEGER,
    email TEXT,
    phone TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','teacher','student')),
    student_id INTEGER,
    FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    dept TEXT,
    semester INTEGER
);
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Present','Absent')),
    UNIQUE(student_id, subject_id, date),
    FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    exam_type TEXT NOT NULL,
    marks REAL NOT NULL,
    UNIQUE(student_id, subject_id, exam_type),
    FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed_demo_data(db)
    db.commit()
    db.close()


def seed_demo_data(db):
    """Demo data so the project works the moment you run it."""
    random.seed(7)
    db.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
               ("admin", generate_password_hash("admin123"), "admin"))
    db.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
               ("teacher", generate_password_hash("teacher123"), "teacher"))
    subjects = ["Data Structures", "DBMS", "Operating Systems",
                "Computer Networks", "Python Programming"]
    for s in subjects:
        db.execute("INSERT INTO subjects(name,dept,semester) VALUES(?,?,?)",
                   (s, "CSE", 6))
    names = ["Arun Kumar", "Priya Dharshini", "Karthik Raja",
             "Divya Bharathi", "Mohamed Faizal", "Lakshmi Priya",
             "Suresh Babu", "Nandhini"]
    # (attendance probability, base mark, mark trend per exam)
    profiles = [(0.95, 82, 3), (0.92, 76, 4), (0.65, 58, -4), (0.88, 90, 1),
                (0.70, 45, 6), (0.97, 70, 2), (0.60, 52, -3), (0.85, 66, 5)]
    today = date.today()
    for i, nm in enumerate(names):
        roll = f"21CSE{101 + i}"
        cur = db.execute(
            "INSERT INTO students(roll_no,name,dept,year,email,phone) "
            "VALUES(?,?,?,?,?,?)",
            (roll, nm, "CSE", 4, f"{roll.lower()}@college.edu",
             f"98765{43210 + i}"))
        sid = cur.lastrowid
        db.execute("INSERT INTO users(username,password_hash,role,student_id)"
                   " VALUES(?,?,?,?)",
                   (roll, generate_password_hash(roll), "student", sid))
        att_p, base, trend = profiles[i]
        for sub in range(1, len(subjects) + 1):
            for d in range(12):
                day = (today - timedelta(days=d)).isoformat()
                st = "Present" if random.random() < att_p else "Absent"
                db.execute("INSERT INTO attendance(student_id,subject_id,date,"
                           "status) VALUES(?,?,?,?)", (sid, sub, day, st))
            for e, ex in enumerate(EXAM_TYPES[:3]):
                m = max(5, min(100, base + trend * e + random.randint(-6, 6)))
                db.execute("INSERT INTO marks(student_id,subject_id,exam_type,"
                           "marks) VALUES(?,?,?,?)", (sid, sub, ex, m))


# --------------------------------------------------------------------------
# Helpers: auth, grading, analytics
# --------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


def role_required(*roles):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapper(*a, **kw):
            if session.get("role") not in roles:
                abort(403)
            return f(*a, **kw)
        return wrapper
    return deco


def grade_of(m):
    """Return (letter grade, grade point) for a mark out of 100."""
    for limit, g_, gp in [(90, "O", 10), (80, "A+", 9), (70, "A", 8),
                          (60, "B+", 7), (50, "B", 6), (40, "C", 5)]:
        if m >= limit:
            return g_, gp
    return "F", 0


def predict_next(values):
    """Predict the next mark using simple linear regression (least squares)
    over the previous exam marks. Falls back to the mean for < 2 points."""
    n = len(values)
    if n == 0:
        return None
    if n == 1:
        return values[0]
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(values) / n
    den = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, values)) / den
    pred = my + slope * (n - mx)
    return max(0, min(100, pred))


def student_stats(db, sid):
    """Everything we show about one student, computed in one place."""
    att_rows = db.execute(
        "SELECT sb.name, COUNT(*) total, SUM(a.status='Present') present "
        "FROM attendance a JOIN subjects sb ON sb.id=a.subject_id "
        "WHERE a.student_id=? GROUP BY sb.id ORDER BY sb.name", (sid,)).fetchall()
    attendance = []
    tot = pres = 0
    for r in att_rows:
        pct = round(100 * r["present"] / r["total"], 1)
        attendance.append({"subject": r["name"], "total": r["total"],
                           "present": r["present"], "pct": pct})
        tot += r["total"]
        pres += r["present"]
    overall_att = round(100 * pres / tot, 1) if tot else None

    mrows = db.execute(
        "SELECT sb.name subject, m.exam_type, m.marks FROM marks m "
        "JOIN subjects sb ON sb.id=m.subject_id WHERE m.student_id=?",
        (sid,)).fetchall()
    by_subject = {}
    for r in mrows:
        by_subject.setdefault(r["subject"], {})[r["exam_type"]] = r["marks"]

    subjects, gps, preds = [], [], []
    for sub, exams in sorted(by_subject.items()):
        ordered = [exams[e] for e in EXAM_TYPES if e in exams]
        avg = sum(ordered) / len(ordered)
        letter, gp = grade_of(avg)
        pred = predict_next(ordered)
        subjects.append({"subject": sub, "exams": exams, "avg": round(avg, 1),
                         "grade": letter, "gp": gp,
                         "pred": round(pred, 1) if pred is not None else None})
        gps.append(gp)
        preds.append(pred)

    exam_avgs = []
    for e in EXAM_TYPES:
        vals = [x["exams"][e] for x in subjects if e in x["exams"]]
        exam_avgs.append(round(sum(vals) / len(vals), 1) if vals else None)

    avg_marks = (round(sum(s["avg"] for s in subjects) / len(subjects), 1)
                 if subjects else None)
    gpa = round(sum(gps) / len(gps), 2) if gps else None
    pred_overall = round(sum(preds) / len(preds), 1) if preds else None

    # --- "Smart" risk analysis ---------------------------------------------
    alerts = []
    if overall_att is not None and overall_att < ATT_LIMIT:
        alerts.append(f"Attendance {overall_att}% is below {ATT_LIMIT}%")
    for a in attendance:
        if a["pct"] < ATT_LIMIT:
            alerts.append(f"Low attendance in {a['subject']} ({a['pct']}%)")
    for s in subjects:
        if s["grade"] == "F":
            alerts.append(f"Failing in {s['subject']} (avg {s['avg']})")
    if pred_overall is not None:
        if pred_overall < 50:
            risk = "High risk"
        elif pred_overall < 65 or (overall_att or 100) < ATT_LIMIT:
            risk = "Needs attention"
        else:
            risk = "On track"
    else:
        risk = "No data"
    return {"attendance": attendance, "overall_att": overall_att,
            "subjects": subjects, "exam_avgs": exam_avgs,
            "avg_marks": avg_marks, "gpa": gpa, "pred": pred_overall,
            "risk": risk, "alerts": alerts}


@app.context_processor
def inject_globals():
    return {"ATT_LIMIT": ATT_LIMIT, "EXAM_TYPES": EXAM_TYPES}


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = get_db().execute("SELECT * FROM users WHERE username=?",
                             (request.form["username"].strip(),)).fetchone()
        if u and check_password_hash(u["password_hash"],
                                     request.form["password"]):
            session.clear()
            session.update(user_id=u["id"], username=u["username"],
                           role=u["role"], student_id=u["student_id"])
            return redirect(url_for("dashboard"))
        flash("Invalid username or password", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE id=?",
                       (session["user_id"],)).fetchone()
        new = request.form["new"]
        if not check_password_hash(u["password_hash"], request.form["old"]):
            flash("Current password is wrong", "danger")
        elif len(new) < 6:
            flash("New password must be at least 6 characters", "danger")
        else:
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (generate_password_hash(new), u["id"]))
            db.commit()
            flash("Password changed", "success")
            return redirect(url_for("dashboard"))
    return render_template("password.html")


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@app.route("/")
@login_required
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    if session["role"] == "student":
        return redirect(url_for("student_detail", sid=session["student_id"]))
    db = get_db()
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    total_students = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    total_subjects = db.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    avg_att = db.execute(
        "SELECT ROUND(100.0*SUM(status='Present')/COUNT(*),1) FROM attendance"
    ).fetchone()[0]
    low_att = q(
        "SELECT st.id, st.name, st.roll_no, "
        "ROUND(100.0*SUM(a.status='Present')/COUNT(*),1) pct "
        "FROM students st JOIN attendance a ON a.student_id=st.id "
        "GROUP BY st.id HAVING pct < ? ORDER BY pct", ATT_LIMIT)
    toppers = q(
        "SELECT st.id, st.name, st.roll_no, ROUND(AVG(m.marks),1) avg "
        "FROM students st JOIN marks m ON m.student_id=st.id "
        "GROUP BY st.id ORDER BY avg DESC LIMIT 5")
    dept = q("SELECT COALESCE(dept,'N/A') d, COUNT(*) c FROM students "
             "GROUP BY dept")
    sub_avg = q("SELECT sb.name, ROUND(AVG(m.marks),1) avg FROM marks m "
                "JOIN subjects sb ON sb.id=m.subject_id GROUP BY sb.id")
    return render_template(
        "dashboard.html", total_students=total_students,
        total_subjects=total_subjects, avg_att=avg_att, low_att=low_att,
        toppers=toppers,
        dept_labels=[r["d"] for r in dept], dept_data=[r["c"] for r in dept],
        sub_labels=[r["name"] for r in sub_avg],
        sub_data=[r["avg"] for r in sub_avg])


# --------------------------------------------------------------------------
# Students (CRUD + search)
# --------------------------------------------------------------------------
@app.route("/students")
@role_required("admin", "teacher")
def students():
    q = request.args.get("q", "").strip()
    dept = request.args.get("dept", "").strip()
    sql, args = "SELECT * FROM students WHERE 1=1", []
    if q:
        sql += " AND (name LIKE ? OR roll_no LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if dept:
        sql += " AND dept = ?"
        args.append(dept)
    db = get_db()
    rows = db.execute(sql + " ORDER BY roll_no", args).fetchall()
    depts = [r[0] for r in db.execute(
        "SELECT DISTINCT dept FROM students WHERE dept IS NOT NULL")]
    return render_template("students.html", students=rows, q=q, dept=dept,
                           depts=depts)


def _student_form_data():
    f = request.form
    return (f["roll_no"].strip().upper(), f["name"].strip(),
            f["dept"].strip().upper(), f.get("year", type=int),
            f["email"].strip(), f["phone"].strip())


@app.route("/students/add", methods=["GET", "POST"])
@role_required("admin", "teacher")
def student_add():
    if request.method == "POST":
        db = get_db()
        data = _student_form_data()
        try:
            cur = db.execute(
                "INSERT INTO students(roll_no,name,dept,year,email,phone) "
                "VALUES(?,?,?,?,?,?)", data)
            # the student can log in with roll number as username & password
            db.execute("INSERT INTO users(username,password_hash,role,"
                       "student_id) VALUES(?,?,?,?)",
                       (data[0], generate_password_hash(data[0]), "student",
                        cur.lastrowid))
            db.commit()
            flash(f"Student added. Login: {data[0]} / {data[0]}", "success")
            return redirect(url_for("students"))
        except sqlite3.IntegrityError:
            flash("Roll number already exists", "danger")
    return render_template("student_form.html", s=None)


@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
@role_required("admin", "teacher")
def student_edit(sid):
    db = get_db()
    s = db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not s:
        abort(404)
    if request.method == "POST":
        try:
            db.execute("UPDATE students SET roll_no=?,name=?,dept=?,year=?,"
                       "email=?,phone=? WHERE id=?", _student_form_data() + (sid,))
            db.commit()
            flash("Student updated", "success")
            return redirect(url_for("students"))
        except sqlite3.IntegrityError:
            flash("Roll number already exists", "danger")
    return render_template("student_form.html", s=s)


@app.route("/students/<int:sid>/delete", methods=["POST"])
@role_required("admin")
def student_delete(sid):
    db = get_db()
    db.execute("DELETE FROM students WHERE id=?", (sid,))
    db.commit()
    flash("Student deleted", "success")
    return redirect(url_for("students"))


@app.route("/students/<int:sid>")
@login_required
def student_detail(sid):
    # a student may only open their own page
    if session["role"] == "student" and session["student_id"] != sid:
        abort(403)
    db = get_db()
    s = db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not s:
        abort(404)
    return render_template("student_detail.html", s=s,
                           st=student_stats(db, sid))


# --------------------------------------------------------------------------
# Subjects
# --------------------------------------------------------------------------
@app.route("/subjects", methods=["GET", "POST"])
@role_required("admin", "teacher")
def subjects():
    db = get_db()
    if request.method == "POST":
        if session["role"] != "admin":
            abort(403)
        db.execute("INSERT INTO subjects(name,dept,semester) VALUES(?,?,?)",
                   (request.form["name"].strip(),
                    request.form["dept"].strip().upper(),
                    request.form.get("semester", type=int)))
        db.commit()
        flash("Subject added", "success")
        return redirect(url_for("subjects"))
    return render_template("subjects.html", subjects=db.execute(
        "SELECT * FROM subjects ORDER BY semester, name").fetchall())


@app.route("/subjects/<int:sub_id>/delete", methods=["POST"])
@role_required("admin")
def subject_delete(sub_id):
    db = get_db()
    db.execute("DELETE FROM subjects WHERE id=?", (sub_id,))
    db.commit()
    flash("Subject deleted", "success")
    return redirect(url_for("subjects"))


# --------------------------------------------------------------------------
# Attendance
# --------------------------------------------------------------------------
@app.route("/attendance", methods=["GET", "POST"])
@role_required("admin", "teacher")
def attendance():
    db = get_db()
    subs = db.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    subject_id = request.values.get("subject_id", type=int)
    day = request.values.get("date") or date.today().isoformat()
    studs, existing = [], {}
    if subject_id:
        studs = db.execute("SELECT * FROM students ORDER BY roll_no").fetchall()
        if request.method == "POST":
            for s in studs:
                status = request.form.get(f"status_{s['id']}", "Absent")
                db.execute(
                    "INSERT INTO attendance(student_id,subject_id,date,status)"
                    " VALUES(?,?,?,?) ON CONFLICT(student_id,subject_id,date)"
                    " DO UPDATE SET status=excluded.status",
                    (s["id"], subject_id, day, status))
            db.commit()
            flash(f"Attendance saved for {day}", "success")
            return redirect(url_for("attendance", subject_id=subject_id,
                                    date=day))
        existing = {r["student_id"]: r["status"] for r in db.execute(
            "SELECT student_id,status FROM attendance "
            "WHERE subject_id=? AND date=?", (subject_id, day))}
    return render_template("attendance.html", subjects=subs,
                           subject_id=subject_id, day=day, students=studs,
                           existing=existing)


@app.route("/attendance/report")
@role_required("admin", "teacher")
def attendance_report():
    db = get_db()
    rows = db.execute(
        "SELECT st.id, st.roll_no, st.name, st.email, COUNT(a.id) total, "
        "COALESCE(SUM(a.status='Present'),0) present FROM students st "
        "LEFT JOIN attendance a ON a.student_id=st.id "
        "GROUP BY st.id ORDER BY st.roll_no").fetchall()
    data = []
    for r in rows:
        pct = round(100 * r["present"] / r["total"], 1) if r["total"] else None
        data.append({**dict(r), "pct": pct})
    return render_template("attendance_report.html", rows=data)


# --------------------------------------------------------------------------
# Marks
# --------------------------------------------------------------------------
@app.route("/marks", methods=["GET", "POST"])
@role_required("admin", "teacher")
def marks():
    db = get_db()
    subs = db.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    subject_id = request.values.get("subject_id", type=int)
    exam = request.values.get("exam_type", EXAM_TYPES[0])
    if exam not in EXAM_TYPES:
        abort(400)
    studs, existing = [], {}
    if subject_id:
        studs = db.execute("SELECT * FROM students ORDER BY roll_no").fetchall()
        if request.method == "POST":
            bad = 0
            for s in studs:
                raw = request.form.get(f"marks_{s['id']}", "").strip()
                if raw == "":
                    continue
                try:
                    val = float(raw)
                    if not 0 <= val <= 100:
                        raise ValueError
                except ValueError:
                    bad += 1
                    continue
                db.execute(
                    "INSERT INTO marks(student_id,subject_id,exam_type,marks)"
                    " VALUES(?,?,?,?) ON CONFLICT(student_id,subject_id,"
                    "exam_type) DO UPDATE SET marks=excluded.marks",
                    (s["id"], subject_id, exam, val))
            db.commit()
            flash("Marks saved" + (f" ({bad} invalid entries skipped)"
                                   if bad else ""),
                  "warning" if bad else "success")
            return redirect(url_for("marks", subject_id=subject_id,
                                    exam_type=exam))
        existing = {r["student_id"]: r["marks"] for r in db.execute(
            "SELECT student_id,marks FROM marks WHERE subject_id=? AND "
            "exam_type=?", (subject_id, exam))}
    return render_template("marks.html", subjects=subs, subject_id=subject_id,
                           exam=exam, students=studs, existing=existing,
                           grade_of=grade_of)


# --------------------------------------------------------------------------
# Reports (CSV, opens in Excel)
# --------------------------------------------------------------------------
def _csv_response(rows, header, filename):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename={filename}"})


@app.route("/reports/students.csv")
@role_required("admin", "teacher")
def report_students():
    db = get_db()
    out = []
    for s in db.execute("SELECT * FROM students ORDER BY roll_no"):
        st = student_stats(db, s["id"])
        out.append([s["roll_no"], s["name"], s["dept"], s["year"],
                    st["overall_att"], st["avg_marks"], st["gpa"],
                    st["pred"], st["risk"]])
    return _csv_response(out, ["Roll No", "Name", "Dept", "Year",
                               "Attendance %", "Avg Marks", "GPA",
                               "Predicted Next", "Status"],
                         "student_report.csv")


@app.route("/reports/marks.csv")
@role_required("admin", "teacher")
def report_marks():
    rows = get_db().execute(
        "SELECT st.roll_no, st.name, sb.name, m.exam_type, m.marks "
        "FROM marks m JOIN students st ON st.id=m.student_id "
        "JOIN subjects sb ON sb.id=m.subject_id "
        "ORDER BY st.roll_no, sb.name").fetchall()
    return _csv_response([list(r) for r in rows],
                         ["Roll No", "Name", "Subject", "Exam", "Marks"],
                         "marks_report.csv")


@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403,
                           msg="You don't have permission to open this page."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404,
                           msg="Page not found."), 404


init_db()

if __name__ == "__main__":
    # host="0.0.0.0" lets other devices on the same WiFi open the app
    app.run(host="0.0.0.0", port=5000, debug=False)
