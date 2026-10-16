"""OrbitHR - GET page renderers. Each view returns (title, active_nav, html)."""
from datetime import date, datetime, timedelta
from urllib.parse import quote

import db as D
import qr as QR
from ui import (avatar, badge, bar_chart, card, donut, esc, hidden_csrf,
                month_cal, page_head, sbadge, stat, table)


# ----------------------------------------------------------------- utilities

def month_param(query):
    m = query.get("m", [""])[0]
    try:
        y, mo = m.split("-")
        return int(y), int(mo)
    except ValueError:
        t = date.today()
        return t.year, t.month


def month_bounds(y, m):
    start = date(y, m, 1)
    end = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)
    return start, end


def month_nav(path, y, m, extra=""):
    prev = date(y, m, 1) - timedelta(days=1)
    nxt = date(y, m, 28) + timedelta(days=5)
    return ('<div class="hd" style="margin-bottom:12px">'
            '<a class="btn ghost sm" href="%s?m=%04d-%02d%s">&larr; %s</a>'
            '<b style="font-size:15px">%s</b>'
            '<a class="btn ghost sm" href="%s?m=%04d-%02d%s">%s &rarr;</a></div>'
            % (path, prev.year, prev.month, extra, prev.strftime("%b"),
               date(y, m, 1).strftime("%B %Y"),
               path, nxt.year, nxt.month, extra, nxt.strftime("%b")))


def get_emp(db, emp_id):
    return db.execute(
        "SELECT e.*, d.name dept, g.title desig, s.name shift_name,"
        " m.first_name mfn, m.last_name mln"
        " FROM employees e LEFT JOIN departments d ON d.id=e.department_id"
        " LEFT JOIN designations g ON g.id=e.designation_id"
        " LEFT JOIN shifts s ON s.id=e.shift_id"
        " LEFT JOIN employees m ON m.id=e.manager_id WHERE e.id=?",
        (emp_id,)).fetchone()


def today_att(db, emp_id):
    return db.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?",
                      (emp_id, date.today().isoformat())).fetchone()


def open_break(db, att):
    if not att:
        return None
    return db.execute("SELECT * FROM breaks WHERE attendance_id=? AND end_ts IS NULL",
                      (att["id"],)).fetchone()


def team_ids(db, user):
    """ids this user can review: direct reports (manager) or everyone (hr)."""
    if user["role"] == "hr":
        return [r["id"] for r in db.execute(
            "SELECT id FROM employees WHERE id!=?", (user["id"],))]
    return [r["id"] for r in db.execute(
        "SELECT id FROM employees WHERE manager_id=?", (user["id"],))]


def scope_clause(ids):
    if not ids:
        return "(-1)", []
    return "(%s)" % ",".join("?" * len(ids)), list(ids)


def att_summary(db, emp_id, start, end):
    r = db.execute(
        "SELECT SUM(CASE WHEN status IN('present','wfh') THEN 1 ELSE 0 END) p,"
        " SUM(CASE WHEN status='wfh' THEN 1 ELSE 0 END) wfh,"
        " SUM(CASE WHEN status='leave' THEN 1 ELSE 0 END) lv,"
        " SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) ab,"
        " SUM(CASE WHEN late_minutes>0 THEN 1 ELSE 0 END) late,"
        " SUM(work_minutes) wm, SUM(overtime_minutes) ot"
        " FROM attendance WHERE employee_id=? AND date BETWEEN ? AND ?",
        (emp_id, start.isoformat(), end.isoformat())).fetchone()
    return {k: r[k] or 0 for k in ("p", "wfh", "lv", "ab", "late", "wm", "ot")}


def clock_widget(db, user, session, att, br):
    shift = D.get_shift(db, user)
    inner = ['<div class="sm mut">Shift: <b>%s</b> · %s–%s · offs %s</div>'
             % (esc(shift["name"]), shift["start_time"], shift["end_time"],
                esc(shift["weekly_offs"]))]
    csrf = hidden_csrf(session)
    if att and att["status"] == "leave":
        inner.append('<p class="mt">You are on approved <b>%s</b> today. Enjoy!</p>'
                     % esc(att["notes"] or "leave"))
    elif not att or not att["clock_in"]:
        off = D.is_weekly_off(shift, date.today())
        hol = D.holidays_map(db).get(date.today().isoformat())
        note = ""
        if hol:
            note = ('<div class="sm" style="color:var(--warn)">Today is a holiday '
                    '(%s). Clocking in will count as extra work for comp-off.</div>'
                    % esc(hol))
        elif off:
            note = ('<div class="sm" style="color:var(--warn)">Today is your weekly '
                    'off. Clocking in will count as extra work for comp-off.</div>')
        inner.append(
            '<div class="bigclock" data-clock style="margin:8px 0 2px"></div>%s'
            '<form method="post" action="/clock-in" class="mt" '
            'style="display:flex;gap:8px;flex-wrap:wrap">%s'
            '<button class="btn" name="mode" value="office">Clock in · Office</button>'
            '<button class="btn ghost" name="mode" value="wfh">Clock in · WFH</button>'
            '</form>' % (note, csrf))
    elif not att["clock_out"]:
        since = att["clock_in"]
        mode = badge("WFH", "sky") if att["mode"] == "wfh" else badge("Office", "ok")
        if br:
            inner.append(
                '<p class="mt">On a break since <b>%s</b> (clocked in %s %s)</p>'
                '<form method="post" action="/break-end" class="mt">%s'
                '<button class="btn warn">End break</button></form>'
                % (esc(br["start_ts"][11:]), esc(since[11:]), mode, csrf))
        else:
            inner.append(
                '<div class="sm mut mt">Clocked in at <b>%s</b> %s%s</div>'
                '<div class="bigclock" data-since="%s">0h 00m</div>'
                '<div class="sm mut">on the clock</div>'
                '<div class="mt" style="display:flex;gap:8px;flex-wrap:wrap">'
                '<form method="post" action="/clock-out">%s'
                '<button class="btn bad">Clock out</button></form>'
                '<form method="post" action="/break-start">%s'
                '<button class="btn ghost">Take a break</button></form></div>'
                % (esc(since[11:]), mode,
                   " · " + badge("Late %d min" % att["late_minutes"], "warn")
                   if att["late_minutes"] else "",
                   esc(since), csrf, csrf))
    else:
        inner.append(
            '<div class="kv mt"><dt>Clocked in</dt><dd>%s</dd>'
            '<dt>Clocked out</dt><dd>%s</dd><dt>Worked</dt><dd>%s</dd>'
            '<dt>Breaks</dt><dd>%s</dd><dt>Overtime</dt><dd>%s</dd></div>'
            '<p class="sm mut mt">Day complete. See you tomorrow \u2600</p>'
            % (esc(att["clock_in"][11:]), esc(att["clock_out"][11:]),
               D.fmt_mins(att["work_minutes"]), D.fmt_mins(att["break_minutes"]),
               D.fmt_mins(att["overtime_minutes"])))
    return card("Time clock · %s" % date.today().strftime("%A"), "".join(inner))


