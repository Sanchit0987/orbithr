"""OrbitHR - data layer: SQLite schema, demo seed data, shared business helpers.

Design intent (from the user brief):
- Qandle-inspired office attendance + HR management system.
- The brief asked for Next.js/TypeScript/PostgreSQL, but this host has no Node.js
  or PostgreSQL toolchain (only Python 3.13), so this functional test build runs on
  the Python stdlib HTTP server with SQLite for persistent storage. The schema is
  plain relational SQL and ports to PostgreSQL nearly 1:1 (see README).
- Features: attendance (clock in/out, breaks, late, overtime), leave management,
  employee directory, role-based dashboards (employee/manager/hr), reports + CSV,
  shift management, notifications, WFH, QR check-in, correction requests,
  onboarding, comp-off and audit logs.
"""
import hashlib
import os
import random
import secrets
import sqlite3
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# On Vercel the repo filesystem is read-only; only /tmp is writable (ephemeral:
# demo data re-seeds on cold starts). Locally the DB lives next to the code.
DB_PATH = os.environ.get("ORBITHR_DB", os.path.join(BASE_DIR, "hrms.db"))

TS_FMT = "%Y-%m-%d %H:%M"
WEEKDAY_KEYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
AVATAR_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444",
                 "#8b5cf6", "#ec4899", "#14b8a6", "#f97316", "#3b82f6"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS designations(
  id INTEGER PRIMARY KEY, title TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS shifts(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  start_time TEXT NOT NULL, end_time TEXT NOT NULL,
  break_minutes INTEGER NOT NULL DEFAULT 60,
  grace_minutes INTEGER NOT NULL DEFAULT 10,
  weekly_offs TEXT NOT NULL DEFAULT 'Sat,Sun');
CREATE TABLE IF NOT EXISTS employees(
  id INTEGER PRIMARY KEY,
  emp_code TEXT UNIQUE NOT NULL,
  first_name TEXT NOT NULL, last_name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL, phone TEXT DEFAULT '',
  password_salt TEXT NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'employee',          -- employee | manager | hr
  department_id INTEGER REFERENCES departments(id),
  designation_id INTEGER REFERENCES designations(id),
  manager_id INTEGER REFERENCES employees(id),
  shift_id INTEGER NOT NULL DEFAULT 1 REFERENCES shifts(id),
  date_joined TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',          -- onboarding | active | exited
  avatar_color TEXT NOT NULL DEFAULT '#6366f1');
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, employee_id INTEGER NOT NULL,
  csrf TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attendance(
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  date TEXT NOT NULL,
  clock_in TEXT, clock_out TEXT,
  break_minutes INTEGER NOT NULL DEFAULT 0,
  work_minutes INTEGER NOT NULL DEFAULT 0,
  overtime_minutes INTEGER NOT NULL DEFAULT 0,
  late_minutes INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'present',  -- present | wfh | leave | absent
  mode TEXT NOT NULL DEFAULT 'office',     -- office | wfh
  notes TEXT NOT NULL DEFAULT '',
  missed_clockout INTEGER NOT NULL DEFAULT 0,
  UNIQUE(employee_id, date));
CREATE TABLE IF NOT EXISTS breaks(
  id INTEGER PRIMARY KEY,
  attendance_id INTEGER NOT NULL REFERENCES attendance(id),
  start_ts TEXT NOT NULL, end_ts TEXT);
CREATE TABLE IF NOT EXISTS leave_types(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
  annual_quota INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS leave_balances(
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  leave_type_id INTEGER NOT NULL REFERENCES leave_types(id),
  year INTEGER NOT NULL, allocated REAL NOT NULL DEFAULT 0,
  used REAL NOT NULL DEFAULT 0,
  UNIQUE(employee_id, leave_type_id, year));
CREATE TABLE IF NOT EXISTS leave_requests(
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  leave_type_id INTEGER NOT NULL REFERENCES leave_types(id),
  start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  days REAL NOT NULL, reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected|cancelled
  reviewer_id INTEGER, review_comment TEXT DEFAULT '',
  created_at TEXT NOT NULL, reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS compoffs(
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  work_date TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  reviewer_id INTEGER, review_comment TEXT DEFAULT '',
  created_at TEXT NOT NULL, reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS holidays(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, date TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'info', link TEXT NOT NULL DEFAULT '',
  is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS corrections(
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  date TEXT NOT NULL, requested_in TEXT, requested_out TEXT,
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  reviewer_id INTEGER, review_comment TEXT DEFAULT '',
  created_at TEXT NOT NULL, reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS onboarding_tasks(
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  task TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, done_at TEXT);
CREATE TABLE IF NOT EXISTS audit_logs(
  id INTEGER PRIMARY KEY, actor_id INTEGER,
  action TEXT NOT NULL, entity TEXT NOT NULL DEFAULT '',
  entity_id TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qr_tokens(
  date TEXT PRIMARY KEY, token TEXT NOT NULL);
"""

DEFAULT_ONBOARDING_TASKS = [
    "Sign offer letter and contract",
    "Create company email account",
    "Issue laptop and access card",
    "Add to payroll and benefits",
    "Complete HR orientation session",
    "Assign buddy and first-week plan",
]


# ---------------------------------------------------------------- connection

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------- passwords

def new_password(password):
    salt = secrets.token_hex(8)
    return salt, _pw_hash(password, salt)


def _pw_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 60000).hex()


def verify_password(emp_row, password):
    return secrets.compare_digest(
        _pw_hash(password, emp_row["password_salt"]), emp_row["password_hash"])


# ---------------------------------------------------------------- time utils

def now():
    return datetime.now()


def now_ts():
    return now().strftime(TS_FMT)


def parse_ts(s):
    return datetime.strptime(s[:16], TS_FMT)


def parse_hm(s):
    h, m = s.split(":")
    return int(h), int(m)


def fmt_mins(m):
    m = int(m or 0)
    return "%dh %02dm" % (m // 60, m % 60)


def mins_between(a, b):
    return int((b - a).total_seconds() // 60)


def shift_start_dt(shift, d):
    h, m = parse_hm(shift["start_time"])
    return datetime(d.year, d.month, d.day, h, m)


def shift_end_dt(shift, d):
    h, m = parse_hm(shift["end_time"])
    return datetime(d.year, d.month, d.day, h, m)


def nominal_minutes(shift):
    d = date.today()
    return max(0, mins_between(shift_start_dt(shift, d), shift_end_dt(shift, d))
               - shift["break_minutes"])


def is_weekly_off(shift, d):
    offs = [x.strip() for x in (shift["weekly_offs"] or "").split(",") if x.strip()]
    return WEEKDAY_KEYS[d.weekday()] in offs


def holidays_map(db):
    return {r["date"]: r["name"] for r in db.execute("SELECT * FROM holidays")}


def working_days(db, shift, start_d, end_d):
    """List of working dates in [start_d, end_d], excluding weekly offs and holidays."""
    hol = holidays_map(db)
    out, d = [], start_d
    while d <= end_d:
        if not is_weekly_off(shift, d) and d.isoformat() not in hol:
            out.append(d)
        d += timedelta(days=1)
    return out


def compute_late(shift, clock_in_dt):
    start = shift_start_dt(shift, clock_in_dt.date())
    return max(0, mins_between(start, clock_in_dt) - shift["grace_minutes"])


def get_shift(db, emp):
    return db.execute("SELECT * FROM shifts WHERE id=?", (emp["shift_id"],)).fetchone()


# ---------------------------------------------------------------- helpers

def emp_name(e):
    return "%s %s" % (e["first_name"], e["last_name"])


def notify(db, employee_id, title, body="", kind="info", link=""):
    db.execute(
        "INSERT INTO notifications(employee_id,title,body,kind,link,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (employee_id, title, body, kind, link, now().strftime("%Y-%m-%d %H:%M:%S")))


def audit(db, actor_id, action, entity="", entity_id="", details=""):
    db.execute(
        "INSERT INTO audit_logs(actor_id,action,entity,entity_id,details,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (actor_id, action, entity, str(entity_id), details,
         now().strftime("%Y-%m-%d %H:%M:%S")))


def hr_ids(db):
    return [r["id"] for r in db.execute(
        "SELECT id FROM employees WHERE role='hr' AND status!='exited'")]


def reviewer_ids(db, emp):
    """Who should be notified about a request from this employee."""
    ids = set(hr_ids(db))
    if emp["manager_id"]:
        ids.add(emp["manager_id"])
    ids.discard(emp["id"])
    return sorted(ids)


def detect_missed_clockouts(db):
    """Lazy job: flag past 'present' days with a clock-in but no clock-out."""
    today = date.today().isoformat()
    rows = db.execute(
        "SELECT a.*, e.first_name, e.last_name FROM attendance a"
        " JOIN employees e ON e.id=a.employee_id"
        " WHERE a.date < ? AND a.clock_in IS NOT NULL AND a.clock_out IS NULL"
        " AND a.missed_clockout=0 AND a.status IN ('present','wfh')",
        (today,)).fetchall()
    for r in rows:
        db.execute("UPDATE attendance SET missed_clockout=1 WHERE id=?", (r["id"],))
        notify(db, r["employee_id"],
               "Missed clock-out on %s" % r["date"],
               "You clocked in at %s but never clocked out. Submit an attendance "
               "correction to fix your hours." % r["clock_in"][11:16],
               "warn", "/corrections")
    if rows:
        db.commit()


def qr_token_today(db, rotate=False):
    today = date.today().isoformat()
    row = db.execute("SELECT token FROM qr_tokens WHERE date=?", (today,)).fetchone()
    if row and not rotate:
        return row["token"]
    token = secrets.token_urlsafe(16)
    db.execute("INSERT INTO qr_tokens(date,token) VALUES(?,?)"
               " ON CONFLICT(date) DO UPDATE SET token=excluded.token", (today, token))
    db.commit()
    return token


# ---------------------------------------------------------------- seed data

def init():
    first_time = not os.path.exists(DB_PATH)
    db = get_db()
    db.executescript(SCHEMA)
    has_emps = db.execute("SELECT COUNT(*) c FROM employees").fetchone()["c"]
    if first_time or not has_emps:
        _seed(db)
    db.commit()
    db.close()


def _seed(db):
    rng = random.Random(42)
    today = date.today()
    year = today.year

    # --- shifts
    shifts = [
        ("General (9-6)", "09:00", "18:00", 60, 10, "Sat,Sun"),
        ("Early (7-4)", "07:00", "16:00", 60, 10, "Sat,Sun"),
        ("Late (1-10)", "13:00", "22:00", 60, 15, "Sun,Mon"),
    ]
    for s in shifts:
        db.execute("INSERT INTO shifts(name,start_time,end_time,break_minutes,"
                   "grace_minutes,weekly_offs) VALUES(?,?,?,?,?,?)", s)

    # --- departments / designations
    depts = ["Engineering", "Product", "Sales", "Finance", "People Ops"]
    for d in depts:
        db.execute("INSERT INTO departments(name) VALUES(?)", (d,))
    desigs = ["Software Engineer", "Senior Software Engineer", "QA Engineer",
              "Engineering Manager", "Product Manager", "Associate Product Manager",
              "Sales Manager", "Sales Executive", "Accountant",
              "HR Manager", "HR Executive"]
    for d in desigs:
        db.execute("INSERT INTO designations(title) VALUES(?)", (d,))
    dept_id = {n: i + 1 for i, n in enumerate(depts)}
    des_id = {n: i + 1 for i, n in enumerate(desigs)}

    # --- employees: (first,last,role,dept,desig,manager_email,shift,joined)
    people = [
        ("Anika", "Rao", "hr", "People Ops", "HR Manager", None, 1, "2021-03-15"),
        ("Rohan", "Mehta", "manager", "Engineering", "Engineering Manager", None, 1, "2020-07-01"),
        ("Maya", "Krishnan", "manager", "Product", "Product Manager", None, 1, "2021-01-11"),
        ("Tara", "Bose", "manager", "Sales", "Sales Manager", None, 1, "2020-11-23"),
        ("Sara", "Iyer", "employee", "Engineering", "Senior Software Engineer", "rohan@acme.io", 1, "2022-02-14"),
        ("Dev", "Patel", "employee", "Engineering", "Software Engineer", "rohan@acme.io", 1, "2023-06-05"),
        ("Lina", "Thomas", "employee", "Engineering", "QA Engineer", "rohan@acme.io", 2, "2022-09-19"),
        ("Arjun", "Nair", "employee", "Engineering", "Software Engineer", "rohan@acme.io", 1, "2023-01-30"),
        ("Ishan", "Gupta", "employee", "Product", "Associate Product Manager", "maya@acme.io", 1, "2023-08-21"),
        ("Vikram", "Singh", "employee", "Sales", "Sales Executive", "tara@acme.io", 3, "2022-05-09"),
        ("Neha", "Sharma", "employee", "Sales", "Sales Executive", "tara@acme.io", 3, "2023-03-13"),
        ("Omar", "Farooq", "employee", "Finance", "Accountant", "anika@acme.io", 1, "2021-10-04"),
        ("Priya", "Das", "employee", "People Ops", "HR Executive", "anika@acme.io", 1, "2022-12-01"),
    ]
    email_to_id = {}
    for i, (fn, ln, role, dept, desig, mgr, shift_id, joined) in enumerate(people):
        email = "%s@acme.io" % fn.lower()
        salt, ph = new_password("demo123")
        db.execute(
            "INSERT INTO employees(emp_code,first_name,last_name,email,phone,"
            "password_salt,password_hash,role,department_id,designation_id,"
            "manager_id,shift_id,date_joined,status,avatar_color)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("EMP%03d" % (i + 1), fn, ln, email,
             "+91 98%08d" % rng.randint(0, 99999999), salt, ph, role,
             dept_id[dept], des_id[desig],
             email_to_id.get(mgr), shift_id, joined, "active",
             AVATAR_COLORS[i % len(AVATAR_COLORS)]))
        email_to_id[email] = db.execute("SELECT last_insert_rowid() i").fetchone()["i"]

    # Onboarding demo employee (not active yet, joins next week)
    salt, ph = new_password("demo123")
    db.execute(
        "INSERT INTO employees(emp_code,first_name,last_name,email,phone,"
        "password_salt,password_hash,role,department_id,designation_id,manager_id,"
        "shift_id,date_joined,status,avatar_color) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("EMP014", "Kabir", "Shah", "kabir@acme.io", "+91 9811224455", salt, ph,
         "employee", dept_id["Engineering"], des_id["Software Engineer"],
         email_to_id["rohan@acme.io"], 1,
         (today + timedelta(days=7)).isoformat(), "onboarding",
         AVATAR_COLORS[3]))
    kabir_id = db.execute("SELECT last_insert_rowid() i").fetchone()["i"]
    for t in DEFAULT_ONBOARDING_TASKS[:4]:
        db.execute("INSERT INTO onboarding_tasks(employee_id,task,done) VALUES(?,?,1)",
                   (kabir_id, t))
    for t in DEFAULT_ONBOARDING_TASKS[4:]:
        db.execute("INSERT INTO onboarding_tasks(employee_id,task) VALUES(?,?)",
                   (kabir_id, t))

    # --- leave types + balances
    ltypes = [("Casual Leave", 12), ("Sick Leave", 8), ("Earned Leave", 15),
              ("Comp Off", 0)]
    for n, q in ltypes:
        db.execute("INSERT INTO leave_types(name,annual_quota) VALUES(?,?)", (n, q))
    lt_id = {n: i + 1 for i, (n, q) in enumerate(ltypes)}
    emps = db.execute("SELECT * FROM employees").fetchall()
    for e in emps:
        for n, q in ltypes:
            db.execute("INSERT INTO leave_balances(employee_id,leave_type_id,year,"
                       "allocated) VALUES(?,?,?,?)", (e["id"], lt_id[n], year, q))

    # --- holidays (demo calendar; adjust to your region)
    for name, d in [("New Year's Day", "%d-01-01" % year),
                    ("Republic Day", "%d-01-26" % year),
                    ("Holi", "%d-03-04" % year),
                    ("Labour Day", "%d-05-01" % year),
                    ("Independence Day", "%d-08-15" % year),
                    ("Gandhi Jayanti", "%d-10-02" % year),
                    ("Diwali", "%d-10-20" % year),
                    ("Guru Nanak Jayanti", "%d-11-09" % year),
                    ("Christmas", "%d-12-25" % year)]:
        db.execute("INSERT OR IGNORE INTO holidays(name,date) VALUES(?,?)", (name, d))

    # --- attendance history: last 70 days for active employees
    hol = holidays_map(db)
    shifts_by_id = {s["id"]: s for s in db.execute("SELECT * FROM shifts")}
    active = [e for e in emps if e["status"] == "active"]
    for e in active:
        sh = shifts_by_id[e["shift_id"]]
        for n in range(70, 0, -1):
            d = today - timedelta(days=n)
            if is_weekly_off(sh, d) or d.isoformat() in hol:
                continue
            r = rng.random()
            if r < 0.03:
                db.execute("INSERT INTO attendance(employee_id,date,status,notes)"
                           " VALUES(?,?,'absent','No show')", (e["id"], d.isoformat()))
                continue
            mode = "wfh" if rng.random() < 0.12 else "office"
            start = shift_start_dt(sh, d)
            if rng.random() < 0.18:  # late day
                cin = start + timedelta(minutes=sh["grace_minutes"] + rng.randint(5, 40))
            else:
                cin = start + timedelta(minutes=rng.randint(-8, sh["grace_minutes"]))
            end = shift_end_dt(sh, d)
            cout = end + timedelta(minutes=rng.randint(-10, 55))
            brk = rng.randint(45, 70)
            work = max(0, mins_between(cin, cout) - brk)
            ot = max(0, work - nominal_minutes(sh))
            late = compute_late(sh, cin)
            db.execute(
                "INSERT INTO attendance(employee_id,date,clock_in,clock_out,"
                "break_minutes,work_minutes,overtime_minutes,late_minutes,status,mode)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (e["id"], d.isoformat(), cin.strftime(TS_FMT), cout.strftime(TS_FMT),
                 brk, work, ot, late, "wfh" if mode == "wfh" else "present", mode))

    # Arjun worked last Saturday (weekly off) -> comp-off credit request pending
    last_sat = today - timedelta(days=(today.weekday() - 5) % 7 or 7)
    arjun = email_to_id["arjun@acme.io"]
    sh = shifts_by_id[1]
    cin = shift_start_dt(sh, last_sat) + timedelta(minutes=12)
    cout = cin + timedelta(minutes=5 * 60 + 30)
    db.execute("INSERT OR REPLACE INTO attendance(employee_id,date,clock_in,clock_out,"
               "break_minutes,work_minutes,overtime_minutes,late_minutes,status,mode,notes)"
               " VALUES(?,?,?,?,30,300,0,0,'present','office','Release weekend')",
               (arjun, last_sat.isoformat(), cin.strftime(TS_FMT), cout.strftime(TS_FMT)))
    db.execute("INSERT INTO compoffs(employee_id,work_date,reason,created_at)"
               " VALUES(?,?,?,?)",
               (arjun, last_sat.isoformat(),
                "Worked Saturday for the v2.4 release cutover",
                now().strftime("%Y-%m-%d %H:%M:%S")))
    notify(db, email_to_id["rohan@acme.io"], "Comp-off request from Arjun Nair",
           "Worked on %s (weekly off). Review in Approvals." % last_sat.isoformat(),
           "action", "/approvals")

    # Yesterday: Lina forgot to clock out (missed clock-out demo)
    yd = today - timedelta(days=1)
    lina = email_to_id["lina@acme.io"]
    if not is_weekly_off(shifts_by_id[2], yd) and yd.isoformat() not in hol:
        sh = shifts_by_id[2]
        cin = shift_start_dt(sh, yd) + timedelta(minutes=4)
        db.execute("INSERT OR REPLACE INTO attendance(employee_id,date,clock_in,"
                   "status,mode) VALUES(?,?,?,'present','office')",
                   (lina, yd.isoformat(), cin.strftime(TS_FMT)))

    # --- leave requests (seeded through the same rules the app uses)
    def seed_leave(email, type_name, start, length, status, reviewer_email,
                   reason, comment=""):
        e = db.execute("SELECT * FROM employees WHERE email=?", (email,)).fetchone()
        sh = shifts_by_id[e["shift_id"]]
        days = working_days(db, sh, start, start + timedelta(days=length - 1))
        if not days:
            return
        created = (start - timedelta(days=5)).strftime("%Y-%m-%d 10:00:00")
        reviewer = email_to_id.get(reviewer_email)
        db.execute(
            "INSERT INTO leave_requests(employee_id,leave_type_id,start_date,end_date,"
            "days,reason,status,reviewer_id,review_comment,created_at,reviewed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (e["id"], lt_id[type_name], days[0].isoformat(), days[-1].isoformat(),
             len(days), reason, status,
             reviewer if status in ("approved", "rejected") else None,
             comment, created,
             (start - timedelta(days=3)).strftime("%Y-%m-%d 15:00:00")
             if status in ("approved", "rejected") else None))
        if status == "approved":
            for d in days:
                db.execute(
                    "INSERT INTO attendance(employee_id,date,status,notes)"
                    " VALUES(?,?,'leave',?) ON CONFLICT(employee_id,date) DO UPDATE SET"
                    " status='leave', notes=excluded.notes, clock_in=NULL,"
                    " clock_out=NULL, work_minutes=0, overtime_minutes=0,"
                    " late_minutes=0, break_minutes=0",
                    (e["id"], d.isoformat(), type_name))
            db.execute("UPDATE leave_balances SET used=used+? WHERE employee_id=?"
                       " AND leave_type_id=? AND year=?",
                       (len(days), e["id"], lt_id[type_name], year))
        elif status == "pending" and reviewer:
            notify(db, reviewer, "Leave request from %s" % emp_name(e),
                   "%s, %s -> %s. Review in Approvals." %
                   (type_name, days[0].isoformat(), days[-1].isoformat()),
                   "action", "/approvals")

    seed_leave("dev@acme.io", "Casual Leave", today - timedelta(days=21), 2,
               "approved", "rohan@acme.io", "Family function in Surat", "Enjoy!")
    seed_leave("sara@acme.io", "Sick Leave", today - timedelta(days=10), 1,
               "approved", "rohan@acme.io", "Fever and cold")
    seed_leave("vikram@acme.io", "Earned Leave", today - timedelta(days=35), 3,
               "approved", "tara@acme.io", "Trip to Coorg")
    seed_leave("neha@acme.io", "Casual Leave", today - timedelta(days=14), 1,
               "rejected", "tara@acme.io", "Personal errand",
               "Quarter-end week, please reschedule")
    # Pending requests (future) for approval demos
    next_mon = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    seed_leave("dev@acme.io", "Casual Leave", next_mon, 2, "pending",
               "rohan@acme.io", "Cousin's wedding")
    seed_leave("priya@acme.io", "Sick Leave", today + timedelta(days=3), 1,
               "pending", "anika@acme.io", "Dental procedure")

    # --- today: most of the office is already clocked in (not the demo logins)
    skip_today = {email_to_id["anika@acme.io"], email_to_id["dev@acme.io"]}
    for e in active:
        if e["id"] in skip_today:
            continue
        sh = shifts_by_id[e["shift_id"]]
        if is_weekly_off(sh, today) or today.isoformat() in hol:
            continue
        if db.execute("SELECT 1 FROM attendance WHERE employee_id=? AND date=?",
                      (e["id"], today.isoformat())).fetchone():
            continue
        if rng.random() < 0.15:
            continue  # not in yet
        start = shift_start_dt(sh, today)
        cin = start + timedelta(minutes=rng.randint(-6, sh["grace_minutes"] + 8))
        if cin > now():
            continue
        mode = "wfh" if rng.random() < 0.15 else "office"
        db.execute(
            "INSERT INTO attendance(employee_id,date,clock_in,late_minutes,status,mode)"
            " VALUES(?,?,?,?,?,?)",
            (e["id"], today.isoformat(), cin.strftime(TS_FMT),
             compute_late(sh, cin), "wfh" if mode == "wfh" else "present", mode))

    # --- a few notifications + audit entries so the first login looks alive
    notify(db, email_to_id["dev@acme.io"], "Leave approved",
           "Your Casual Leave for last month was approved by Rohan Mehta.",
           "success", "/leave")
    notify(db, email_to_id["anika@acme.io"], "Onboarding in progress",
           "Kabir Shah joins next week. 2 onboarding tasks are still open.",
           "info", "/onboarding")
    audit(db, email_to_id["anika@acme.io"], "seed.demo-data", "system", "",
          "Demo workspace seeded with 14 employees and 70 days of attendance")
    db.commit()
