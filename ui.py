"""OrbitHR - presentation layer: layout, CSS, reusable components, SVG charts.

No external CDNs or build tools: the host has no Node toolchain, so the
"Tailwind-grade" look is a hand-written utility stylesheet served inline.
"""
import html as _html
from datetime import date

import db as D


def esc(s):
    return _html.escape(str(s if s is not None else ""))


CSS = """
:root{--bg:#f4f6fb;--panel:#ffffff;--ink:#0f172a;--mut:#64748b;--line:#e2e8f0;
 --brand:#4f46e5;--brand2:#6366f1;--ok:#059669;--warn:#d97706;--bad:#dc2626;
 --sky:#0284c7;--side:#111735;--side2:#1b2347;--r:14px}
*{box-sizing:border-box;margin:0;padding:0}
body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
 background:var(--bg);color:var(--ink)}
a{color:var(--brand);text-decoration:none}a:hover{text-decoration:underline}
.app{display:flex;min-height:100vh}
/* ---------- sidebar ---------- */
.side{width:232px;background:linear-gradient(180deg,var(--side),var(--side2));
 color:#cbd5e1;flex-shrink:0;display:flex;flex-direction:column;position:sticky;
 top:0;height:100vh;overflow-y:auto}
.logo{display:flex;gap:10px;align-items:center;padding:20px 18px 14px;color:#fff}
.logo .mark{width:34px;height:34px;border-radius:10px;background:
 linear-gradient(135deg,#6366f1,#22d3ee);display:grid;place-items:center;
 font-weight:800;font-size:16px;color:#fff}
.logo b{font-size:17px;letter-spacing:.2px}
.logo small{display:block;font-size:10.5px;color:#8b95b5;font-weight:500}
.nav{padding:6px 10px 20px}
.nav .sec{font-size:10.5px;text-transform:uppercase;letter-spacing:.12em;
 color:#7c87a8;margin:14px 10px 4px}
.nav a{display:flex;align-items:center;gap:10px;padding:8px 12px;margin:2px 0;
 border-radius:9px;color:#c3cbe0;font-weight:500;font-size:13.5px}
.nav a:hover{background:rgba(255,255,255,.07);text-decoration:none;color:#fff}
.nav a.on{background:var(--brand);color:#fff;box-shadow:0 6px 16px -6px rgba(79,70,229,.7)}
.nav a .ic{width:18px;text-align:center;opacity:.9}
.nav a .pill{margin-left:auto;background:#ef4444;color:#fff;border-radius:99px;
 font-size:10.5px;padding:1px 7px;font-weight:700}
/* ---------- main ---------- */
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.top{background:var(--panel);border-bottom:1px solid var(--line);padding:12px 26px;
 display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:20}
.top h1{font-size:18px;font-weight:700}
.top .sp{flex:1}
.top .clockbox{font-variant-numeric:tabular-nums;color:var(--mut);font-size:13px;
 text-align:right;line-height:1.3}
.top .clockbox b{color:var(--ink);font-size:15px}
.bell{position:relative;font-size:19px;color:var(--mut);padding:4px 6px;border-radius:8px}
.bell:hover{background:var(--bg);text-decoration:none}
.bell .dot{position:absolute;top:0;right:-2px;background:#ef4444;color:#fff;
 font-size:10px;border-radius:99px;padding:0 5px;font-weight:700}
.me{display:flex;align-items:center;gap:10px}
.me .who{text-align:right;line-height:1.25}
.me .who b{font-size:13.5px;display:block}
.me .who span{font-size:11.5px;color:var(--mut)}
.content{padding:24px 26px 56px;max-width:1240px;width:100%;margin:0 auto}
/* ---------- components ---------- */
.av{border-radius:50%;display:inline-grid;place-items:center;color:#fff;
 font-weight:700;flex-shrink:0}
.grid{display:grid;gap:16px}
.g2{grid-template-columns:repeat(2,1fr)}.g3{grid-template-columns:repeat(3,1fr)}
.g4{grid-template-columns:repeat(4,1fr)}
.g23{grid-template-columns:2fr 1fr}.g32{grid-template-columns:1fr 2fr}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
 padding:18px 20px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.card h3{font-size:13px;text-transform:uppercase;letter-spacing:.08em;
 color:var(--mut);margin-bottom:12px;font-weight:700;display:flex;align-items:center}
.card h3 .rt{margin-left:auto;text-transform:none;letter-spacing:0;font-size:12.5px;
 font-weight:600}
.stat .v{font-size:26px;font-weight:800;letter-spacing:-.5px}
.stat .s{font-size:12.5px;color:var(--mut);margin-top:2px}
.stat .ico{float:right;font-size:22px;width:42px;height:42px;border-radius:11px;
 display:grid;place-items:center}
table.t{width:100%;border-collapse:collapse;font-size:13.5px}
.t th{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.08em;
 text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
.t td{padding:9px 10px;border-bottom:1px solid #eef2f7;vertical-align:middle}
.t tr:last-child td{border-bottom:0}
.t tr:hover td{background:#f8fafc}
.num{font-variant-numeric:tabular-nums}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:2px 9px;
 border-radius:99px;white-space:nowrap}
.b-ok{background:#d1fae5;color:#065f46}.b-bad{background:#fee2e2;color:#991b1b}
.b-warn{background:#fef3c7;color:#92400e}.b-info{background:#e0e7ff;color:#3730a3}
.b-sky{background:#e0f2fe;color:#075985}.b-mut{background:#f1f5f9;color:#475569}
.btn{display:inline-block;border:0;border-radius:9px;padding:8px 16px;font-size:13.5px;
 font-weight:600;cursor:pointer;background:var(--brand);color:#fff;font-family:inherit}
.btn:hover{background:#4338ca;text-decoration:none}
.btn.sm{padding:5px 11px;font-size:12.5px;border-radius:8px}
.btn.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
.btn.ghost:hover{background:var(--bg)}
.btn.ok{background:var(--ok)}.btn.ok:hover{background:#047857}
.btn.bad{background:var(--bad)}.btn.bad:hover{background:#b91c1c}
.btn.warn{background:var(--warn)}.btn.warn:hover{background:#b45309}
.btn:disabled{opacity:.5;cursor:not-allowed}
input,select,textarea{font-family:inherit;font-size:13.5px;border:1px solid #cbd5e1;
 border-radius:9px;padding:8px 11px;background:#fff;color:var(--ink);width:100%}
input:focus,select:focus,textarea:focus{outline:2px solid #c7d2fe;border-color:var(--brand2)}
label.f{display:block;font-size:12px;font-weight:600;color:var(--mut);margin-bottom:4px}
.frm{display:grid;gap:12px}
.frm .row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.flash{border-radius:11px;padding:11px 16px;margin-bottom:18px;font-size:13.5px;
 font-weight:600;display:flex;gap:10px;align-items:center}
.flash.ok{background:#d1fae5;color:#065f46;border:1px solid #a7f3d0}
.flash.err{background:#fee2e2;color:#991b1b;border:1px solid #fecaca}
.mut{color:var(--mut)}.sm{font-size:12.5px}.xs{font-size:11.5px}
.mb{margin-bottom:16px}.mt{margin-top:16px}
.hd{display:flex;align-items:center;gap:12px;margin-bottom:18px;flex-wrap:wrap}
.hd h2{font-size:21px;font-weight:800;letter-spacing:-.3px}
.hd .sp{flex:1}
.tabs{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}
.tabs a{padding:6px 14px;border-radius:99px;font-size:13px;font-weight:600;
 color:var(--mut);border:1px solid var(--line);background:#fff}
.tabs a.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.tabs a:hover{text-decoration:none;border-color:#94a3b8}
details.dd{position:relative}
details.dd summary{list-style:none;cursor:pointer}
details.dd summary::-webkit-details-marker{display:none}
details.dd .pane{position:absolute;right:0;top:calc(100% + 6px);background:#fff;
 border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 32px -8px
 rgba(15,23,42,.25);padding:14px;z-index:40;min-width:270px}
.cal{width:100%;border-collapse:collapse;table-layout:fixed}
.cal th{font-size:10.5px;color:var(--mut);text-transform:uppercase;padding:6px 4px;
 letter-spacing:.08em}
.cal td{border:1px solid #eef2f7;height:72px;vertical-align:top;padding:5px 6px;
 font-size:11.5px}
.cal td .d{font-weight:700;font-size:12px;margin-bottom:3px;color:#334155}
.cal td.off{background:#f8fafc}.cal td.today{outline:2px solid var(--brand2);outline-offset:-2px}
.cal td.pad{background:transparent;border:0}
.bigclock{font-size:34px;font-weight:800;font-variant-numeric:tabular-nums;
 letter-spacing:-1px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;font-size:13.5px}
.kv dt{color:var(--mut)}.kv dd{font-weight:600;text-align:right}
.bar{height:8px;border-radius:99px;background:#eef2f7;overflow:hidden}
.bar i{display:block;height:100%;border-radius:99px;background:var(--brand)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-top:8px}
.legend i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:5px;
 vertical-align:-1px}
.empty{color:var(--mut);font-size:13.5px;padding:18px 4px;text-align:center}
.qrwrap{display:grid;place-items:center;padding:12px}
.chip{display:inline-flex;align-items:center;gap:7px;background:#f1f5f9;
 border-radius:99px;padding:4px 12px 4px 5px;font-size:12.5px;font-weight:600}
.loginbg{min-height:100vh;display:grid;place-items:center;
 background:radial-gradient(900px 500px at 20% 0%,#312e81 0%,#111735 55%,#0b1023 100%)}
.loginbox{width:min(880px,94vw);display:grid;grid-template-columns:1fr 1fr;
 border-radius:20px;overflow:hidden;box-shadow:0 30px 80px -20px rgba(0,0,0,.6)}
.loginbox .l{background:#141b3d;color:#cbd5e1;padding:42px 38px}
.loginbox .r{background:#fff;padding:42px 38px}
.demo a{display:flex;justify-content:space-between;gap:8px;padding:9px 12px;
 border:1px solid var(--line);border-radius:10px;margin-top:8px;font-size:13px;
 color:var(--ink)}
.demo a:hover{background:var(--bg);text-decoration:none}
@media(max-width:1020px){.g4{grid-template-columns:repeat(2,1fr)}
 .g3{grid-template-columns:repeat(2,1fr)}.g23,.g32{grid-template-columns:1fr}}
@media(max-width:760px){.side{display:none}.g2,.g3,.g4{grid-template-columns:1fr}
 .content{padding:16px 14px 44px}.loginbox{grid-template-columns:1fr}
 .top{padding:10px 14px}.top .clockbox{display:none}}
"""