def att_row_cells(a, with_name=None):
    cells = []
    if with_name is not None:
        cells.append(with_name)
    d = datetime.strptime(a["date"], "%Y-%m-%d").date()
    cells += [
        '<b>%s</b> <span class="mut xs">%s</span>' % (a["date"], d.strftime("%a")),
        sbadge(a["status"]) + (" " + badge("QR", "mut") if "QR" in (a["notes"] or "") else ""),
        esc(a["clock_in"][11:16]) if a["clock_in"] else "—",
        (esc(a["clock_out"][11:16]) if a["clock_out"]
         else (badge("Missed", "bad") if a["missed_clockout"] else
               ('<span class="b-ok badge">on clock</span>'
                if a["clock_in"] and a["date"] == date.today().isoformat() else "—"))),
        '<span class="num">%s</span>' % D.fmt_mins(a["work_minutes"])
        if a["work_minutes"] else "—",
        '<span class="num">%s</span>' % D.fmt_mins(a["break_minutes"])
        if a["break_minutes"] else "—",
        badge("+" + D.fmt_mins(a["overtime_minutes"]), "ok")
        if a["overtime_minutes"] else "—",
        badge("%d min" % a["late_minutes"], "warn") if a["late_minutes"] else "—",
    ]
    return cells


ATT_HEADERS = ["Date", "Status", "In", "Out", "Worked", "Breaks", "OT", "Late"]


# ----------------------------------------------------------------- dashboard

def dashboard(db, user, session, query):
    t = date.today()
    ms, me = month_bounds(t.year, t.month)
    att = today_att(db, user["id"])
    br = open_break(db, att)
    s = att_summary(db, user["id"], ms, me)
    wd = len(D.working_days(db, D.get_shift(db, user), ms, min(me, t)))

    bal = db.execute(
        "SELECT lt.name, lb.allocated, lb.used FROM leave_balances lb"
        " JOIN leave_types lt ON lt.id=lb.leave_type_id"
        " WHERE lb.employee_id=? AND lb.year=? ORDER BY lt.id",
        (user["id"], t.year)).fetchall()
    bal_left = sum(b["allocated"] - b["used"] for b in bal)

    stats = (
        stat("Days present · %s" % t.strftime("%b"), "%d / %d" % (s["p"], max(wd, s["p"])),
             "%d WFH · %d absent" % (s["wfh"], s["ab"]), "\u2713", "#d1fae5", "#059669")
        + stat("Hours worked", D.fmt_mins(s["wm"]),
               "overtime " + D.fmt_mins(s["ot"]), "\u23f1", "#e0e7ff", "#4f46e5")
        + stat("Late arrivals", s["late"], "grace %d min" %
               D.get_shift(db, user)["grace_minutes"], "\u23f0", "#fef3c7", "#d97706")
        + stat("Leave balance", "%g days" % bal_left,
               " · ".join("%s %g" % (b["name"].split()[0], b["allocated"] - b["used"])
                          for b in bal if b["allocated"] - b["used"] > 0) or "none",
               "\u2708", "#e0f2fe", "#0284c7"))

    # last 14 working-day hours chart
    rows = db.execute(
        "SELECT date, work_minutes FROM attendance WHERE employee_id=?"
        " AND status IN('present','wfh') ORDER BY date DESC LIMIT 14",
        (user["id"],)).fetchall()
    pairs = [(r["date"][5:], round(r["work_minutes"] / 60, 1)) for r in reversed(rows)]
    chart = card("My hours · last %d working days" % len(pairs),
                 bar_chart(pairs, unit="h"))

    # upcoming holidays + my pending requests
    hol = db.execute("SELECT * FROM holidays WHERE date>=? ORDER BY date LIMIT 4",
                     (t.isoformat(),)).fetchall()
    hol_html = "".join(
        '<div style="display:flex;gap:10px;padding:7px 0;border-bottom:1px solid '
        '#eef2f7"><span class="chip">\u2605</span><div><b class="sm">%s</b>'
        '<div class="xs mut">%s</div></div></div>'
        % (esc(h["name"]),
           datetime.strptime(h["date"], "%Y-%m-%d").strftime("%a, %d %b %Y"))
        for h in hol) or '<div class="empty">No upcoming holidays.</div>'

    pend = db.execute(
        "SELECT lr.*, lt.name tname FROM leave_requests lr"
        " JOIN leave_types lt ON lt.id=lr.leave_type_id"
        " WHERE lr.employee_id=? AND lr.status='pending'", (user["id"],)).fetchall()
    pend_html = "".join(
        '<div class="sm" style="padding:6px 0;border-bottom:1px solid #eef2f7">'
        '%s <b>%s</b> · %s → %s</div>'
        % (sbadge(r["status"]), esc(r["tname"]), r["start_date"], r["end_date"])
        for r in pend) or '<div class="empty">No pending requests.</div>'

    left = clock_widget(db, user, session, att, br) + chart
    right = (card("Upcoming holidays", hol_html, '<a href="/calendar">calendar</a>')
             + card("My pending requests", pend_html, '<a href="/leave">leave</a>'))
    body = stats
    mgr_html = ""
    if user["role"] in ("manager", "hr"):
        mgr_html = _mgr_dash(db, user)
    return ("Dashboard", "/",
            '<div class="grid g4 mb">%s</div>%s'
            '<div class="grid g23"><div class="grid">%s</div><div class="grid">%s'
            '</div></div>' % (body, mgr_html, left, right))


def _mgr_dash(db, user):
    t = date.today().isoformat()
    ids = team_ids(db, user)
    cl, args = scope_clause(ids)
    rows = db.execute(
        "SELECT e.*, a.status ast, a.clock_in, a.late_minutes lm FROM employees e"
        " LEFT JOIN attendance a ON a.employee_id=e.id AND a.date=?"
        " WHERE e.id IN %s AND e.status='active' ORDER BY e.first_name" % cl,
        [t] + args).fetchall()
    present = sum(1 for r in rows if r["ast"] in ("present", "wfh"))
    on_leave = sum(1 for r in rows if r["ast"] == "leave")
    not_in = [r for r in rows if not r["ast"]]
    late = [r for r in rows if (r["lm"] or 0) > 0]
    scope = "Organization" if user["role"] == "hr" else "My team"

    chips = "".join(
        '<span class="chip" title="%s">%s %s</span>'
        % (esc("not clocked in yet"), avatar(r, 22), esc(r["first_name"]))
        for r in not_in[:8]) or '<span class="sm mut">everyone is in \u2713</span>'
    late_html = "".join(
        '<span class="chip">%s %s · %dm</span>' % (avatar(r, 22),
                                                   esc(r["first_name"]), r["lm"])
        for r in late[:8]) or '<span class="sm mut">no late arrivals today</span>'
    body = ('<div class="grid g3"><div><div class="v" style="font-size:24px;'
            'font-weight:800">%d<span class="mut">/%d</span></div>'
            '<div class="sm mut">clocked in now</div></div>'
            '<div><div style="font-size:24px;font-weight:800">%d</div>'
            '<div class="sm mut">on approved leave</div></div>'
            '<div><div style="font-size:24px;font-weight:800">%d</div>'
            '<div class="sm mut">late past grace</div></div></div>'
            '<div class="mt sm"><b>Not in yet:</b><br>%s</div>'
            '<div class="mt sm"><b>Late today:</b><br>%s</div>'
            % (present, len(rows), on_leave, len(late), chips, late_html))
    return '<div class="mb">%s</div>' % card(
        "%s · today" % scope, body, '<a href="/team">open team</a>')


