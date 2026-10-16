"""OrbitHR - HTTP server: routing, sessions, RBAC, POST actions, CSV export.

Security model (stdlib-only equivalent of the requested stack):
- PBKDF2-hashed passwords with per-user salts.
- Opaque session tokens in HttpOnly cookies, 12 h expiry, server-side store.
- Per-session CSRF token required on every POST.
- Role-based access control on every route (employee / manager / hr); managers
  only see and approve their direct reports, HR sees everything.
- All mutations re-validate server-side (dates, balances, ownership, scope).

Run:  python3 app.py   ->  http://127.0.0.1:8045
Demo logins (password demo123): anika@acme.io (HR), rohan@acme.io (manager),
dev@acme.io (employee).
"""
import csv
import io
import secrets
import sys
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http import cookies as http_cookies
from urllib.parse import parse_qs, quote, urlparse

import db as D
import views as V
from ui import CSS, JS, esc

PORT = 8045
SESSION_HOURS = 12


# --------------------------------------------------------------------- auth

def create_session(db, emp_id):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(16)
    now = D.now()
    db.execute("INSERT INTO sessions(token,employee_id,csrf,created_at,expires_at)"
               " VALUES(?,?,?,?,?)",
               (token, emp_id, csrf, now.strftime("%Y-%m-%d %H:%M:%S"),
                (now + timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()
    return token


def get_session(db, token):
    if not token:
        return None
    s = db.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
    if not s:
        return None
    if s["expires_at"] < D.now().strftime("%Y-%m-%d %H:%M:%S"):
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        db.commit()
        return None
    return s


LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · OrbitHR</title><style>%s</style></head>
<body><div class="loginbg"><div class="loginbox">
<div class="l">
 <div class="logo" style="padding:0 0 18px"><span class="mark">O</span>
  <div><b style="color:#fff">OrbitHR</b><small>Attendance &amp; HR Suite</small></div></div>
 <h2 style="font-size:24px;color:#fff;letter-spacing:-.4px">Everything your
 office needs to run the day.</h2>
 <p style="margin:12px 0 18px;color:#9aa5c4;font-size:14px">Clock-in/out, leave,
 shifts, approvals, reports, QR kiosk check-in, onboarding and audit logs —
 with role-based dashboards for employees, managers and HR.</p>
 <p class="xs" style="color:#7c87a8">Need access? Contact your HR administrator.
 Demo credentials for evaluators are documented in the project README.</p>
</div>
<div class="r">
 <h2 style="font-size:21px;margin-bottom:4px">Welcome back</h2>
 <p class="mut sm" style="margin-bottom:18px">Sign in to your workspace</p>
 %s
 <form method="post" action="/login" class="frm">
  <div><label class="f">Work email</label>
   <input name="email" type="email" placeholder="you@acme.io" required autofocus></div>
  <div><label class="f">Password</label>
   <input name="password" type="password" placeholder="••••••••" required></div>
  <button class="btn" style="width:100%%;padding:11px">Sign in</button>
  <p class="xs mut">Sessions last %dh. Passwords are salted PBKDF2 hashes; all
  actions are CSRF-protected and role-checked on the server.</p>
 </form>
</div></div></div><script>%s</script></body></html>"""


# --------------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    server_version = "OrbitHR/1.0"

    # ---- plumbing
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_html(self, html, status=200, headers=None):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, path, ok="", err="", set_cookie=None):
        q = []
        if ok:
            q.append("ok=" + quote(ok))
        if err:
            q.append("err=" + quote(err))
        if q:
            path += ("&" if "?" in path else "?") + "&".join(q)
        self.send_response(303)
        self.send_header("Location", path)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def cookie_token(self):
        c = http_cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return c["orbit_session"].value if "orbit_session" in c else None

    def form(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode() if length else ""
        parsed = parse_qs(raw, keep_blank_values=True)
        self._last_form_multi = parsed
        return {k: v[0] for k, v in parsed.items()}

    def _multi_values(self, key):
        return getattr(self, "_last_form_multi", {}).get(key, [])

    # ---- GET
    def do_GET(self):
        db = D.get_db()
        try:
            url = urlparse(self.path)
            path, query = url.path.rstrip("/") or "/", parse_qs(url.query)
            sess = get_session(db, self.cookie_token())
            if path == "/login" or (not sess and path == "/"):
                flash = ""
                if "err" in query:
                    flash = ('<div class="flash err">%s</div>'
                             % esc(query["err"][0]))
                self.send_html(LOGIN_PAGE % (CSS, flash, SESSION_HOURS, JS))
                return
            if not sess:
                self.redirect("/login?err=" + quote("Please sign in to continue."))
                return
            user = V.get_emp(db, sess["employee_id"])
            D.detect_missed_clockouts(db)

            if path == "/reports/export.csv":
                self.export_csv(db, user, query)
                return

            page = self.route_get(db, user, sess, path, query)
            if page is None:
                self.send_html(self.wrap(db, user, sess, "Not found", "/",
                                         '<div class="card"><div class="empty">'
                                         'Page not found.</div></div>', query), 404)
                return
            title, active, html = page
            self.send_html(self.wrap(db, user, sess, title, active, html, query))
        except Exception as e:  # pragma: no cover - visible in server log
            import traceback
            traceback.print_exc()
            self.send_html("<h1>500</h1><pre>%s</pre>" % esc(e), 500)
        finally:
            db.close()

    def wrap(self, db, user, sess, title, active, html, query):
        from ui import flash_html, layout
        unread = db.execute("SELECT COUNT(*) c FROM notifications WHERE"
                            " employee_id=? AND is_read=0",
                            (user["id"],)).fetchone()["c"]
        counts = {}
        if user["role"] in ("manager", "hr"):
            ids = V.team_ids(db, user)
            cl, args = V.scope_clause(ids)
            counts["approvals"] = (
                db.execute("SELECT COUNT(*) c FROM leave_requests WHERE"
                           " status='pending' AND employee_id IN %s" % cl,
                           args).fetchone()["c"]
                + db.execute("SELECT COUNT(*) c FROM compoffs WHERE status='pending'"
                             " AND employee_id IN %s" % cl, args).fetchone()["c"]
                + db.execute("SELECT COUNT(*) c FROM corrections WHERE"
                             " status='pending' AND employee_id IN %s" % cl,
                             args).fetchone()["c"])
        return layout(user, sess, title, active, html, unread,
                      flash_html(query), counts)

    def route_get(self, db, user, sess, path, query):
        is_mgr = user["role"] in ("manager", "hr")
        is_hr = user["role"] == "hr"
        routes = {
            "/": lambda: V.dashboard(db, user, sess, query),
            "/attendance": lambda: V.attendance(db, user, sess, query),
            "/leave": lambda: V.leave(db, user, sess, query),
            "/calendar": lambda: V.calendar_page(db, user, sess, query),
            "/corrections": lambda: V.corrections(db, user, sess, query),
            "/directory": lambda: V.directory(db, user, sess, query),
            "/notifications": lambda: V.notifications_page(db, user, sess, query),
            "/qr": lambda: V.qr_confirm(db, user, sess, query),
        }
        if is_mgr:
            routes.update({
                "/team": lambda: V.team(db, user, sess, query),
                "/approvals": lambda: V.approvals(db, user, sess, query),
                "/reports": lambda: V.reports(db, user, sess, query),
            })
        if is_hr:
            routes.update({
                "/admin/employees": lambda: V.admin_employees(db, user, sess, query),
                "/shifts": lambda: V.shifts_page(db, user, sess, query),
                "/holidays": lambda: V.holidays_page(db, user, sess, query),
                "/onboarding": lambda: V.onboarding(db, user, sess, query),
                "/kiosk": lambda: V.kiosk(db, user, sess, query,
                                          self.headers.get("Host",
                                                           "127.0.0.1:%d" % PORT)),
                "/audit": lambda: V.audit_page(db, user, sess, query),
            })
        if path in routes:
            return routes[path]()
        if path.startswith("/employee/"):
            tail = path.rsplit("/", 1)[-1]
            if tail.isdigit():
                return V.profile(db, user, sess, query, int(tail))
        return None

    # ---- CSV export (manager/HR scope-aware; employees get their own data)
    def export_csv(self, db, user, query):
        y, m = V.month_param(query)
        ms, me = V.month_bounds(y, m)
        who = query.get("who", [""])[0]
        kind = query.get("kind", ["daily"])[0]
        if who == "me" or user["role"] == "employee":
            ids = [user["id"]]
        else:
            ids = V.team_ids(db, user) + [user["id"]]
        cl, args = V.scope_clause(ids)
        out = io.StringIO()
        w = csv.writer(out)
        if kind == "summary":
            w.writerow(["Employee", "Code", "Department", "Present", "WFH days",
                        "Leave", "Absent", "Late days", "Hours", "Overtime h"])
            rows = db.execute(
                "SELECT e.first_name, e.last_name, e.emp_code, d.name dept,"
                " SUM(CASE WHEN a.status IN('present','wfh') THEN 1 ELSE 0 END) p,"
                " SUM(CASE WHEN a.status='wfh' THEN 1 ELSE 0 END) wfh,"
                " SUM(CASE WHEN a.status='leave' THEN 1 ELSE 0 END) lv,"
                " SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) ab,"
                " SUM(CASE WHEN a.late_minutes>0 THEN 1 ELSE 0 END) late,"
                " SUM(a.work_minutes) wm, SUM(a.overtime_minutes) ot"
                " FROM employees e LEFT JOIN departments d ON d.id=e.department_id"
                " LEFT JOIN attendance a ON a.employee_id=e.id AND a.date BETWEEN"
                " ? AND ? WHERE e.id IN %s GROUP BY e.id ORDER BY e.first_name" % cl,
                [ms.isoformat(), me.isoformat()] + args).fetchall()
            for r in rows:
                w.writerow([("%s %s" % (r["first_name"], r["last_name"])),
                            r["emp_code"], r["dept"] or "", r["p"] or 0,
                            r["wfh"] or 0, r["lv"] or 0, r["ab"] or 0,
                            r["late"] or 0,
                            round((r["wm"] or 0) / 60, 1),
                            round((r["ot"] or 0) / 60, 1)])
        else:
            w.writerow(["Date", "Employee", "Code", "Status", "Mode", "Clock in",
                        "Clock out", "Work h", "Break min", "OT min", "Late min",
                        "Notes"])
            rows = db.execute(
                "SELECT a.*, e.first_name, e.last_name, e.emp_code FROM attendance a"
                " JOIN employees e ON e.id=a.employee_id WHERE a.employee_id IN %s"
                " AND a.date BETWEEN ? AND ? ORDER BY a.date, e.first_name" % cl,
                args + [ms.isoformat(), me.isoformat()]).fetchall()
            for a in rows:
                w.writerow([a["date"], "%s %s" % (a["first_name"], a["last_name"]),
                            a["emp_code"], a["status"], a["mode"],
                            a["clock_in"] or "", a["clock_out"] or "",
                            round(a["work_minutes"] / 60, 2), a["break_minutes"],
                            a["overtime_minutes"], a["late_minutes"], a["notes"]])
        D.audit(db, user["id"], "report.export", "attendance",
                "%04d-%02d" % (y, m), "kind=%s rows=%d" % (kind, len(rows)))
        db.commit()
        body = out.getvalue().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         'attachment; filename="attendance-%s-%04d-%02d.csv"'
                         % (kind, y, m))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- POST
    def do_POST(self):
        db = D.get_db()
        try:
            path = urlparse(self.path).path.rstrip("/")
            form = self.form()
            if path == "/login":
                self.handle_login(db, form)
                return
            sess = get_session(db, self.cookie_token())
            if not sess:
                self.redirect("/login?err=" + quote("Session expired. Sign in again."))
                return
            if form.get("csrf") != sess["csrf"]:
                self.redirect("/", err="Security check failed. Please retry.")
                return
            user = V.get_emp(db, sess["employee_id"])
            handler = getattr(self, "post_" +
                              path.strip("/").replace("/", "_").replace("-", "_"),
                              None)
            if handler is None:
                self.redirect("/", err="Unknown action.")
                return
            handler(db, user, sess, form)
        except Exception as e:  # pragma: no cover
            import traceback
            traceback.print_exc()
            self.send_html("<h1>500</h1><pre>%s</pre>" % esc(e), 500)
        finally:
            db.close()

    # ---- auth actions
    def handle_login(self, db, form):
        email = form.get("email", "").strip().lower()
        pw = form.get("password", "")
        e = db.execute("SELECT * FROM employees WHERE lower(email)=?",
                       (email,)).fetchone()
        if not e or not D.verify_password(e, pw):
            D.audit(db, None, "auth.login-failed", "employee", email, "")
            db.commit()
            self.redirect("/login", err="Invalid email or password.")
            return
        if e["status"] == "exited":
            self.redirect("/login", err="This account has been deactivated.")
            return
        token = create_session(db, e["id"])
        D.audit(db, e["id"], "auth.login", "employee", e["id"], "")
        db.commit()
        cookie = ("orbit_session=%s; HttpOnly; Path=/; Max-Age=%d; SameSite=Lax"
                  % (token, SESSION_HOURS * 3600))
        self.redirect("/", ok="Welcome back, %s!" % e["first_name"],
                      set_cookie=cookie)

    def post_logout(self, db, user, sess, form):
        db.execute("DELETE FROM sessions WHERE token=?", (sess["token"],))
        D.audit(db, user["id"], "auth.logout", "employee", user["id"], "")
        db.commit()
        self.redirect("/login",
                      set_cookie="orbit_session=; Path=/; Max-Age=0")

    # ---- attendance actions
    def post_clock_in(self, db, user, sess, form):
        self._clock_in(db, user, form.get("mode", "office"), "")

    def post_qr_checkin(self, db, user, sess, form):
        if form.get("t", "") != D.qr_token_today(db):
            self.redirect("/attendance", err="QR token invalid or expired.")
            return
        self._clock_in(db, user, "office", "QR kiosk")

    def _clock_in(self, db, user, mode, note):
        if mode not in ("office", "wfh"):
            mode = "office"
        today = date.today().isoformat()
        a = db.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?",
                       (user["id"], today)).fetchone()
        if a and a["clock_in"]:
            self.redirect("/attendance", err="You are already clocked in today.")
            return
        if a and a["status"] == "leave":
            self.redirect("/attendance",
                          err="You are on approved leave today. Cancel it first.")
            return
        shift = D.get_shift(db, user)
        now = D.now()
        late = D.compute_late(shift, now)
        off = (D.is_weekly_off(shift, date.today())
               or today in D.holidays_map(db))
        if off:
            late = 0
            note = (note + " · " if note else "") + "worked on off day"
        status = "wfh" if mode == "wfh" else "present"
        if a:
            db.execute("UPDATE attendance SET clock_in=?, late_minutes=?, status=?,"
                       " mode=?, notes=? WHERE id=?",
                       (now.strftime(D.TS_FMT), late, status, mode, note, a["id"]))
        else:
            db.execute("INSERT INTO attendance(employee_id,date,clock_in,"
                       "late_minutes,status,mode,notes) VALUES(?,?,?,?,?,?,?)",
                       (user["id"], today, now.strftime(D.TS_FMT), late, status,
                        mode, note))
        D.audit(db, user["id"], "attendance.clock-in", "attendance", today,
                "mode=%s late=%d %s" % (mode, late, note))
        if late > 30 and user["manager_id"]:
            D.notify(db, user["manager_id"],
                     "%s arrived %d min late" % (D.emp_name(user), late),
                     "Clock-in at %s (grace %d min)." %
                     (now.strftime("%H:%M"), shift["grace_minutes"]),
                     "warn", "/team")
        db.commit()
        msg = "Clocked in at %s" % now.strftime("%H:%M")
        if late:
            msg += " — %d min past grace" % late
        if off:
            msg += " (off day — eligible for comp-off)"
        self.redirect("/attendance", ok=msg)

    def post_clock_out(self, db, user, sess, form):
        today = date.today().isoformat()
        a = db.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?",
                       (user["id"], today)).fetchone()
        if not a or not a["clock_in"]:
            self.redirect("/attendance", err="You have not clocked in today.")
            return
        if a["clock_out"]:
            self.redirect("/attendance", err="Already clocked out.")
            return
        now = D.now()
        # close any open break
        br = db.execute("SELECT * FROM breaks WHERE attendance_id=? AND end_ts IS"
                        " NULL", (a["id"],)).fetchone()
        brk_total = a["break_minutes"]
        if br:
            extra = D.mins_between(D.parse_ts(br["start_ts"]), now)
            db.execute("UPDATE breaks SET end_ts=? WHERE id=?",
                       (now.strftime(D.TS_FMT), br["id"]))
            brk_total += max(0, extra)
        cin = D.parse_ts(a["clock_in"])
        work = max(0, D.mins_between(cin, now) - brk_total)
        shift = D.get_shift(db, user)
        ot = max(0, work - D.nominal_minutes(shift))
        db.execute("UPDATE attendance SET clock_out=?, break_minutes=?,"
                   " work_minutes=?, overtime_minutes=? WHERE id=?",
                   (now.strftime(D.TS_FMT), brk_total, work, ot, a["id"]))
        D.audit(db, user["id"], "attendance.clock-out", "attendance", today,
                "work=%dm ot=%dm" % (work, ot))
        db.commit()
        self.redirect("/attendance", ok="Clocked out. Worked %s today%s."
                      % (D.fmt_mins(work),
                         ", +%s overtime" % D.fmt_mins(ot) if ot else ""))

    def post_break_start(self, db, user, sess, form):
        a = db.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?",
                       (user["id"], date.today().isoformat())).fetchone()
        if not a or not a["clock_in"] or a["clock_out"]:
            self.redirect("/attendance", err="You can only take a break while "
                          "clocked in.")
            return
        if db.execute("SELECT 1 FROM breaks WHERE attendance_id=? AND end_ts IS"
                      " NULL", (a["id"],)).fetchone():
            self.redirect("/attendance", err="A break is already running.")
            return
        db.execute("INSERT INTO breaks(attendance_id,start_ts) VALUES(?,?)",
                   (a["id"], D.now().strftime(D.TS_FMT)))
        db.commit()
        self.redirect("/attendance", ok="Break started. Step away ☕")

    def post_break_end(self, db, user, sess, form):
        a = db.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?",
                       (user["id"], date.today().isoformat())).fetchone()
        br = db.execute("SELECT * FROM breaks WHERE attendance_id=? AND end_ts IS"
                        " NULL", (a["id"],)).fetchone() if a else None
        if not br:
            self.redirect("/attendance", err="No break is running.")
            return
        now = D.now()
        mins = max(0, D.mins_between(D.parse_ts(br["start_ts"]), now))
        db.execute("UPDATE breaks SET end_ts=? WHERE id=?",
                   (now.strftime(D.TS_FMT), br["id"]))
        db.execute("UPDATE attendance SET break_minutes=break_minutes+? WHERE id=?",
                   (mins, a["id"]))
        db.commit()
        self.redirect("/attendance", ok="Break ended (%s)." % D.fmt_mins(mins))

    # ---- leave actions
    def post_leave_apply(self, db, user, sess, form):
        try:
            start = date.fromisoformat(form.get("start", ""))
            end = date.fromisoformat(form.get("end", ""))
            type_id = int(form.get("type_id", "0"))
        except ValueError:
            self.redirect("/leave", err="Invalid dates.")
            return
        reason = form.get("reason", "").strip()
        if not reason:
            self.redirect("/leave", err="Please give a reason.")
            return
        if end < start:
            self.redirect("/leave", err="End date is before start date.")
            return
        if (end - start).days > 30:
            self.redirect("/leave", err="Leave ranges above 30 days are not "
                          "allowed. Contact HR.")
            return
        lt = db.execute("SELECT * FROM leave_types WHERE id=?",
                        (type_id,)).fetchone()
        if not lt:
            self.redirect("/leave", err="Unknown leave type.")
            return
        days = D.working_days(db, D.get_shift(db, user), start, end)
        if not days:
            self.redirect("/leave", err="That range has no working days (weekly "
                          "offs/holidays only).")
            return
        bal = db.execute("SELECT * FROM leave_balances WHERE employee_id=? AND"
                         " leave_type_id=? AND year=?",
                         (user["id"], type_id, start.year)).fetchone()
        avail = (bal["allocated"] - bal["used"]) if bal else 0
        if len(days) > avail:
            self.redirect("/leave", err="Insufficient %s balance: need %d, have %g."
                          % (lt["name"], len(days), avail))
            return
        overlap = db.execute(
            "SELECT 1 FROM leave_requests WHERE employee_id=? AND status IN"
            " ('pending','approved') AND NOT (end_date<? OR start_date>?)",
            (user["id"], start.isoformat(), end.isoformat())).fetchone()
        if overlap:
            self.redirect("/leave", err="You already have a request overlapping "
                          "those dates.")
            return
        db.execute("INSERT INTO leave_requests(employee_id,leave_type_id,"
                   "start_date,end_date,days,reason,created_at)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (user["id"], type_id, days[0].isoformat(), days[-1].isoformat(),
                    len(days), reason, D.now().strftime("%Y-%m-%d %H:%M:%S")))
        rid = db.execute("SELECT last_insert_rowid() i").fetchone()["i"]
        for nid in D.reviewer_ids(db, user):
            D.notify(db, nid, "Leave request from %s" % D.emp_name(user),
                     "%s, %s → %s (%d days). Review in Approvals." %
                     (lt["name"], days[0], days[-1], len(days)),
                     "action", "/approvals")
        D.audit(db, user["id"], "leave.apply", "leave_request", rid,
                "%s %s→%s %dd" % (lt["name"], days[0], days[-1], len(days)))
        db.commit()
        self.redirect("/leave", ok="Request submitted: %d working day(s) of %s."
                      % (len(days), lt["name"]))

    def post_leave_cancel(self, db, user, sess, form):
        r = db.execute("SELECT * FROM leave_requests WHERE id=? AND employee_id=?",
                       (form.get("id", "0"), user["id"])).fetchone()
        if not r or r["status"] != "pending":
            self.redirect("/leave", err="Only pending requests can be cancelled.")
            return
        db.execute("UPDATE leave_requests SET status='cancelled' WHERE id=?",
                   (r["id"],))
        D.audit(db, user["id"], "leave.cancel", "leave_request", r["id"], "")
        db.commit()
        self.redirect("/leave", ok="Request cancelled.")

    def _can_review(self, db, user, target_emp_id):
        if user["role"] == "hr":
            return target_emp_id != user["id"]
        if user["role"] == "manager":
            t = db.execute("SELECT manager_id FROM employees WHERE id=?",
                           (target_emp_id,)).fetchone()
            return t and t["manager_id"] == user["id"]
        return False

    def post_leave_review(self, db, user, sess, form):
        r = db.execute(
            "SELECT lr.*, lt.name tname FROM leave_requests lr"
            " JOIN leave_types lt ON lt.id=lr.leave_type_id WHERE lr.id=?",
            (form.get("id", "0"),)).fetchone()
        decision = form.get("decision", "")
        comment = form.get("comment", "").strip()
        if not r or r["status"] != "pending" or decision not in ("approved",
                                                                 "rejected"):
            self.redirect("/approvals", err="Request not found or already decided.")
            return
        if not self._can_review(db, user, r["employee_id"]):
            self.redirect("/approvals", err="You are not authorized to review "
                          "this request.")
            return
        db.execute("UPDATE leave_requests SET status=?, reviewer_id=?,"
                   " review_comment=?, reviewed_at=? WHERE id=?",
                   (decision, user["id"], comment,
                    D.now().strftime("%Y-%m-%d %H:%M:%S"), r["id"]))
        if decision == "approved":
            db.execute("UPDATE leave_balances SET used=used+? WHERE employee_id=?"
                       " AND leave_type_id=? AND year=?",
                       (r["days"], r["employee_id"], r["leave_type_id"],
                        int(r["start_date"][:4])))
            emp = V.get_emp(db, r["employee_id"])
            for d in D.working_days(db, D.get_shift(db, emp),
                                    date.fromisoformat(r["start_date"]),
                                    date.fromisoformat(r["end_date"])):
                db.execute(
                    "INSERT INTO attendance(employee_id,date,status,notes)"
                    " VALUES(?,?,'leave',?) ON CONFLICT(employee_id,date) DO UPDATE"
                    " SET status='leave', notes=excluded.notes, clock_in=NULL,"
                    " clock_out=NULL, work_minutes=0, overtime_minutes=0,"
                    " late_minutes=0, break_minutes=0, missed_clockout=0",
                    (r["employee_id"], d.isoformat(), r["tname"]))
        D.notify(db, r["employee_id"],
                 "Leave %s" % decision,
                 "Your %s (%s → %s) was %s by %s.%s" %
                 (r["tname"], r["start_date"], r["end_date"], decision,
                  D.emp_name(user), " “%s”" % comment if comment else ""),
                 "success" if decision == "approved" else "warn", "/leave")
        D.audit(db, user["id"], "leave." + decision, "leave_request", r["id"],
                comment)
        db.commit()
        self.redirect("/approvals", ok="Leave %s." % decision)

    # ---- comp-off
    def post_compoff_apply(self, db, user, sess, form):
        try:
            wd = date.fromisoformat(form.get("work_date", ""))
        except ValueError:
            self.redirect("/leave", err="Invalid date.")
            return
        reason = form.get("reason", "").strip()
        if not reason:
            self.redirect("/leave", err="Please give a reason.")
            return
        if wd > date.today():
            self.redirect("/leave", err="Comp-off is claimed after you worked, "
                          "not in advance.")
            return
        shift = D.get_shift(db, user)
        if not D.is_weekly_off(shift, wd) and wd.isoformat() not in D.holidays_map(db):
            self.redirect("/leave", err="%s was a regular working day — comp-off "
                          "applies to weekly offs and holidays." % wd.isoformat())
            return
        a = db.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?"
                       " AND clock_in IS NOT NULL",
                       (user["id"], wd.isoformat())).fetchone()
        if not a:
            self.redirect("/leave", err="No clock-in found on %s, so there is "
                          "nothing to credit." % wd.isoformat())
            return
        if db.execute("SELECT 1 FROM compoffs WHERE employee_id=? AND work_date=?"
                      " AND status IN ('pending','approved')",
                      (user["id"], wd.isoformat())).fetchone():
            self.redirect("/leave", err="You already claimed comp-off for that day.")
            return
        db.execute("INSERT INTO compoffs(employee_id,work_date,reason,created_at)"
                   " VALUES(?,?,?,?)",
                   (user["id"], wd.isoformat(), reason,
                    D.now().strftime("%Y-%m-%d %H:%M:%S")))
        for nid in D.reviewer_ids(db, user):
            D.notify(db, nid, "Comp-off request from %s" % D.emp_name(user),
                     "Worked on %s (off day). Review in Approvals." % wd.isoformat(),
                     "action", "/approvals")
        D.audit(db, user["id"], "compoff.apply", "compoff", wd.isoformat(), reason)
        db.commit()
        self.redirect("/leave", ok="Comp-off request submitted for %s."
                      % wd.isoformat())

    def post_compoff_review(self, db, user, sess, form):
        r = db.execute("SELECT * FROM compoffs WHERE id=?",
                       (form.get("id", "0"),)).fetchone()
        decision = form.get("decision", "")
        if not r or r["status"] != "pending" or decision not in ("approved",
                                                                 "rejected"):
            self.redirect("/approvals", err="Request not found or already decided.")
            return
        if not self._can_review(db, user, r["employee_id"]):
            self.redirect("/approvals", err="Not authorized.")
            return
        comment = form.get("comment", "").strip()
        db.execute("UPDATE compoffs SET status=?, reviewer_id=?, review_comment=?,"
                   " reviewed_at=? WHERE id=?",
                   (decision, user["id"], comment,
                    D.now().strftime("%Y-%m-%d %H:%M:%S"), r["id"]))
        if decision == "approved":
            year = int(r["work_date"][:4])
            ct = db.execute("SELECT id FROM leave_types WHERE name='Comp Off'"
                            ).fetchone()
            db.execute(
                "INSERT INTO leave_balances(employee_id,leave_type_id,year,"
                "allocated,used) VALUES(?,?,?,1,0) ON CONFLICT(employee_id,"
                "leave_type_id,year) DO UPDATE SET allocated=allocated+1",
                (r["employee_id"], ct["id"], year))
        D.notify(db, r["employee_id"], "Comp-off %s" % decision,
                 "Your comp-off for %s was %s by %s." %
                 (r["work_date"], decision, D.emp_name(user)),
                 "success" if decision == "approved" else "warn", "/leave")
        D.audit(db, user["id"], "compoff." + decision, "compoff", r["id"], comment)
        db.commit()
        self.redirect("/approvals", ok="Comp-off %s." % decision)

    # ---- corrections
    def post_corrections_apply(self, db, user, sess, form):
        try:
            d = date.fromisoformat(form.get("date", ""))
        except ValueError:
            self.redirect("/corrections", err="Invalid date.")
            return
        if d > date.today():
            self.redirect("/corrections", err="Cannot correct a future date.")
            return
        rin, rout = form.get("in", "").strip(), form.get("out", "").strip()
        reason = form.get("reason", "").strip()
        if not reason or (not rin and not rout):
            self.redirect("/corrections", err="Give a reason and at least one "
                          "corrected time.")
            return
        for t in (rin, rout):
            if t:
                try:
                    D.parse_hm(t)
                except (ValueError, IndexError):
                    self.redirect("/corrections", err="Times must be HH:MM.")
                    return
        if rin and rout and rout <= rin:
            self.redirect("/corrections", err="Clock-out must be after clock-in.")
            return
        db.execute("INSERT INTO corrections(employee_id,date,requested_in,"
                   "requested_out,reason,created_at) VALUES(?,?,?,?,?,?)",
                   (user["id"], d.isoformat(), rin or None, rout or None, reason,
                    D.now().strftime("%Y-%m-%d %H:%M:%S")))
        for nid in D.reviewer_ids(db, user):
            D.notify(db, nid, "Attendance correction from %s" % D.emp_name(user),
                     "For %s. Review in Approvals." % d.isoformat(),
                     "action", "/approvals")
        D.audit(db, user["id"], "correction.apply", "correction", d.isoformat(),
                reason)
        db.commit()
        self.redirect("/corrections", ok="Correction submitted for approval.")

    def post_corrections_review(self, db, user, sess, form):
        r = db.execute("SELECT * FROM corrections WHERE id=?",
                       (form.get("id", "0"),)).fetchone()
        decision = form.get("decision", "")
        if not r or r["status"] != "pending" or decision not in ("approved",
                                                                 "rejected"):
            self.redirect("/approvals", err="Request not found or already decided.")
            return
        if not self._can_review(db, user, r["employee_id"]):
            self.redirect("/approvals", err="Not authorized.")
            return
        comment = form.get("comment", "").strip()
        db.execute("UPDATE corrections SET status=?, reviewer_id=?,"
                   " review_comment=?, reviewed_at=? WHERE id=?",
                   (decision, user["id"], comment,
                    D.now().strftime("%Y-%m-%d %H:%M:%S"), r["id"]))
        if decision == "approved":
            emp = V.get_emp(db, r["employee_id"])
            shift = D.get_shift(db, emp)
            a = db.execute("SELECT * FROM attendance WHERE employee_id=? AND"
                           " date=?", (r["employee_id"], r["date"])).fetchone()
            cin = ("%s %s" % (r["date"], r["requested_in"])
                   if r["requested_in"] else (a["clock_in"] if a else None))
            cout = ("%s %s" % (r["date"], r["requested_out"])
                    if r["requested_out"] else (a["clock_out"] if a else None))
            work = ot = late = 0
            brk = a["break_minutes"] if a else 0
            if cin:
                late = D.compute_late(shift, D.parse_ts(cin))
            if cin and cout:
                work = max(0, D.mins_between(D.parse_ts(cin), D.parse_ts(cout))
                           - brk)
                ot = max(0, work - D.nominal_minutes(shift))
            if a:
                db.execute("UPDATE attendance SET clock_in=?, clock_out=?,"
                           " work_minutes=?, overtime_minutes=?, late_minutes=?,"
                           " status='present', missed_clockout=0, notes=? WHERE"
                           " id=?",
                           (cin, cout, work, ot, late,
                            ((a["notes"] + " · ") if a["notes"] else "")
                            + "corrected", a["id"]))
            else:
                db.execute("INSERT INTO attendance(employee_id,date,clock_in,"
                           "clock_out,work_minutes,overtime_minutes,late_minutes,"
                           "status,notes) VALUES(?,?,?,?,?,?,?,'present',"
                           "'corrected')",
                           (r["employee_id"], r["date"], cin, cout, work, ot,
                            late))
        D.notify(db, r["employee_id"], "Correction %s" % decision,
                 "Your attendance correction for %s was %s by %s." %
                 (r["date"], decision, D.emp_name(user)),
                 "success" if decision == "approved" else "warn", "/corrections")
        D.audit(db, user["id"], "correction." + decision, "correction", r["id"],
                comment)
        db.commit()
        self.redirect("/approvals", ok="Correction %s." % decision)

    # ---- HR admin actions
    def _require_hr(self, user):
        if user["role"] != "hr":
            self.redirect("/", err="HR access required.")
            return False
        return True

    def _employee_form_fields(self, db, form, require_email_unique_except=None):
        first = form.get("first_name", "").strip()
        last = form.get("last_name", "").strip()
        email = form.get("email", "").strip().lower()
        if not first or not last or "@" not in email:
            return None, "Name and a valid email are required."
        q = "SELECT id FROM employees WHERE lower(email)=?"
        args = [email]
        if require_email_unique_except:
            q += " AND id!=?"
            args.append(require_email_unique_except)
        if db.execute(q, args).fetchone():
            return None, "That email is already in use."
        try:
            date.fromisoformat(form.get("date_joined", ""))
        except ValueError:
            return None, "Invalid joining date."
        role = form.get("role", "employee")
        status = form.get("status", "active")
        if role not in ("employee", "manager", "hr") or status not in (
                "onboarding", "active", "exited"):
            return None, "Invalid role or status."
        def iv(k):
            v = form.get(k, "")
            return int(v) if v.isdigit() else None
        return {"first_name": first, "last_name": last, "email": email,
                "phone": form.get("phone", "").strip(),
                "department_id": iv("department_id"),
                "designation_id": iv("designation_id"),
                "manager_id": iv("manager_id"),
                "shift_id": iv("shift_id") or 1,
                "date_joined": form.get("date_joined"),
                "role": role, "status": status}, None

    def post_admin_employees_create(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        f, err = self._employee_form_fields(db, form)
        if err:
            self.redirect("/admin/employees", err=err)
            return
        n = db.execute("SELECT COUNT(*) c FROM employees").fetchone()["c"]
        salt, ph = D.new_password("demo123")
        import random as _r
        db.execute(
            "INSERT INTO employees(emp_code,first_name,last_name,email,phone,"
            "password_salt,password_hash,role,department_id,designation_id,"
            "manager_id,shift_id,date_joined,status,avatar_color)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("EMP%03d" % (n + 1), f["first_name"], f["last_name"], f["email"],
             f["phone"], salt, ph, f["role"], f["department_id"],
             f["designation_id"], f["manager_id"], f["shift_id"],
             f["date_joined"], f["status"],
             _r.choice(D.AVATAR_COLORS)))
        new_id = db.execute("SELECT last_insert_rowid() i").fetchone()["i"]
        year = date.today().year
        for lt in db.execute("SELECT * FROM leave_types"):
            db.execute("INSERT INTO leave_balances(employee_id,leave_type_id,year,"
                       "allocated) VALUES(?,?,?,?)",
                       (new_id, lt["id"], year, lt["annual_quota"]))
        if f["status"] == "onboarding":
            for t in D.DEFAULT_ONBOARDING_TASKS:
                db.execute("INSERT INTO onboarding_tasks(employee_id,task)"
                           " VALUES(?,?)", (new_id, t))
        if f["manager_id"]:
            D.notify(db, f["manager_id"], "%s %s joins your team"
                     % (f["first_name"], f["last_name"]),
                     "Joining on %s as a new report." % f["date_joined"],
                     "info", "/team")
        D.audit(db, user["id"], "employee.create", "employee", new_id, f["email"])
        db.commit()
        self.redirect("/admin/employees", ok="%s %s added (password demo123)."
                      % (f["first_name"], f["last_name"]))

    def post_admin_employees_update(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        eid = form.get("id", "")
        e = db.execute("SELECT * FROM employees WHERE id=?", (eid,)).fetchone()
        if not e:
            self.redirect("/admin/employees", err="Employee not found.")
            return
        f, err = self._employee_form_fields(db, form,
                                            require_email_unique_except=e["id"])
        if err:
            self.redirect("/admin/employees?edit=%s" % eid, err=err)
            return
        if f["manager_id"] == e["id"]:
            self.redirect("/admin/employees?edit=%s" % eid,
                          err="An employee cannot report to themselves.")
            return
        was_onboarding = e["status"]
        db.execute(
            "UPDATE employees SET first_name=?, last_name=?, email=?, phone=?,"
            " department_id=?, designation_id=?, manager_id=?, shift_id=?,"
            " date_joined=?, role=?, status=? WHERE id=?",
            (f["first_name"], f["last_name"], f["email"], f["phone"],
             f["department_id"], f["designation_id"], f["manager_id"],
             f["shift_id"], f["date_joined"], f["role"], f["status"], e["id"]))
        if (f["status"] == "onboarding" and was_onboarding != "onboarding"
                and not db.execute("SELECT 1 FROM onboarding_tasks WHERE"
                                   " employee_id=?", (e["id"],)).fetchone()):
            for t in D.DEFAULT_ONBOARDING_TASKS:
                db.execute("INSERT INTO onboarding_tasks(employee_id,task)"
                           " VALUES(?,?)", (e["id"], t))
        if f["status"] == "exited":
            db.execute("DELETE FROM sessions WHERE employee_id=?", (e["id"],))
        D.audit(db, user["id"], "employee.update", "employee", e["id"],
                "status=%s role=%s" % (f["status"], f["role"]))
        db.commit()
        self.redirect("/admin/employees", ok="%s %s updated."
                      % (f["first_name"], f["last_name"]))

    def post_shifts_create(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        name = form.get("name", "").strip()
        start, end = form.get("start", ""), form.get("end", "")
        try:
            D.parse_hm(start), D.parse_hm(end)
        except (ValueError, IndexError):
            self.redirect("/shifts", err="Invalid start/end time.")
            return
        if not name:
            self.redirect("/shifts", err="Shift needs a name.")
            return
        if end <= start:
            self.redirect("/shifts", err="End must be after start (overnight "
                          "shifts not supported in this demo).")
            return
        brk = max(0, min(240, int(form.get("brk", "60") or 60)))
        grace = max(0, min(120, int(form.get("grace", "10") or 10)))
        # checkboxes arrive as repeated keys; our form() keeps the first only,
        # so re-parse raw for multi-values
        offs = ",".join(sorted(set(
            x for x in self._multi_values("offs") if x in D.WEEKDAY_KEYS),
            key=D.WEEKDAY_KEYS.index))
        db.execute("INSERT INTO shifts(name,start_time,end_time,break_minutes,"
                   "grace_minutes,weekly_offs) VALUES(?,?,?,?,?,?)",
                   (name, start, end, brk, grace, offs or "Sat,Sun"))
        D.audit(db, user["id"], "shift.create", "shift", name,
                "%s-%s offs=%s" % (start, end, offs))
        db.commit()
        self.redirect("/shifts", ok="Shift “%s” created." % name)

    def post_shifts_assign(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        e = db.execute("SELECT * FROM employees WHERE id=?",
                       (form.get("employee_id", "0"),)).fetchone()
        s = db.execute("SELECT * FROM shifts WHERE id=?",
                       (form.get("shift_id", "0"),)).fetchone()
        if not e or not s:
            self.redirect("/shifts", err="Employee or shift not found.")
            return
        db.execute("UPDATE employees SET shift_id=? WHERE id=?", (s["id"], e["id"]))
        D.notify(db, e["id"], "Shift changed",
                 "You are now on %s (%s–%s, offs %s)." %
                 (s["name"], s["start_time"], s["end_time"], s["weekly_offs"]),
                 "info", "/attendance")
        D.audit(db, user["id"], "shift.assign", "employee", e["id"], s["name"])
        db.commit()
        self.redirect("/shifts", ok="%s moved to %s." % (D.emp_name(e), s["name"]))

    def post_holidays_create(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        name = form.get("name", "").strip()
        try:
            d = date.fromisoformat(form.get("date", ""))
        except ValueError:
            self.redirect("/holidays", err="Invalid date.")
            return
        if not name:
            self.redirect("/holidays", err="Holiday needs a name.")
            return
        if db.execute("SELECT 1 FROM holidays WHERE date=?",
                      (d.isoformat(),)).fetchone():
            self.redirect("/holidays", err="There is already a holiday on %s."
                          % d.isoformat())
            return
        db.execute("INSERT INTO holidays(name,date) VALUES(?,?)",
                   (name, d.isoformat()))
        D.audit(db, user["id"], "holiday.create", "holiday", d.isoformat(), name)
        db.commit()
        self.redirect("/holidays", ok="Holiday “%s” added." % name)

    def post_holidays_delete(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        h = db.execute("SELECT * FROM holidays WHERE id=?",
                       (form.get("id", "0"),)).fetchone()
        if not h:
            self.redirect("/holidays", err="Holiday not found.")
            return
        db.execute("DELETE FROM holidays WHERE id=?", (h["id"],))
        D.audit(db, user["id"], "holiday.delete", "holiday", h["date"], h["name"])
        db.commit()
        self.redirect("/holidays", ok="Deleted %s." % h["name"])

    def post_onboarding_toggle(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        t = db.execute("SELECT * FROM onboarding_tasks WHERE id=?",
                       (form.get("task_id", "0"),)).fetchone()
        if not t:
            self.redirect("/onboarding", err="Task not found.")
            return
        db.execute("UPDATE onboarding_tasks SET done=?, done_at=? WHERE id=?",
                   (0 if t["done"] else 1,
                    None if t["done"] else D.now().strftime("%Y-%m-%d %H:%M:%S"),
                    t["id"]))
        db.commit()
        self.redirect("/onboarding")

    def post_onboarding_add_task(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        task = form.get("task", "").strip()
        eid = form.get("employee_id", "0")
        if not task or not db.execute("SELECT 1 FROM employees WHERE id=?",
                                      (eid,)).fetchone():
            self.redirect("/onboarding", err="Invalid task.")
            return
        db.execute("INSERT INTO onboarding_tasks(employee_id,task) VALUES(?,?)",
                   (eid, task))
        db.commit()
        self.redirect("/onboarding", ok="Task added.")

    def post_onboarding_activate(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        e = db.execute("SELECT * FROM employees WHERE id=? AND status='onboarding'",
                       (form.get("employee_id", "0"),)).fetchone()
        if not e:
            self.redirect("/onboarding", err="Employee not found.")
            return
        open_tasks = db.execute("SELECT COUNT(*) c FROM onboarding_tasks WHERE"
                                " employee_id=? AND done=0",
                                (e["id"],)).fetchone()["c"]
        if open_tasks:
            self.redirect("/onboarding", err="%d task(s) still open." % open_tasks)
            return
        db.execute("UPDATE employees SET status='active' WHERE id=?", (e["id"],))
        D.notify(db, e["id"], "Welcome aboard!",
                 "Your onboarding is complete — you can start clocking in.",
                 "success", "/")
        if e["manager_id"]:
            D.notify(db, e["manager_id"], "%s is now active" % D.emp_name(e),
                     "Onboarding completed.", "info", "/team")
        D.audit(db, user["id"], "onboarding.complete", "employee", e["id"], "")
        db.commit()
        self.redirect("/onboarding", ok="%s is now active." % D.emp_name(e))

    def post_kiosk_rotate(self, db, user, sess, form):
        if not self._require_hr(user):
            return
        D.qr_token_today(db, rotate=True)
        D.audit(db, user["id"], "kiosk.rotate-token", "qr", date.today().isoformat(),
                "")
        db.commit()
        self.redirect("/kiosk", ok="QR token rotated — old codes are now invalid.")

    def post_notifications_read(self, db, user, sess, form):
        db.execute("UPDATE notifications SET is_read=1 WHERE employee_id=?",
                   (user["id"],))
        db.commit()
        self.redirect("/notifications", ok="All notifications marked read.")


def main():
    D.init()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("OrbitHR running at http://127.0.0.1:%d" % PORT)
    print("Demo credentials are documented in README.md")
    server.serve_forever()


if __name__ == "__main__":
    main()