JS = """
function tick(){var els=document.querySelectorAll('[data-clock]');
 var n=new Date();var s=n.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
 els.forEach(function(e){e.textContent=s});
 var t=document.querySelectorAll('[data-since]');
 t.forEach(function(e){var st=new Date(e.dataset.since.replace(' ','T'));
  var m=Math.max(0,Math.floor((n-st)/60000));
  e.textContent=Math.floor(m/60)+'h '+String(m%60).padStart(2,'0')+'m';});}
setInterval(tick,1000);tick();
setTimeout(function(){var f=document.querySelector('.flash');
 if(f&&!f.classList.contains('stay'))f.style.display='none';},6000);
function fill(e,p){document.querySelector('[name=email]').value=e;
 document.querySelector('[name=password]').value=p;return false;}
"""

NAV = [
    ("core", "Workspace", None),
    ("/", "Dashboard", "\u25a6"),
    ("/attendance", "My Attendance", "\u23f1"),
    ("/leave", "Leave", "\u2708"),
    ("/calendar", "Calendar", "\u25a1"),
    ("/corrections", "Corrections", "\u270e"),
    ("/directory", "Directory", "\u2637"),
    ("mgr", "Management", ("manager", "hr")),
    ("/team", "My Team", "\u2630"),
    ("/approvals", "Approvals", "\u2714"),
    ("/reports", "Reports", "\u2241"),
    ("hr", "HR Admin", ("hr",)),
    ("/admin/employees", "Employees", "\u2699"),
    ("/shifts", "Shifts", "\u21bb"),
    ("/holidays", "Holidays", "\u2605"),
    ("/onboarding", "Onboarding", "\u2b06"),
    ("/kiosk", "QR Kiosk", "\u25a3"),
    ("/audit", "Audit Log", "\u2691"),
]