# ----------------------------------------------------------------- attendance

def attendance(db, user, session, query):
    y, m = month_param(query)
    ms, me = month_bounds(y, m)
    att = today_att(db, user["id"])
    br = open_break(db, att)
    rows = db.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND date BETWEEN ? AND ?"
        " ORDER BY date DESC", (user["id"], ms.isoformat(), me.isoformat())).fetchall()
    s = att_summary(db, user["id"], ms, me)
    totals = ('<div class="grid g4 mb">%s%s%s%s</div>' % (
        stat("Present days", s["p"], "%d of them WFH" % s["wfh"], "\u2713",
             "#d1fae5", "#059669"),
        stat("Hours worked", D.fmt_mins(s["wm"]), "", "\u23f1", "#e0e7ff", "#4f46e5"),
        stat("Overtime", D.fmt_mins(s["ot"]), "", "\u2b06", "#e0f2fe", "#0284c7"),
        stat("Late arrivals", s["late"], "", "\u23f0", "#fef3c7", "#d97706")))
    tbl = table(ATT_HEADERS, [att_row_cells(a) for a in rows],
                "No attendance records this month.")
    head = page_head("My Attendance",
                     '<a class="btn ghost sm" href="/corrections">Request correction'
                     '</a><a class="btn ghost sm" href="/reports/export.csv?m='
                     '%04d-%02d&amp;who=me">Download CSV</a>' % (y, m))
    return ("My Attendance", "/attendance",
            head + '<div class="grid g32 mb"><div>%s</div><div>%s%s</div></div>%s'
            % (clock_widget(db, user, session, att, br), totals,
               month_nav("/attendance", y, m), card("Daily log", tbl)))


# ----------------------------------------------------------------- leave

def leave(db, user, session, query):
    year = date.today().year
    bal = db.execute(
        "SELECT lt.id, lt.name, lb.allocated, lb.used FROM leave_balances lb"
        " JOIN leave_types lt ON lt.id=lb.leave_type_id"
        " WHERE lb.employee_id=? AND lb.year=? ORDER BY lt.id",
        (user["id"], year)).fetchall()
    cards = "".join(
        '<div class="card stat"><div class="v">%g<span class="mut" '
        'style="font-size:15px">/%g</span></div><div class="s">%s left</div>'
        '<div class="bar mt"><i style="width:%d%%"></i></div></div>'
        % (b["allocated"] - b["used"], b["allocated"], esc(b["name"]),
           int(100 * (b["allocated"] - b["used"]) / b["allocated"])
           if b["allocated"] else 0)
        for b in bal)

    opts = "".join('<option value="%d">%s (%g left)</option>'
                   % (b["id"], esc(b["name"]), b["allocated"] - b["used"])
                   for b in bal)
    t = date.today().isoformat()
    apply_form = (
        '<form method="post" action="/leave/apply" class="frm">%s'
        '<div class="row"><div><label class="f">Leave type</label>'
        '<select name="type_id">%s</select></div>'
        '<div><label class="f">From</label><input type="date" name="start" '
        'value="%s" required></div>'
        '<div><label class="f">To</label><input type="date" name="end" value="%s" '
        'required></div></div>'
        '<div><label class="f">Reason</label><textarea name="reason" rows="2" '
        'placeholder="A short reason helps your approver" required></textarea></div>'
        '<div><button class="btn">Submit for approval</button> '
        '<span class="xs mut">Weekly offs and holidays inside the range are not '
        'deducted.</span></div></form>' % (hidden_csrf(session), opts, t, t))

    co_form = (
        '<form method="post" action="/compoff/apply" class="frm">%s'
        '<div class="row"><div><label class="f">Date you worked (off/holiday)'
        '</label><input type="date" name="work_date" required></div></div>'
        '<div><label class="f">Reason</label><input name="reason" '
        'placeholder="e.g. production release on Saturday" required></div>'
        '<div><button class="btn ghost">Request comp-off credit</button></div>'
        '</form>' % hidden_csrf(session))

    reqs = db.execute(
        "SELECT lr.*, lt.name tname, r.first_name rfn, r.last_name rln"
        " FROM leave_requests lr JOIN leave_types lt ON lt.id=lr.leave_type_id"
        " LEFT JOIN employees r ON r.id=lr.reviewer_id"
        " WHERE lr.employee_id=? ORDER BY lr.created_at DESC LIMIT 30",
        (user["id"],)).fetchall()
    rows = []
    for r in reqs:
        act = "—"
        if r["status"] == "pending":
            act = ('<form method="post" action="/leave/cancel">%s'
                   '<input type="hidden" name="id" value="%d">'
                   '<button class="btn ghost sm">Cancel</button></form>'
                   % (hidden_csrf(session), r["id"]))
        elif r["reviewer_id"]:
            act = '<span class="xs mut">by %s %s%s</span>' % (
                esc(r["rfn"] or ""), esc(r["rln"] or ""),
                " · “%s”" % esc(r["review_comment"]) if r["review_comment"] else "")
        rows.append([esc(r["tname"]), "%s → %s" % (r["start_date"], r["end_date"]),
                     "%g" % r["days"], esc(r["reason"][:48]), sbadge(r["status"]), act])

    cos = db.execute(
        "SELECT * FROM compoffs WHERE employee_id=? ORDER BY created_at DESC LIMIT 10",
        (user["id"],)).fetchall()
    co_rows = [[r["work_date"], esc(r["reason"][:60]), sbadge(r["status"])]
               for r in cos]

    return ("Leave", "/leave",
            page_head("Leave Management")
            + '<div class="grid g4 mb">%s</div>' % cards
            + '<div class="grid g2 mb">%s%s</div>' % (
                card("Apply for leave", apply_form),
                card("Comp-off credit", co_form
                     + ('<div class="mt">%s</div>' % table(
                         ["Worked on", "Reason", "Status"], co_rows,
                         "No comp-off requests yet.") if True else "")))
            + card("My requests", table(
                ["Type", "Dates", "Days", "Reason", "Status", ""], rows,
                "You have not applied for leave yet.")))


# ----------------------------------------------------------------- calendar