def avatar(e, size=34):
    initials = (e["first_name"][:1] + e["last_name"][:1]).upper()
    return ('<span class="av" style="width:%dpx;height:%dpx;background:%s;'
            'font-size:%dpx">%s</span>' %
            (size, size, e["avatar_color"], int(size * .38), esc(initials)))


def badge(text, kind="mut"):
    return '<span class="badge b-%s">%s</span>' % (kind, esc(text))


STATUS_BADGE = {"present": ("Present", "ok"), "wfh": ("WFH", "sky"),
                "leave": ("Leave", "info"), "absent": ("Absent", "bad"),
                "pending": ("Pending", "warn"), "approved": ("Approved", "ok"),
                "rejected": ("Rejected", "bad"), "cancelled": ("Cancelled", "mut"),
                "active": ("Active", "ok"), "onboarding": ("Onboarding", "warn"),
                "exited": ("Exited", "mut")}


def sbadge(status):
    t, k = STATUS_BADGE.get(status, (status.title(), "mut"))
    return badge(t, k)


def card(title, body, right=""):
    rt = '<span class="rt">%s</span>' % right if right else ""
    return '<div class="card"><h3>%s%s</h3>%s</div>' % (esc(title), rt, body)


def stat(label, value, sub="", icon="", tone="#eef2ff", ink="#4f46e5"):
    ic = ('<span class="ico" style="background:%s;color:%s">%s</span>'
          % (tone, ink, icon)) if icon else ""
    return ('<div class="card stat">%s<div class="v">%s</div>'
            '<div class="s">%s</div><div class="s mut">%s</div></div>'
            % (ic, esc(value), esc(label), esc(sub)))