def calendar_page(db, user, session, query):
    y, m = month_param(query)
    hol = D.holidays_map(db)
    shift = D.get_shift(db, user)
    att = {r["date"]: r for r in db.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND date LIKE ?",
        (user["id"], "%04d-%02d-%%" % (y, m)))}

    def cell(d):
        key = d.isoformat()
        parts, cls = [], ""
        if key in hol:
            cls = "off"
            parts.append(badge(hol[key][:14], "info"))
        elif D.is_weekly_off(shift, d):
            cls = "off"
            parts.append('<span class="xs mut">weekly off</span>')
        a = att.get(key)
        if a:
            if a["status"] in ("present", "wfh"):
                parts.append('<div class="xs num">%s–%s</div>' % (
                    a["clock_in"][11:16] if a["clock_in"] else "?",
                    a["clock_out"][11:16] if a["clock_out"] else "…"))
                parts.append(sbadge(a["status"]))
            else:
                parts.append(sbadge(a["status"]))
        return cls, "".join(parts)

    legend = ('<div class="legend"><span><i style="background:#d1fae5"></i>Present'
              '</span><span><i style="background:#e0f2fe"></i>WFH</span>'
              '<span><i style="background:#e0e7ff"></i>Leave/Holiday</span>'
              '<span><i style="background:#fee2e2"></i>Absent</span></div>')
    return ("Calendar", "/calendar",
            page_head("My Calendar") + month_nav("/calendar", y, m)
            + card(date(y, m, 1).strftime("%B %Y"),
                   month_cal(y, m, cell) + legend))


# ----------------------------------------------------------------- corrections

def corrections(db, user, session, query):
    form = (
        '<form method="post" action="/corrections/apply" class="frm">%s'
        '<div class="row"><div><label class="f">Date</label>'
        '<input type="date" name="date" max="%s" required></div>'
        '<div><label class="f">Correct clock-in</label>'
        '<input type="time" name="in"></div>'
        '<div><label class="f">Correct clock-out</label>'
        '<input type="time" name="out"></div></div>'
        '<div><label class="f">Reason</label><textarea name="reason" rows="2" '
        'placeholder="e.g. forgot to clock out, left at 18:30" required>'
        '</textarea></div><div><button class="btn">Submit correction</button> '
        '<span class="xs mut">Goes to your manager/HR for approval; approved '
        'corrections rewrite the attendance record.</span></div></form>'
        % (hidden_csrf(session), date.today().isoformat()))

    reqs = db.execute(
        "SELECT c.*, r.first_name rfn, r.last_name rln FROM corrections c"
        " LEFT JOIN employees r ON r.id=c.reviewer_id"
        " WHERE c.employee_id=? ORDER BY c.created_at DESC LIMIT 30",
        (user["id"],)).fetchall()
    rows = [[r["date"],
             esc(r["requested_in"] or "—"), esc(r["requested_out"] or "—"),
             esc(r["reason"][:50]), sbadge(r["status"]),
             '<span class="xs mut">%s</span>' % esc(
                 ("%s %s" % (r["rfn"], r["rln"])) if r["rfn"] else "")]
            for r in reqs]

    missed = db.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND missed_clockout=1"
        " ORDER BY date DESC LIMIT 5", (user["id"],)).fetchall()
    warn = ""
    if missed:
        warn = ('<div class="flash err stay">\u26a0 You have %d day(s) with a missed '
                'clock-out: %s. Submit corrections below.</div>'
                % (len(missed), ", ".join(r["date"] for r in missed)))

    return ("Corrections", "/corrections",
            page_head("Attendance Corrections") + warn
            + '<div class="grid g2"><div>%s</div><div>%s</div></div>' % (
                card("Request a correction", form),
                card("My correction requests", table(
                    ["Date", "In", "Out", "Reason", "Status", "Reviewer"], rows,
                    "No correction requests yet."))))


# ----------------------------------------------------------------- directory

def directory(db, user, session, query):
    q = query.get("q", [""])[0].strip()
    dept = query.get("dept", [""])[0]
    sql = ("SELECT e.*, d.name dept, g.title desig, m.first_name mfn,"
           " m.last_name mln FROM employees e"
           " LEFT JOIN departments d ON d.id=e.department_id"
           " LEFT JOIN designations g ON g.id=e.designation_id"
           " LEFT JOIN employees m ON m.id=e.manager_id WHERE e.status!='exited'")
    args = []
    if q:
        sql += (" AND (e.first_name LIKE ? OR e.last_name LIKE ? OR e.email LIKE ?"
                " OR e.emp_code LIKE ?)")
        args += ["%" + q + "%"] * 4
    if dept:
        sql += " AND d.name=?"
        args.append(dept)
    emps = db.execute(sql + " ORDER BY e.first_name", args).fetchall()
    depts = db.execute("SELECT name FROM departments ORDER BY name").fetchall()
    filt = ('<form class="hd" method="get" action="/directory">'
            '<input name="q" value="%s" placeholder="Search name, email, code…" '
            'style="max-width:280px"><select name="dept" style="max-width:190px">'
            '<option value="">All departments</option>%s</select>'
            '<button class="btn sm">Filter</button></form>'
            % (esc(q), "".join('<option %s>%s</option>'
                               % ("selected" if d["name"] == dept else "",
                                  esc(d["name"])) for d in depts)))
    rows = [[
        '<a href="/employee/%d" style="display:flex;gap:10px;align-items:center">'
        '%s<span><b>%s</b><br><span class="xs mut">%s</span></span></a>'
        % (e["id"], avatar(e, 32), esc(D.emp_name(e)), esc(e["emp_code"])),
        esc(e["desig"] or "—"), esc(e["dept"] or "—"),
        esc(("%s %s" % (e["mfn"], e["mln"])) if e["mfn"] else "—"),
        '<a href="mailto:%s">%s</a>' % (esc(e["email"]), esc(e["email"])),
        sbadge(e["status"])]
        for e in emps]
    return ("Directory", "/directory",
            page_head("Employee Directory",
                      badge("%d people" % len(rows), "info")) + filt
            + card("", table(["Employee", "Designation", "Department", "Manager",
                              "Email", "Status"], rows, "No matches.")))


# ----------------------------------------------------------------- profile

def profile(db, user, session, query, emp_id):
    e = get_emp(db, emp_id)
    if not e:
        return ("Not found", "/directory", '<div class="empty">No such employee.</div>')
    year = date.today().year
    t = date.today()
    ms, _ = month_bounds(t.year, t.month)
    s = att_summary(db, e["id"], ms, t)
    bal = db.execute(
        "SELECT lt.name, lb.allocated, lb.used FROM leave_balances lb"
        " JOIN leave_types lt ON lt.id=lb.leave_type_id"
        " WHERE lb.employee_id=? AND lb.year=?", (e["id"], year)).fetchall()
    recent = db.execute(
        "SELECT * FROM attendance WHERE employee_id=? ORDER BY date DESC LIMIT 10",
        (e["id"],)).fetchall()
    info = ('<div style="display:flex;gap:16px;align-items:center;margin-bottom:14px">'
            '%s<div><div style="font-size:19px;font-weight:800">%s</div>'
            '<div class="sm mut">%s · %s</div>%s</div></div>'
            '<div class="kv"><dt>Employee code</dt><dd>%s</dd>'
            '<dt>Email</dt><dd>%s</dd><dt>Phone</dt><dd>%s</dd>'
            '<dt>Reports to</dt><dd>%s</dd><dt>Shift</dt><dd>%s</dd>'
            '<dt>Joined</dt><dd>%s</dd><dt>Role</dt><dd>%s</dd></div>'
            % (avatar(e, 56), esc(D.emp_name(e)), esc(e["desig"] or "—"),
               esc(e["dept"] or "—"), sbadge(e["status"]), esc(e["emp_code"]),
               esc(e["email"]), esc(e["phone"] or "—"),
               esc("%s %s" % (e["mfn"], e["mln"])) if e["mfn"] else "—",
               esc(e["shift_name"] or "—"), e["date_joined"], esc(e["role"].title())))
    bal_html = "".join(
        '<div style="margin-bottom:10px"><div class="sm" style="display:flex;'
        'justify-content:space-between"><span>%s</span><b>%g / %g</b></div>'
        '<div class="bar"><i style="width:%d%%"></i></div></div>'
        % (esc(b["name"]), b["allocated"] - b["used"], b["allocated"],
           int(100 * (b["allocated"] - b["used"]) / b["allocated"])
           if b["allocated"] else 0) for b in bal)
    stats = ('<div class="kv"><dt>Present this month</dt><dd>%d</dd>'
             '<dt>Hours</dt><dd>%s</dd><dt>Late arrivals</dt><dd>%d</dd>'
             '<dt>Overtime</dt><dd>%s</dd></div>'
             % (s["p"], D.fmt_mins(s["wm"]), s["late"], D.fmt_mins(s["ot"])))
    actions = ""
    if user["role"] == "hr":
        actions = ('<a class="btn ghost sm" href="/admin/employees?edit=%d">'
                   'Edit employee</a>' % e["id"])
    return ("Profile", "/directory",
            page_head(D.emp_name(e), actions)
            + '<div class="grid g32 mb"><div class="grid">%s%s</div>%s</div>%s' % (
                card("Leave balances · %d" % year, bal_html or
                     '<div class="empty">No balances.</div>'),
                card("This month", stats),
                card("Profile", info),
                card("Recent attendance",
                     table(ATT_HEADERS, [att_row_cells(a) for a in recent],
                           "No attendance yet."))))


# ----------------------------------------------------------------- team

def team(db, user, session, query):
    ids = team_ids(db, user)
    cl, args = scope_clause(ids)
    t = date.today()
    ms, _ = month_bounds(t.year, t.month)
    emps = db.execute(
        "SELECT e.*, d.name dept, g.title desig FROM employees e"
        " LEFT JOIN departments d ON d.id=e.department_id"
        " LEFT JOIN designations g ON g.id=e.designation_id"
        " WHERE e.id IN %s AND e.status='active' ORDER BY e.first_name" % cl,
        args).fetchall()
    rows = []
    for e in emps:
        a = today_att(db, e["id"])
        s = att_summary(db, e["id"], ms, t)
        today_s = sbadge(a["status"]) if a else badge("Not in", "mut")
        if a and a["clock_in"] and not a["clock_out"] and a["status"] != "leave":
            today_s += ' <span class="xs mut num">in %s</span>' % a["clock_in"][11:16]
        rows.append([
            '<a href="/employee/%d" style="display:flex;gap:10px;align-items:center">'
            '%s<span><b>%s</b><br><span class="xs mut">%s</span></span></a>'
            % (e["id"], avatar(e, 30), esc(D.emp_name(e)), esc(e["desig"] or "")),
            today_s, '<span class="num">%d</span>' % s["p"],
            '<span class="num">%s</span>' % D.fmt_mins(s["wm"]),
            '<span class="num">%d</span>' % s["late"],
            badge("+" + D.fmt_mins(s["ot"]), "ok") if s["ot"] else "—"])
    scope = "Everyone" if user["role"] == "hr" else "Direct reports"
    return ("My Team", "/team",
            page_head("My Team", badge(scope, "info"))
            + card("Month-to-date · %s" % t.strftime("%B %Y"),
                   table(["Employee", "Today", "Present", "Hours", "Late", "OT"],
                         rows, "No team members found.")))


# ----------------------------------------------------------------- approvals

def approvals(db, user, session, query):
    ids = team_ids(db, user)
    cl, args = scope_clause(ids)
    csrf = hidden_csrf(session)

    def review_form(action, rid):
        return ('<form method="post" action="%s" style="display:flex;gap:6px;'
                'flex-wrap:wrap;align-items:center">%s'
                '<input type="hidden" name="id" value="%d">'
                '<input name="comment" placeholder="comment (optional)" '
                'style="width:150px">'
                '<button class="btn ok sm" name="decision" value="approved">Approve'
                '</button><button class="btn bad sm" name="decision" '
                'value="rejected">Reject</button></form>' % (action, csrf, rid))

    lv = db.execute(
        "SELECT lr.*, lt.name tname, e.first_name, e.last_name, e.avatar_color"
        " FROM leave_requests lr JOIN leave_types lt ON lt.id=lr.leave_type_id"
        " JOIN employees e ON e.id=lr.employee_id"
        " WHERE lr.status='pending' AND lr.employee_id IN %s"
        " ORDER BY lr.created_at" % cl, args).fetchall()
    lv_rows = [['<span style="display:flex;gap:8px;align-items:center">%s %s</span>'
                % (avatar(r, 26), esc("%s %s" % (r["first_name"], r["last_name"]))),
                esc(r["tname"]), "%s → %s" % (r["start_date"], r["end_date"]),
                "%g" % r["days"], esc(r["reason"][:60]),
                review_form("/leave/review", r["id"])] for r in lv]

    co = db.execute(
        "SELECT c.*, e.first_name, e.last_name, e.avatar_color FROM compoffs c"
        " JOIN employees e ON e.id=c.employee_id"
        " WHERE c.status='pending' AND c.employee_id IN %s"
        " ORDER BY c.created_at" % cl, args).fetchall()
    co_rows = [['<span style="display:flex;gap:8px;align-items:center">%s %s</span>'
                % (avatar(r, 26), esc("%s %s" % (r["first_name"], r["last_name"]))),
                r["work_date"], esc(r["reason"][:70]),
                review_form("/compoff/review", r["id"])] for r in co]

    cr = db.execute(
        "SELECT c.*, e.first_name, e.last_name, e.avatar_color FROM corrections c"
        " JOIN employees e ON e.id=c.employee_id"
        " WHERE c.status='pending' AND c.employee_id IN %s"
        " ORDER BY c.created_at" % cl, args).fetchall()
    cr_rows = [['<span style="display:flex;gap:8px;align-items:center">%s %s</span>'
                % (avatar(r, 26), esc("%s %s" % (r["first_name"], r["last_name"]))),
                r["date"], esc(r["requested_in"] or "—"),
                esc(r["requested_out"] or "—"), esc(r["reason"][:50]),
                review_form("/corrections/review", r["id"])] for r in cr]

    return ("Approvals", "/approvals",
            page_head("Approvals",
                      badge("%d pending" % (len(lv) + len(co) + len(cr)),
                            "warn" if (lv or co or cr) else "ok"))
            + card("Leave requests", table(
                ["Employee", "Type", "Dates", "Days", "Reason", "Decision"],
                lv_rows, "No pending leave requests."))
            + '<div class="mt"></div>'
            + card("Comp-off credits", table(
                ["Employee", "Worked on", "Reason", "Decision"], co_rows,
                "No pending comp-off requests."))
            + '<div class="mt"></div>'
            + card("Attendance corrections", table(
                ["Employee", "Date", "In", "Out", "Reason", "Decision"], cr_rows,
                "No pending corrections.")))