def table(headers, rows, empty="Nothing here yet."):
    if not rows:
        return '<div class="empty">%s</div>' % esc(empty)
    h = "".join("<th>%s</th>" % esc(x) for x in headers)
    b = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)
    return '<table class="t"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (h, b)


def bar_chart(pairs, height=150, color="#6366f1", unit=""):
    """pairs: [(label, value)] -> responsive SVG column chart."""
    if not pairs:
        return '<div class="empty">No data for this range.</div>'
    n = len(pairs)
    mx = max((v for _, v in pairs), default=0) or 1
    w = 100.0 / n
    bars = []
    for i, (lab, v) in enumerate(pairs):
        bh = (v / mx) * (height - 38)
        x = i * w + w * 0.18
        bars.append(
            '<rect x="%.2f%%" y="%.1f" width="%.2f%%" height="%.1f" rx="3" fill="%s">'
            '<title>%s: %s%s</title></rect>'
            '<text x="%.2f%%" y="%d" font-size="9" fill="#64748b" '
            'text-anchor="middle">%s</text>'
            % (x, height - 24 - bh, w * 0.64, max(bh, 1.5), color,
               esc(lab), round(v, 1), unit,
               i * w + w / 2, height - 8, esc(str(lab)[:7])))
    return ('<svg width="100%%" height="%d" role="img" '
            'style="display:block">%s</svg>' % (height, "".join(bars)))


def donut(segments, size=140):
    """segments: [(label, value, color)] -> donut + legend."""
    total = sum(v for _, v, _ in segments) or 1
    import math
    r, cx, cy, sw = 52, size / 2, size / 2, 22
    circ = 2 * math.pi * r
    off, arcs = 0.0, []
    for lab, v, col in segments:
        frac = v / total
        arcs.append('<circle cx="%s" cy="%s" r="%s" fill="none" stroke="%s" '
                    'stroke-width="%s" stroke-dasharray="%.2f %.2f" '
                    'stroke-dashoffset="%.2f" transform="rotate(-90 %s %s)">'
                    '<title>%s: %s</title></circle>'
                    % (cx, cy, r, col, sw, frac * circ, circ, -off * circ,
                       cx, cy, esc(lab), v))
        off += frac
    legend = "".join('<span><i style="background:%s"></i>%s · %s</span>'
                     % (c, esc(l), round(v, 1)) for l, v, c in segments)
    return ('<div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">'
            '<svg width="%d" height="%d">%s<text x="%s" y="%s" text-anchor="middle" '
            'font-size="15" font-weight="800" fill="#0f172a">%s</text></svg>'
            '<div class="legend" style="flex-direction:column;gap:6px">%s</div></div>'
            % (size, size, "".join(arcs), cx, cy + 5, round(total, 1), legend))