# ----------------------------------------------------------------- reports

DONUT_COLORS = {"present": "#059669", "wfh": "#0284c7", "leave": "#6366f1",
                "absent": "#dc2626"}


def reports(db, user, session, query):
    y, m = month_param(query)
    ms, me = month_bounds(y, m)
    ids = team_ids(db, user)
    cl, args = scope_clause(ids)
    span = [ms.isoformat(), me.isoformat()]

    mix = db.execute(
        "SELECT status, COUNT(*) c FROM attendance WHERE employee_id IN %s"
        " AND date BETWEEN ? AND ? GROUP BY status" % cl, args + span).fetchall()
    seg = [(r["status"].title(), r["c"], DONUT_COLORS.get(r["status"], "#94a3b8"))
           for r in mix]

    daily = db.execute(
        "SELECT date, SUM(CASE WHEN status IN('present','wfh') THEN 1 ELSE 0 END) c"
        " FROM attendance WHERE employee_id IN %s AND date BETWEEN ? AND ?"
        " GROUP BY date ORDER BY date" % cl, args + span).fetchall()
    daily_pairs = [(r["date"][8:], r["c"]) for r in daily]

    dept = db.execute(
        "SELECT d.name, COUNT(DISTINCT e.id) hc,"
        " SUM(CASE WHEN a.status IN('present','wfh') THEN 1 ELSE 0 END) p,"
        " SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) ab,"
        " SUM(CASE WHEN a.late_minutes>0 THEN 1 ELSE 0 END) late,"
        " SUM(a.work_minutes) wm, SUM(a.overtime_minutes) ot"
        " FROM employees e JOIN departments d ON d.id=e.department_id"
        " LEFT JOIN attendance a ON a.employee_id=e.id AND a.date BETWEEN ? AND ?"
        " WHERE e.id IN %s AND e.status='active'"
        " GROUP BY d.name ORDER BY d.name" % cl, span + args).fetchall()
    dept_rows = []
    for r in dept:
        total_marked = (r["p"] or 0) + (r["ab"] or 0)
        absent_pct = (100.0 * (r["ab"] or 0) / total_marked) if total_marked else 0
        avg_h = ((r["wm"] or 0) / 60.0 / r["p"]) if r["p"] else 0
        dept_rows.append([
            "<b>%s</b>" % esc(r["name"]), r["hc"], r["p"] or 0, r["ab"] or 0,
            badge("%.1f%%" % absent_pct, "bad" if absent_pct > 5 else "ok"),
            "%.1f h" % avg_h, r["late"] or 0, D.fmt_mins(r["ot"] or 0)])
    dept_chart = bar_chart([(r["name"][:6], round((r["wm"] or 0) / 60, 1))
                            for r in dept], color="#0ea5e9", unit="h")

    late_top = db.execute(
        "SELECT e.first_name, e.last_name, e.avatar_color,"
        " SUM(CASE WHEN a.late_minutes>0 THEN 1 ELSE 0 END) days,"
        " SUM(a.late_minutes) mins FROM attendance a"
        " JOIN employees e ON e.id=a.employee_id"
        " WHERE a.employee_id IN %s AND a.date BETWEEN ? AND ?"
        " GROUP BY a.employee_id HAVING days>0 ORDER BY mins DESC LIMIT 6" % cl,
        args + span).fetchall()
    late_rows = [['<span style="display:flex;gap:8px;align-items:center">%s %s</span>'
                  % (avatar(r, 24), esc("%s %s" % (r["first_name"], r["last_name"]))),
                  r["days"], D.fmt_mins(r["mins"])] for r in late_top]

    mstr = "%04d-%02d" % (y, m)
    actions = ('<a class="btn ghost sm" href="/reports/export.csv?m=%s">Attendance '
               'CSV</a><a class="btn ghost sm" href="/reports/export.csv?m=%s&amp;'
               'kind=summary">Summary CSV</a>' % (mstr, mstr))
    return ("Reports", "/reports",
            page_head("Reports &amp; Analytics", actions)
            + month_nav("/reports", y, m)
            + '<div class="grid g2 mb">%s%s</div>' % (
                card("Attendance mix · %s" % date(y, m, 1).strftime("%B"),
                     donut(seg) if seg else '<div class="empty">No data.</div>'),
                card("Headcount present by day", bar_chart(daily_pairs, color="#6366f1")))
            + '<div class="grid g23 mb">%s%s</div>' % (
                card("Department-wise statistics", table(
                    ["Department", "Headcount", "Present-days", "Absent",
                     "Absenteeism", "Avg hrs/day", "Late", "Overtime"],
                    dept_rows, "No departments in scope.")),
                card("Most late arrivals", table(
                    ["Employee", "Days late", "Total late"], late_rows,
                    "No late arrivals. \U0001f389")))
            + card("Hours by department", dept_chart))


# ----------------------------------------------------------------- HR admin

def admin_employees(db, user, session, query):
    edit_id = query.get("edit", [""])[0]
    depts = db.execute("SELECT * FROM departments ORDER BY name").fetchall()
    desigs = db.execute("SELECT * FROM designations ORDER BY title").fetchall()
    shifts = db.execute("SELECT * FROM shifts ORDER BY id").fetchall()
    mgrs = db.execute("SELECT * FROM employees WHERE role IN('manager','hr')"
                      " AND status!='exited' ORDER BY first_name").fetchall()
    csrf = hidden_csrf(session)

    def opts(rows, key, label, sel=None):
        return "".join('<option value="%s"%s>%s</option>'
                       % (r[key], " selected" if sel == r[key] else "",
                          esc(r[label])) for r in rows)

    e = None
    if edit_id.isdigit():
        e = get_emp(db, int(edit_id))

    def v(field, default=""):
        return esc(e[field]) if e else default

    form = (
        '<form method="post" action="%s" class="frm">%s%s'
        '<div class="row">'
        '<div><label class="f">First name</label><input name="first_name" value="%s"'
        ' required></div>'
        '<div><label class="f">Last name</label><input name="last_name" value="%s"'
        ' required></div>'
        '<div><label class="f">Email</label><input type="email" name="email" '
        'value="%s" required></div>'
        '<div><label class="f">Phone</label><input name="phone" value="%s"></div>'
        '</div><div class="row">'
        '<div><label class="f">Department</label><select name="department_id">%s'
        '</select></div>'
        '<div><label class="f">Designation</label><select name="designation_id">%s'
        '</select></div>'
        '<div><label class="f">Reporting manager</label><select name="manager_id">'
        '<option value="">— none —</option>%s</select></div>'
        '</div><div class="row">'
        '<div><label class="f">Role</label><select name="role">%s</select></div>'
        '<div><label class="f">Shift</label><select name="shift_id">%s</select></div>'
        '<div><label class="f">Date joined</label><input type="date" '
        'name="date_joined" value="%s" required></div>'
        '<div><label class="f">Status</label><select name="status">%s</select></div>'
        '</div>%s'
        '<div><button class="btn">%s</button> <span class="xs mut">%s</span></div>'
        '</form>') % (
        "/admin/employees/update" if e else "/admin/employees/create", csrf,
        '<input type="hidden" name="id" value="%d">' % e["id"] if e else "",
        v("first_name"), v("last_name"), v("email"), v("phone"),
        opts(depts, "id", "name", e["department_id"] if e else None),
        opts(desigs, "id", "title", e["designation_id"] if e else None),
        opts(mgrs, "id", "first_name", e["manager_id"] if e else None),
        "".join('<option value="%s"%s>%s</option>'
                % (r, " selected" if e and e["role"] == r else "", r.title())
                for r in ("employee", "manager", "hr")),
        opts(shifts, "id", "name", e["shift_id"] if e else None),
        v("date_joined", date.today().isoformat()),
        "".join('<option value="%s"%s>%s</option>'
                % (s, " selected" if e and e["status"] == s else "", s.title())
                for s in ("onboarding", "active", "exited")),
        "" if e else ('<div class="xs mut">New employees get login password '
                      '<b>demo123</b>, a full leave quota for this year and an '
                      'onboarding checklist when status is Onboarding.</div>'),
        "Save changes" if e else "Add employee",
        'Editing %s — <a href="/admin/employees">cancel</a>' % esc(D.emp_name(e))
        if e else "")

    emps = db.execute(
        "SELECT e.*, d.name dept, g.title desig FROM employees e"
        " LEFT JOIN departments d ON d.id=e.department_id"
        " LEFT JOIN designations g ON g.id=e.designation_id"
        " ORDER BY e.status='exited', e.first_name").fetchall()
    rows = [[esc(x["emp_code"]),
             '<a href="/employee/%d" style="display:flex;gap:8px;align-items:center">'
             '%s %s</a>' % (x["id"], avatar(x, 26), esc(D.emp_name(x))),
             esc(x["dept"] or "—"), esc(x["desig"] or "—"),
             badge(x["role"].upper(), "info" if x["role"] != "employee" else "mut"),
             sbadge(x["status"]),
             '<a class="btn ghost sm" href="/admin/employees?edit=%d">Edit</a>'
             % x["id"]] for x in emps]

    return ("Employees", "/admin/employees",
            page_head("Employee Administration")
            + card("Edit employee" if e else "Add employee", form)
            + '<div class="mt"></div>'
            + card("All employees (%d)" % len(rows), table(
                ["Code", "Name", "Department", "Designation", "Role", "Status", ""],
                rows)))


def shifts_page(db, user, session, query):
    csrf = hidden_csrf(session)
    shifts = db.execute("SELECT * FROM shifts ORDER BY id").fetchall()
    emps = db.execute("SELECT * FROM employees WHERE status!='exited'"
                      " ORDER BY first_name").fetchall()
    day_boxes = " ".join(
        '<label style="font-weight:500;font-size:12.5px;display:inline-flex;'
        'gap:3px;align-items:center"><input type="checkbox" name="offs" value="%s"'
        ' style="width:auto"%s>%s</label>'
        % (d, " checked" if d in ("Sat", "Sun") else "", d) for d in D.WEEKDAY_KEYS)
    create = (
        '<form method="post" action="/shifts/create" class="frm">%s'
        '<div class="row"><div><label class="f">Shift name</label>'
        '<input name="name" placeholder="e.g. Night (10-7)" required></div>'
        '<div><label class="f">Start</label><input type="time" name="start" '
        'value="09:00" required></div>'
        '<div><label class="f">End</label><input type="time" name="end" '
        'value="18:00" required></div>'
        '<div><label class="f">Break (min)</label><input type="number" name="brk" '
        'value="60" min="0" max="240"></div>'
        '<div><label class="f">Grace (min)</label><input type="number" name="grace" '
        'value="10" min="0" max="120"></div></div>'
        '<div><label class="f">Weekly offs</label>%s</div>'
        '<div><button class="btn">Create shift</button></div></form>'
        % (csrf, day_boxes))

    rows = []
    for s in shifts:
        cnt = db.execute("SELECT COUNT(*) c FROM employees WHERE shift_id=?"
                         " AND status!='exited'", (s["id"],)).fetchone()["c"]
        rows.append([
            "<b>%s</b>" % esc(s["name"]),
            '<span class="num">%s–%s</span>' % (s["start_time"], s["end_time"]),
            "%d min" % s["break_minutes"], "%d min" % s["grace_minutes"],
            esc(s["weekly_offs"]), badge("%d people" % cnt, "info"),
            "%s" % D.fmt_mins(D.nominal_minutes(s))])

    assign = (
        '<form method="post" action="/shifts/assign" class="frm">%s'
        '<div class="row"><div><label class="f">Employee</label>'
        '<select name="employee_id">%s</select></div>'
        '<div><label class="f">Move to shift</label><select name="shift_id">%s'
        '</select></div></div>'
        '<div><button class="btn">Assign shift</button> <span class="xs mut">'
        'Takes effect immediately; past attendance is untouched.</span></div></form>'
        % (csrf,
           "".join('<option value="%d">%s (%s)</option>'
                   % (x["id"], esc(D.emp_name(x)),
                      next((s["name"] for s in shifts if s["id"] == x["shift_id"]),
                           "?")) for x in emps),
           "".join('<option value="%d">%s</option>' % (s["id"], esc(s["name"]))
                   for s in shifts)))

    return ("Shifts", "/shifts",
            page_head("Shift Management")
            + card("Shifts", table(
                ["Shift", "Hours", "Break", "Grace", "Weekly offs", "Assigned",
                 "Nominal work"], rows))
            + '<div class="grid g2 mt">%s%s</div>' % (
                card("Create a shift", create), card("Assign employees", assign)))


def holidays_page(db, user, session, query):
    csrf = hidden_csrf(session)
    hols = db.execute("SELECT * FROM holidays ORDER BY date").fetchall()
    rows = []
    for h in hols:
        d = datetime.strptime(h["date"], "%Y-%m-%d").date()
        past = d < date.today()
        rows.append([
            "<b>%s</b>" % esc(h["name"]), h["date"], d.strftime("%A"),
            badge("past", "mut") if past else badge("upcoming", "ok"),
            ('<form method="post" action="/holidays/delete">%s'
             '<input type="hidden" name="id" value="%d">'
             '<button class="btn ghost sm">Delete</button></form>'
             % (csrf, h["id"]))])
    form = ('<form method="post" action="/holidays/create" class="frm">%s'
            '<div class="row"><div><label class="f">Holiday name</label>'
            '<input name="name" placeholder="e.g. Founders Day" required></div>'
            '<div><label class="f">Date</label><input type="date" name="date" '
            'required></div></div><div><button class="btn">Add holiday</button>'
            '</div></form>' % csrf)
    return ("Holidays", "/holidays",
            page_head("Holiday Calendar")
            + '<div class="grid g23">%s%s</div>' % (
                card("Holidays", table(["Name", "Date", "Day", "", ""], rows)),
                card("Add a holiday", form)))