def month_cal(year, month, cell_fn):
    """cell_fn(date) -> (extra_css_class, inner_html)."""
    import calendar as _c
    cal = _c.Calendar(firstweekday=0)
    head = "".join("<th>%s</th>" % d for d in D.WEEKDAY_KEYS)
    rows = []
    for week in cal.monthdatescalendar(year, month):
        tds = []
        for d in week:
            if d.month != month:
                tds.append('<td class="pad"></td>')
                continue
            cls, inner = cell_fn(d)
            if d == date.today():
                cls += " today"
            tds.append('<td class="%s"><div class="d">%d</div>%s</td>'
                       % (cls, d.day, inner))
        rows.append("<tr>%s</tr>" % "".join(tds))
    return ('<table class="cal"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
            % (head, "".join(rows)))


def flash_html(query):
    ok = query.get("ok", [""])[0]
    err = query.get("err", [""])[0]
    if ok:
        return '<div class="flash ok">\u2713 %s</div>' % esc(ok)
    if err:
        return '<div class="flash err">\u26a0 %s</div>' % esc(err)
    return ""


def hidden_csrf(user_session):
    return '<input type="hidden" name="csrf" value="%s">' % esc(user_session["csrf"])


def layout(user, session, title, active, content, unread=0, flash="", counts=None):
    counts = counts or {}
    nav = []
    for item in NAV:
        key, label, meta = item
        if key in ("core", "mgr", "hr"):
            if meta and user["role"] not in meta:
                continue
            nav.append('<div class="sec">%s</div>' % esc(label))
            continue
        href, icon = key, meta
        pill = ""
        if href == "/approvals" and counts.get("approvals"):
            pill = '<span class="pill">%d</span>' % counts["approvals"]
        on = " on" if active == href else ""
        nav.append('<a class="nav-a%s" href="%s"><span class="ic">%s</span>%s%s</a>'
                   % (on, href, icon, esc(label), pill))
    role_label = {"hr": "HR Administrator", "manager": "Manager",
                  "employee": "Employee"}[user["role"]]
    bell_dot = '<span class="dot">%d</span>' % unread if unread else ""
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · OrbitHR</title><style>%s</style></head><body>
<div class="app">
 <aside class="side">
  <div class="logo"><span class="mark">O</span>
   <div><b>OrbitHR</b><small>Attendance &amp; HR Suite</small></div></div>
  <nav class="nav">%s</nav>
 </aside>
 <div class="main">
  <header class="top">
   <h1>%s</h1><span class="sp"></span>
   <div class="clockbox"><b data-clock></b><br>%s</div>
   <a class="bell" href="/notifications" title="Notifications">\u2709%s</a>
   <div class="me"><div class="who"><b>%s</b><span>%s</span></div>
    <a href="/employee/%d" title="My profile">%s</a>
    <form method="post" action="/logout" style="margin-left:4px">%s
     <button class="btn ghost sm" type="submit">Log out</button></form></div>
  </header>
  <div class="content">%s%s</div>
 </div>
</div><script>%s</script></body></html>""" % (
        esc(title), CSS, "".join(nav).replace("nav-a", ""), esc(title),
        date.today().strftime("%a, %d %b %Y"), bell_dot,
        esc(D.emp_name(user)), esc(role_label), user["id"], avatar(user, 36),
        hidden_csrf(session), flash, content, JS)


def page_head(title, actions=""):
    return '<div class="hd"><h2>%s</h2><span class="sp"></span>%s</div>' % (
        esc(title), actions)