def onboarding(db, user, session, query):
    csrf = hidden_csrf(session)
    emps = db.execute(
        "SELECT e.*, d.name dept, g.title desig FROM employees e"
        " LEFT JOIN departments d ON d.id=e.department_id"
        " LEFT JOIN designations g ON g.id=e.designation_id"
        " WHERE e.status='onboarding' ORDER BY e.date_joined").fetchall()
    blocks = []
    for e in emps:
        tasks = db.execute("SELECT * FROM onboarding_tasks WHERE employee_id=?"
                           " ORDER BY id", (e["id"],)).fetchall()
        done = sum(1 for x in tasks if x["done"])
        items = "".join(
            '<form method="post" action="/onboarding/toggle" style="display:flex;'
            'gap:9px;align-items:center;padding:5px 0">%s'
            '<input type="hidden" name="task_id" value="%d">'
            '<button class="btn sm %s" style="min-width:30px">%s</button>'
            '<span class="sm" style="%s">%s</span></form>'
            % (csrf, x["id"], "ok" if x["done"] else "ghost",
               "\u2713" if x["done"] else "\u25cb",
               "text-decoration:line-through;color:var(--mut)" if x["done"] else "",
               esc(x["task"])) for x in tasks)
        add = ('<form method="post" action="/onboarding/add-task" class="mt" '
               'style="display:flex;gap:8px">%s'
               '<input type="hidden" name="employee_id" value="%d">'
               '<input name="task" placeholder="Add a task…" required>'
               '<button class="btn ghost sm">Add</button></form>' % (csrf, e["id"]))
        activate = ""
        if tasks and done == len(tasks):
            activate = ('<form method="post" action="/onboarding/activate" '
                        'class="mt">%s<input type="hidden" name="employee_id" '
                        'value="%d"><button class="btn ok">Mark active — '
                        'onboarding complete</button></form>' % (csrf, e["id"]))
        pct = int(100 * done / len(tasks)) if tasks else 0
        blocks.append(card(
            "%s — joins %s" % (D.emp_name(e), e["date_joined"]),
            '<div style="display:flex;gap:12px;align-items:center;margin-bottom:8px">'
            '%s<div><b>%s</b><div class="xs mut">%s · %s</div></div></div>'
            '<div class="bar mb"><i style="width:%d%%"></i></div>%s%s%s'
            % (avatar(e, 40), esc(D.emp_name(e)), esc(e["desig"] or "—"),
               esc(e["dept"] or "—"), pct, items, add, activate),
            "%d/%d tasks" % (done, len(tasks))))
    if not blocks:
        blocks = ['<div class="card"><div class="empty">No employees onboarding. '
                  'Add one with status “Onboarding” in '
                  '<a href="/admin/employees">Employees</a>.</div></div>']
    return ("Onboarding", "/onboarding",
            page_head("Employee Onboarding") + '<div class="grid g2">%s</div>'
            % "".join(blocks))


def kiosk(db, user, session, query, host):
    token = D.qr_token_today(db)
    url = "http://%s/qr?t=%s" % (host, quote(token))
    svg = QR.svg(url, scale=5)
    rotate = ('<form method="post" action="/kiosk/rotate">%s'
              '<button class="btn ghost sm">Rotate token</button></form>'
              % hidden_csrf(session))
    return ("QR Kiosk", "/kiosk",
            page_head("QR Check-in Kiosk", rotate)
            + '<div class="grid g2">%s%s</div>' % (
                card("Scan to clock in",
                     '<div class="qrwrap">%s</div>'
                     '<p class="sm mut" style="text-align:center">Employees scan '
                     'this code with their phone (logged in to OrbitHR) to clock '
                     'in at the office. Token rotates daily.</p>' % svg),
                card("How it works",
                     '<ol class="sm" style="padding-left:18px;line-height:2">'
                     '<li>Display this page on a tablet at reception.</li>'
                     '<li>The QR encodes <span class="num xs">%s</span></li>'
                     '<li>Scanning opens a confirmation page; one tap clocks the '
                     'employee in with mode <b>Office</b> and note '
                     '<b>QR kiosk</b>.</li>'
                     '<li>The token is valid only today; rotate it anytime if '
                     'leaked.</li></ol>' % esc(url))))


def qr_confirm(db, user, session, query):
    token = query.get("t", [""])[0]
    ok = token and token == D.qr_token_today(db)
    att = today_att(db, user["id"])
    if not ok:
        body = ('<div class="flash err stay">\u26a0 This QR code is expired or '
                'invalid. Ask HR to refresh the kiosk.</div>')
    elif att and att["clock_in"]:
        body = ('<div class="flash ok stay">\u2713 You are already clocked in today '
                'at %s.</div>' % esc(att["clock_in"][11:16]))
    else:
        body = ('<p>Scanning the reception kiosk code. Confirm to clock in as '
                '<b>%s</b> (Office).</p>'
                '<form method="post" action="/qr-checkin" class="mt">%s'
                '<input type="hidden" name="t" value="%s">'
                '<button class="btn">Confirm clock-in</button></form>'
                % (esc(D.emp_name(user)), hidden_csrf(session), esc(token)))
    return ("QR Check-in", "/attendance", page_head("QR Check-in") + card("", body))


def audit_page(db, user, session, query):
    rows = db.execute(
        "SELECT a.*, e.first_name, e.last_name FROM audit_logs a"
        " LEFT JOIN employees e ON e.id=a.actor_id"
        " ORDER BY a.id DESC LIMIT 200").fetchall()
    data = [['<span class="num xs">%s</span>' % esc(r["created_at"]),
             esc("%s %s" % (r["first_name"], r["last_name"])) if r["first_name"]
             else badge("system", "mut"),
             badge(r["action"], "info"),
             esc("%s %s" % (r["entity"], r["entity_id"])).strip(),
             '<span class="sm">%s</span>' % esc(r["details"][:110])]
            for r in rows]
    return ("Audit Log", "/audit",
            page_head("Audit Log", badge("last %d events" % len(data), "mut"))
            + card("", table(["When", "Actor", "Action", "Entity", "Details"],
                             data, "No audit events.")))


def notifications_page(db, user, session, query):
    rows = db.execute(
        "SELECT * FROM notifications WHERE employee_id=? ORDER BY id DESC LIMIT 50",
        (user["id"],)).fetchall()
    kinds = {"info": "info", "warn": "warn", "success": "ok", "action": "info"}
    items = "".join(
        '<div style="display:flex;gap:12px;padding:11px 4px;border-bottom:1px solid '
        '#eef2f7;%s"><div>%s</div><div style="flex:1"><b class="sm">%s</b>'
        '<div class="sm mut">%s</div><div class="xs mut">%s%s</div></div></div>'
        % ("" if r["is_read"] else "background:#f5f7ff;border-radius:8px",
           badge("\u2709", kinds.get(r["kind"], "mut")), esc(r["title"]),
           esc(r["body"]), esc(r["created_at"]),
           ' · <a href="%s">open</a>' % esc(r["link"]) if r["link"] else "")
        for r in rows) or '<div class="empty">No notifications yet.</div>'
    mark = ('<form method="post" action="/notifications/read">%s'
            '<button class="btn ghost sm">Mark all read</button></form>'
            % hidden_csrf(session))
    return ("Notifications", "/notifications",
            page_head("Notifications", mark) + card("", items))
