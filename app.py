import os, sqlite3, threading, time
from collections import Counter
from datetime import date, timedelta
from functools import wraps
from flask import Flask, request, session, redirect, render_template, flash, abort
from markupsafe import Markup, escape
from werkzeug.security import generate_password_hash, check_password_hash
from core import q, x, contact
from modules import inventory, forecasting, crm, automation
import seed

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "doi-khoa-bi-mat-khi-trien-khai")
seed.seed()
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
IMG_DIR = os.path.join(app.root_path, "static", "img")
os.makedirs(IMG_DIR, exist_ok=True)
ALLOWED = ("jpg", "jpeg", "png", "webp")

NAV = {
    "customer": [("/", "Khám phá"), ("/match", "AI Concept Match"), ("/services", "Dịch vụ"), ("/my", "Của tôi")],
    "partner": [("/partner", "Tổng quan"), ("/partner/inventory", "Kho"), ("/partner/forecast", "Dự báo"), ("/partner/customers", "Khách hàng"), ("/partner/concepts", "Concept & ảnh")],
    "admin": [("/admin", "Tổng quan"), ("/admin/crm", "CRM"), ("/admin/inventory", "Kho"), ("/admin/forecast", "Dự báo"),
              ("/admin/automation", "Tự động hoá"), ("/admin/concepts", "Concept & ảnh"), ("/admin/users", "Người dùng")],
}
PAL = [("#1F5FA8", "#9CC3E6"), ("#0B7A6B", "#A8DCCF"), ("#4A3FA0", "#C3BDF0"), ("#B45309", "#F5D08A")]
STATUS = dict(pending="Chờ xác nhận", confirmed="Đã xác nhận", completed="Hoàn thành", cancelled="Đã huỷ")
STAGES = ["Mới", "Đã liên hệ", "Báo giá", "Thành công", "Mất"]
COMMISSION = 0.10

# ---------- tiện ích ----------
def me():
    return q("select * from users where id=?", (session["uid"],), True) if "uid" in session else None

@app.context_processor
def ctx():
    u = me()
    return dict(u=u, nav=NAV.get(u["role"], []) if u else [], contact=contact())

def need(role):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = me()
            if not u:
                return redirect("/login")
            if u["role"] != role:
                abort(403)
            return f(*a, **k)
        return w
    return deco

def page(title, stats=(), blocks=(), sub=""):
    return render_template("page.html", title=title, stats=stats, blocks=blocks, sub=sub)

def F(name, label, type="text", opts=None, val=""):
    return dict(name=name, label=label, type=type, opts=opts or [], val=val)

def vnd(n):
    return f"{int(n or 0):,}".replace(",", ".") + "đ"

def btn(url, label, cls="", **fields):
    h = "".join(f'<input type="hidden" name="{k}" value="{escape(v)}">' for k, v in fields.items())
    return Markup(f'<form method="post" action="{url}" class="inline">{h}<button class="{cls}">{label}</button></form>')

def tag(text, cls=""):
    return Markup(f'<span class="tag {cls}">{escape(text)}</span>')

def bars(hist, fc=(), big=False):
    vals = list(hist)[-12:] + list(fc)
    mx = max(vals + [1])
    n = len(vals) - len(fc)
    inner = "".join(f'<i class="{"f" if i >= n else ""}" style="height:{max(4, v / mx * 100):.0f}%" title="{v:.0f}"></i>' for i, v in enumerate(vals))
    return Markup(f'<span class="bars{" big" if big else ""}">{inner}</span>')

def mypartner():
    return q("select * from partners where user_id=?", (session["uid"],), True)

def services_rows():
    return q("select s.*, p.name pname, (select round(avg(rating),1) from reviews r where r.partner_id=s.partner_id) rating "
             "from services s join partners p on p.id=s.partner_id order by s.id")

def img_url(slug):
    for e in ALLOWED:
        if slug and os.path.exists(os.path.join(IMG_DIR, f"{slug}.{e}")):
            return f"/static/img/{slug}.{e}"
    return None

def save_img(slug, f):
    ext = f.filename.rsplit(".", 1)[-1].lower() if f and f.filename and "." in f.filename else ""
    if ext not in ALLOWED or not slug:
        return False
    for e in ALLOWED:
        old = os.path.join(IMG_DIR, f"{slug}.{e}")
        if os.path.exists(old):
            os.remove(old)
    f.save(os.path.join(IMG_DIR, f"{slug}.{ext}"))
    return True

def svc_card(s):
    c1, c2 = PAL[s["id"] % len(PAL)]
    rating = f"★{s['rating']}" if s["rating"] else "mới"
    return dict(title=s["title"], sub=f"{s['pname']} · {s['style']} · {rating} · {vnd(s['price'])}", c1=c1, c2=c2, img=img_url(s["img"]),
                actions=Markup(f'<a class="btn" href="/book/{s["id"]}">Đặt lịch</a>'))

# ---------- đăng nhập ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = q("select * from users where email=?", (request.form["email"].strip().lower(),), True)
        if u and check_password_hash(u["pw"], request.form["password"]):
            session["uid"] = u["id"]
            return redirect("/")
        flash("Email hoặc mật khẩu không đúng.")
    return page("Đăng nhập", blocks=[
        dict(form=dict(action="/login", submit="Đăng nhập", fields=[F("email", "Email", "email"), F("password", "Mật khẩu", "password")])),
        dict(note="Tài khoản demo: user@photohub.vn / user123 · partner@photohub.vn / partner123 · admin@photohub.vn / admin123"),
        dict(chips=[("Tạo tài khoản khách hàng", "/register")])])

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            uid = x("insert into users(email,name,pw,role,created) values(?,?,?,?,?)",
                    (request.form["email"].strip().lower(), request.form["name"], generate_password_hash(request.form["password"]), "customer", date.today().isoformat()))
            session["uid"] = uid
            return redirect("/")
        except sqlite3.IntegrityError:
            flash("Email này đã được đăng ký.")
    return page("Tạo tài khoản", blocks=[dict(form=dict(action="/register", submit="Tạo tài khoản",
                fields=[F("name", "Họ tên"), F("email", "Email", "email"), F("password", "Mật khẩu", "password")]))])

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ================= GIAO DIỆN KHÁCH HÀNG =================
@app.route("/")
def home():
    u = me()
    if not u:
        return redirect("/login")
    if u["role"] != "customer":
        return redirect("/partner" if u["role"] == "partner" else "/admin")
    style = request.args.get("style")
    posts = q("select po.*, p.name pname from posts po join partners p on p.id=po.partner_id" + (" where po.style=?" if style else "") + " order by po.id desc", (style,) if style else ())
    saved = {r["post_id"] for r in q("select post_id from saves where user_id=?", (u["id"],))}
    cards = [dict(title=r["caption"], sub=f"{r['pname']} · {r['style']}", c1=r["c1"], c2=r["c2"], img=img_url(r["img"]),
                  actions=btn(f"/like/{r['id']}", f"♥ {r['likes']}", "alt") + btn(f"/save/{r['id']}", "Bỏ lưu" if r["id"] in saved else "Lưu vào moodboard"))
             for r in posts]
    chips = [("Tất cả", "/")] + [(r["style"], f"/?style={r['style']}") for r in q("select distinct style from posts")]
    return page("Khám phá concept", blocks=[dict(chips=chips), dict(cards=cards)], sub="Xem bộ ảnh, lưu cảm hứng và đặt lịch ngay.")

@app.post("/like/<int:pid>")
@need("customer")
def like(pid):
    x("update posts set likes=likes+1 where id=?", (pid,))
    return redirect(request.referrer or "/")

@app.post("/save/<int:pid>")
@need("customer")
def save(pid):
    if q("select 1 from saves where user_id=? and post_id=?", (session["uid"], pid)):
        x("delete from saves where user_id=? and post_id=?", (session["uid"], pid))
    else:
        x("insert into saves(user_id,post_id) values(?,?)", (session["uid"], pid))
    return redirect(request.referrer or "/")

@app.route("/services")
@need("customer")
def services():
    return page("Dịch vụ chụp ảnh", blocks=[dict(cards=[svc_card(s) for s in services_rows()])])

@app.route("/match")
@need("customer")
def match():
    text = request.args.get("q", "").strip().lower()
    budget = request.args.get("budget", "")
    blocks = [dict(h="Mô tả buổi chụp bạn muốn", note="Gợi ý dựa trên từ khoá, phong cách và ngân sách (bản demo, chưa gắn mô hình AI).",
                   form=dict(action="/match", via="get", submit="Tìm gợi ý",
                             fields=[F("q", "Ví dụ: sinh nhật vintage, couple kiểu Hàn", "text", val=text), F("budget", "Ngân sách tối đa (đồng)", "number", val=budget)]))]
    if text:
        words = [w for w in text.replace(",", " ").split() if len(w) > 1]
        res = []
        for s in services_rows():
            hay = " ".join([s["title"], s["style"], s["descr"], s["pname"]]).lower()
            score = sum(w in hay for w in words) + (2 if s["style"].lower() in text else 0)
            if score and (not budget or s["price"] <= int(budget)):
                res.append((score, s))
        res.sort(key=lambda r: -r[0])
        blocks.append(dict(h="Gợi ý cho bạn", cards=[svc_card(s) for _, s in res[:6]]))
    return page("AI Concept Match", blocks=blocks)

@app.route("/book/<int:sid>", methods=["GET", "POST"])
@need("customer")
def book(sid):
    s = q("select s.*, p.name pname from services s join partners p on p.id=s.partner_id where s.id=?", (sid,), True)
    if not s:
        abort(404)
    if request.method == "POST":
        day = request.form["day"]
        if day < date.today().isoformat():
            flash("Ngày chụp phải từ hôm nay trở đi.")
        else:
            bid = x("insert into bookings(user_id,service_id,partner_id,day,status,total,note,created) values(?,?,?,?,?,?,?,?)",
                    (session["uid"], sid, s["partner_id"], day, "pending", s["price"], request.form.get("note", ""), date.today().isoformat()))
            automation.fire("booking_created", bid)
            flash("Đã tạo đơn. Hãy thanh toán cọc 30% để giữ lịch.")
            return redirect("/my")
    return page(f"Đặt lịch: {s['title']}", sub=f"{s['pname']} · {vnd(s['price'])} · cọc 30% = {vnd(s['price'] * 0.3)}",
                blocks=[dict(form=dict(action=f"/book/{sid}", submit="Tạo đơn đặt lịch",
                                       fields=[F("day", "Ngày chụp", "date", val=date.today().isoformat()), F("note", "Mô tả concept / moodboard", "textarea")]))])

@app.route("/my")
@need("customer")
def my():
    u = me()
    bk = q("select b.*, s.title, (select 1 from reviews r where r.booking_id=b.id) reviewed from bookings b join services s on s.id=b.service_id where b.user_id=? order by b.day desc", (u["id"],))
    rows = []
    for b in bk:
        a = ""
        if b["status"] in ("pending", "confirmed") and not b["deposit_paid"]:
            a = btn(f"/pay/{b['id']}", f"Thanh toán cọc {vnd(b['total'] * 0.3)}")
        elif b["status"] == "completed" and not b["reviewed"]:
            a = Markup(f'<form method="post" action="/review/{b["id"]}" class="inline"><select name="rating"><option>5</option><option>4</option><option>3</option><option>2</option><option>1</option></select> <button>Đánh giá ★</button></form>')
        rows.append([f"#{b['id']}", b["title"], b["day"], STATUS[b["status"]], vnd(b["total"]), "Đã cọc" if b["deposit_paid"] else "Chưa cọc", a])
    mood = q("select po.*, p.name pname from saves s join posts po on po.id=s.post_id join partners p on p.id=po.partner_id where s.user_id=?", (u["id"],))
    ns = q("select ts, body from notifs where user_id=? order by id desc limit 8", (u["id"],))
    return page("Của tôi", stats=[("PhotoPoint", u["points"]), ("Số đơn", len(bk))], blocks=[
        dict(h="Đơn đặt lịch", cols=["Mã", "Dịch vụ", "Ngày", "Trạng thái", "Tổng", "Cọc", ""], rows=rows),
        dict(h="Moodboard", cards=[dict(title=r["caption"], sub=r["pname"], c1=r["c1"], c2=r["c2"], img=img_url(r["img"]), actions="") for r in mood]),
        dict(h="Thông báo", cols=["Lúc", "Nội dung"], rows=[[n["ts"], n["body"]] for n in ns])])

@app.post("/pay/<int:bid>")
@need("customer")
def pay(bid):
    x("update bookings set deposit_paid=1 where id=? and user_id=?", (bid, session["uid"]))
    flash("Đã ghi nhận thanh toán cọc (mô phỏng, chưa nối cổng thanh toán).")
    return redirect("/my")

@app.post("/review/<int:bid>")
@need("customer")
def review(bid):
    b = q("select * from bookings where id=? and user_id=? and status='completed'", (bid, session["uid"]), True)
    if b and not q("select 1 from reviews where booking_id=?", (bid,)):
        x("insert into reviews(booking_id,partner_id,rating,comment) values(?,?,?,?)", (bid, b["partner_id"], int(request.form["rating"]), ""))
        flash("Cảm ơn bạn đã đánh giá.")
    return redirect("/my")

# ================= BLOCK DÙNG CHUNG (đối tác + admin) =================
def inv_block(pid=None):
    rows = []
    for it in inventory.items(pid):
        p = forecasting.item_plan(it)
        st = inventory.status(it, p["rop"])
        rows.append([it["name"]] + ([] if pid else [it["pname"]]) + [it["cat"], it["stock"], round(p["rop"], 1),
                     tag(st, "g" if st == "Ổn định" else "r"), bars(p["series"], p["fc"]), p["order"] or "-"])
    cols = ["Vật tư / thiết bị"] + ([] if pid else ["Đối tác"]) + ["Nhóm", "Tồn kho", "Điểm đặt lại", "Trạng thái", "Nhu cầu 12 tuần (xám) + dự báo 4 tuần (màu)", "Đề xuất nhập"]
    return dict(h="Tồn kho", cols=cols, rows=rows)

def forecast_blocks(pid=None):
    cnt, rev = forecasting.booking_series(pid)
    fc, name, mae = forecasting.forecast(cnt)
    fr, rname, _ = forecasting.forecast(rev)
    wk = [(date.today() + timedelta(weeks=i + 1)).strftime("%d/%m") for i in range(4)]
    b1 = dict(h="Dự báo đặt lịch và doanh thu", html=bars(cnt, fc, True),
              note=f"Đếm đơn: {name} (sai số TB {mae:.1f} đơn/tuần). Doanh thu: {rname}.",
              cols=["Tuần bắt đầu", "Đơn dự báo", "Doanh thu dự báo"], rows=[[wk[i], round(fc[i], 1), vnd(fr[i])] for i in range(4)])
    rows = []
    for it in inventory.items(pid):
        p = forecasting.item_plan(it)
        rows.append([it["name"], p["method"], f"{p['mae']:.1f}"] + [round(v, 1) for v in p["fc"]] + ["∞" if p["cover"] is None else f"{p['cover']:.0f} ngày", p["order"]])
    b2 = dict(h="Dự báo nhu cầu vật tư (4 tuần tới)", note="Điểm đặt lại = nhu cầu/ngày × thời gian giao + tồn kho an toàn (mức phục vụ 95%).",
              cols=["Vật tư", "Phương pháp", "Sai số (MAE)", "Tuần 1", "Tuần 2", "Tuần 3", "Tuần 4", "Tồn đủ dùng", "Đề xuất nhập"], rows=rows)
    return [b1, b2]

SEG_CLS = {"VIP": "g", "Nguy cơ rồi bỏ": "r", "Nguy cơ rời bỏ": "r"}

def crm_rows(cs):
    return [[c["name"], c["email"], c["n"], vnd(c["spend"]), c["last"] or "-", tag(c["seg"], SEG_CLS.get(c["seg"], "")), c["tags"], c["points"]] for c in cs]

CRM_COLS = ["Khách hàng", "Email", "Số đơn", "Chi tiêu", "Lần cuối", "Phân khúc", "Thẻ", "Điểm"]

# ================= GIAO DIỆN ĐỐI TÁC =================
FLOW = {"confirm": ("pending", "confirmed"), "complete": ("confirmed", "completed"), "cancel": (None, "cancelled")}

@app.route("/partner")
@need("partner")
def partner_home():
    p = mypartner()
    bk = q("select b.*, s.title, u.name uname from bookings b join services s on s.id=b.service_id join users u on u.id=b.user_id where b.partner_id=? order by b.day desc limit 30", (p["id"],))
    rows = []
    for b in bk:
        a = ""
        if b["status"] == "pending":
            a = btn(f"/partner/booking/{b['id']}/confirm", "Xác nhận") + btn(f"/partner/booking/{b['id']}/cancel", "Huỷ", "bad")
        elif b["status"] == "confirmed":
            a = btn(f"/partner/booking/{b['id']}/complete", "Hoàn thành") + btn(f"/partner/booking/{b['id']}/cancel", "Huỷ", "bad")
        rows.append([f"#{b['id']}", b["uname"], b["title"], b["day"], STATUS[b["status"]], vnd(b["total"]), "Đã cọc" if b["deposit_paid"] else "Chưa cọc", a])
    rev = q("select coalesce(sum(total),0) t from bookings where partner_id=? and status='completed'", (p["id"],), True)["t"]
    rating = q("select round(avg(rating),1) r from reviews where partner_id=?", (p["id"],), True)["r"]
    tasks = q("select * from tasks where partner_id=? and done=0", (p["id"],))
    ns = q("select ts, body from notifs where user_id=? order by id desc limit 6", (session["uid"],))
    return page(p["name"], stats=[("Doanh thu thực nhận (sau hoa hồng 10%)", vnd(rev * (1 - COMMISSION))), ("Đơn chờ xử lý", sum(b["status"] in ("pending", "confirmed") for b in bk)), ("Đánh giá TB", rating or "-")], blocks=[
        dict(h="Đơn đặt lịch", cols=["Mã", "Khách", "Dịch vụ", "Ngày", "Trạng thái", "Tổng", "Cọc", ""], rows=rows),
        dict(h="Việc cần làm (do tự động hoá tạo)", cols=["Việc", ""], rows=[[t["title"], btn(f"/partner/task/{t['id']}", "Xong", "alt")] for t in tasks]),
        dict(h="Thông báo", cols=["Lúc", "Nội dung"], rows=[[n["ts"], n["body"]] for n in ns])])

@app.post("/partner/booking/<int:bid>/<act>")
@need("partner")
def partner_booking(bid, act):
    b = q("select * from bookings where id=? and partner_id=?", (bid, mypartner()["id"]), True)
    if not b or act not in FLOW:
        abort(404)
    src, dst = FLOW[act]
    if b["status"] in ("completed", "cancelled") or (src and b["status"] != src):
        flash("Trạng thái đơn không hợp lệ.")
        return redirect("/partner")
    x("update bookings set status=? where id=?", (dst, bid))
    if dst == "completed":
        automation.fire("booking_completed", bid)
    return redirect("/partner")

@app.post("/partner/task/<int:tid>")
@need("partner")
def partner_task(tid):
    x("update tasks set done=1 where id=? and partner_id=?", (tid, mypartner()["id"]))
    return redirect("/partner")

@app.route("/partner/inventory")
@need("partner")
def partner_inventory():
    p = mypartner()
    its = inventory.items(p["id"])
    cats = [("camera", "Máy ảnh"), ("lens", "Lens"), ("light", "Đèn"), ("backdrop", "Phông nền"), ("print", "Vật tư in"), ("tripod", "Chân máy"), ("other", "Khác")]
    return page("Kho vật tư và thiết bị", blocks=[inv_block(p["id"]),
        dict(h="Nhập / xuất kho", form=dict(action="/partner/inventory/move", submit="Ghi nhận", fields=[
            F("item_id", "Mặt hàng", "select", [(i["id"], i["name"]) for i in its]),
            F("kind", "Loại", "select", [("in", "Nhập kho"), ("out", "Xuất kho / cho thuê"), ("return", "Khách trả")]), F("qty", "Số lượng", "number", val=1)])),
        dict(h="Thêm mặt hàng", form=dict(action="/partner/inventory/add", submit="Thêm", fields=[
            F("name", "Tên"), F("cat", "Nhóm", "select", cats), F("stock", "Tồn đầu", "number", val=0), F("reorder", "Mức tối thiểu", "number", val=0),
            F("lead", "Thời gian giao (ngày)", "number", val=2), F("price", "Giá / đơn vị", "number", val=0)]))])

@app.post("/partner/inventory/move")
@need("partner")
def partner_move():
    it = q("select * from items where id=? and partner_id=?", (request.form["item_id"], mypartner()["id"]), True)
    if not it:
        abort(404)
    try:
        inventory.move(it["id"], request.form["kind"], request.form["qty"], "Nhập tay")
    except ValueError as e:
        flash(str(e))
    return redirect("/partner/inventory")

@app.post("/partner/inventory/add")
@need("partner")
def partner_add():
    f, pid = request.form, mypartner()["id"]
    stock = int(f.get("stock") or 0)
    iid = x("insert into items(partner_id,name,cat,stock,reorder,lead,price) values(?,?,?,?,?,?,?)",
            (pid, f["name"], f["cat"], 0, int(f.get("reorder") or 0), max(1, int(f.get("lead") or 2)), int(f.get("price") or 0)))
    if stock > 0:
        inventory.move(iid, "in", stock, "Tồn đầu")
    return redirect("/partner/inventory")

@app.route("/partner/forecast")
@need("partner")
def partner_forecast():
    return page("Dự báo", blocks=forecast_blocks(mypartner()["id"]))

@app.route("/partner/customers")
@need("partner")
def partner_customers():
    cs = crm.customers(mypartner()["id"])
    cnt = Counter(c["seg"] for c in cs)
    return page("Khách hàng của tôi", stats=[(s, cnt.get(s, 0)) for s in crm.SEGMENTS], blocks=[dict(cols=CRM_COLS, rows=crm_rows(cs))])

# ================= GIAO DIỆN ADMIN =================
def contact_block():
    c = contact()
    return dict(h="Thông tin liên hệ hiển thị trên website", form=dict(action="/admin/contact", submit="Lưu thông tin", fields=[
        F("hotline", "Hotline", val=c["hotline"]), F("phone", "Số điện thoại", val=c["phone"]),
        F("email", "Email", "email", val=c["email"]), F("address", "Địa chỉ", val=c["address"])]))

@app.post("/admin/contact")
@need("admin")
def admin_contact():
    for k in ("hotline", "phone", "email", "address"):
        x("insert or replace into settings(k,v) values(?,?)", (k, request.form[k].strip()))
    flash("Đã lưu thông tin liên hệ.")
    return redirect("/admin")

@app.route("/admin")
@need("admin")
def admin_home():
    gmv = q("select coalesce(sum(total),0) t from bookings where status in ('confirmed','completed')", one=True)["t"]
    one = lambda sql: q(sql, one=True)["c"]
    recent = q("select b.id, u.name un, p.name pn, b.day, b.status, b.total from bookings b join users u on u.id=b.user_id join partners p on p.id=b.partner_id order by b.id desc limit 10")
    return page("Tổng quan nền tảng", stats=[("GMV (đơn xác nhận + hoàn thành)", vnd(gmv)), (f"Hoa hồng nền tảng ({int(COMMISSION * 100)}%)", vnd(gmv * COMMISSION)),
                ("Khách hàng", one("select count(*) c from users where role='customer'")), ("Đối tác", one("select count(*) c from partners")),
                ("Việc tồn kho đang mở", one("select count(*) c from tasks where done=0"))],
                blocks=[dict(h="Đơn gần đây", cols=["Mã", "Khách", "Đối tác", "Ngày", "Trạng thái", "Tổng"],
                             rows=[[f"#{r['id']}", r["un"], r["pn"], r["day"], STATUS[r["status"]], vnd(r["total"])] for r in recent]), forecast_blocks()[0], contact_block()])

@app.route("/admin/crm")
@need("admin")
def admin_crm():
    cs = crm.customers()
    cnt = Counter(c["seg"] for c in cs)
    leads = q("select * from leads order by stage, id")
    lrows = []
    for l in leads:
        a = ""
        if l["stage"] < 3:
            a = btn(f"/admin/crm/lead/{l['id']}/{l['stage'] + 1}", f"→ {STAGES[l['stage'] + 1]}") + btn(f"/admin/crm/lead/{l['id']}/4", "Mất", "bad")
        lrows.append([l["name"], l["contact"], l["source"], tag(STAGES[l["stage"]], "g" if l["stage"] == 3 else ""), vnd(l["value"]), a])
    notes = q("select n.created, u.name, n.body from notes n join users u on u.id=n.user_id order by n.id desc limit 8")
    opts = [(c["id"], c["name"]) for c in cs]
    return page("CRM", stats=[(s, cnt.get(s, 0)) for s in crm.SEGMENTS], blocks=[
        dict(h="Khách hàng và phân khúc", note="VIP: từ 3 đơn hoặc chi tiêu từ 6 triệu. Nguy cơ rời bỏ: từ 2 đơn nhưng quá 60 ngày không đặt lại.", cols=CRM_COLS, rows=crm_rows(cs)),
        dict(h="Ghi chú chăm sóc", form=dict(action="/admin/crm/note", submit="Lưu ghi chú", fields=[F("uid", "Khách hàng", "select", opts), F("body", "Nội dung")]),
             cols=["Lúc", "Khách", "Ghi chú"], rows=[[n["created"], n["name"], n["body"]] for n in notes]),
        dict(h="Pipeline khách tiềm năng", cols=["Tên", "Liên hệ", "Nguồn", "Giai đoạn", "Giá trị", ""], rows=lrows,
             form=dict(action="/admin/crm/lead", submit="Thêm khách tiềm năng", fields=[F("name", "Tên"), F("contact", "Liên hệ"), F("source", "Nguồn"), F("value", "Giá trị (đồng)", "number", val=0)])),
        dict(h="Chiến dịch tin nhắn", form=dict(action="/admin/crm/campaign", submit="Gửi chiến dịch", fields=[F("seg", "Nhóm khách", "select", [(s, s) for s in crm.SEGMENTS]), F("text", "Nội dung")]))])

@app.post("/admin/crm/note")
@need("admin")
def crm_note():
    crm.add_note(int(request.form["uid"]), request.form["body"])
    return redirect("/admin/crm")

@app.post("/admin/crm/lead")
@need("admin")
def crm_lead():
    f = request.form
    x("insert into leads(name,contact,source,stage,value) values(?,?,?,0,?)", (f["name"], f["contact"], f["source"], int(f.get("value") or 0)))
    return redirect("/admin/crm")

@app.post("/admin/crm/lead/<int:lid>/<int:stage>")
@need("admin")
def crm_lead_stage(lid, stage):
    if 0 <= stage < len(STAGES):
        x("update leads set stage=? where id=?", (stage, lid))
    return redirect("/admin/crm")

@app.post("/admin/crm/campaign")
@need("admin")
def crm_campaign():
    flash(f"Đã gửi tới {crm.send_campaign(request.form['seg'], request.form['text'])} khách.")
    return redirect("/admin/crm")

@app.route("/admin/inventory")
@need("admin")
def admin_inventory():
    return page("Kho toàn nền tảng", blocks=[inv_block()])

@app.route("/admin/forecast")
@need("admin")
def admin_forecast():
    return page("Dự báo toàn nền tảng", blocks=forecast_blocks())

@app.route("/admin/automation")
@need("admin")
def admin_automation():
    rules = q("select * from rules order by id")
    logs = q("select * from logs order by id desc limit 15")
    return page("Tự động hoá", sub="Quy tắc theo sự kiện chạy ngay khi có đơn; quy tắc theo lịch chạy mỗi 5 phút hoặc khi bấm nút.", blocks=[
        dict(h="Quy tắc", cols=["Quy tắc", "Sự kiện", "Hành động", "Ngưỡng", "Số lần chạy", "Trạng thái", ""],
             rows=[[r["name"], r["trigger"], r["action"], r["param"] or "-", r["runs"], tag("Bật", "g") if r["enabled"] else tag("Tắt"),
                    btn(f"/admin/automation/{r['id']}/toggle", "Tắt" if r["enabled"] else "Bật", "alt")] for r in rules]),
        dict(h="Chạy các quy tắc theo lịch", form=dict(action="/admin/automation/run", submit="Chạy ngay", fields=[])),
        dict(h="Nhật ký", cols=["Lúc", "Quy tắc", "Chi tiết"], rows=[[l["ts"], l["rule"], l["detail"]] for l in logs])])

@app.post("/admin/automation/<int:rid>/toggle")
@need("admin")
def automation_toggle(rid):
    x("update rules set enabled=1-enabled where id=?", (rid,))
    return redirect("/admin/automation")

@app.post("/admin/automation/run")
@need("admin")
def automation_run():
    flash(f"Đã chạy xong, có {automation.run_scheduled()} hành động mới.")
    return redirect("/admin/automation")

@app.route("/admin/users")
@need("admin")
def admin_users():
    us = q("select u.name, u.email, u.role, u.points, u.created from users u order by u.role, u.id")
    ps = q("select p.name, p.kind, p.city, (select count(*) from bookings b where b.partner_id=p.id) n, "
           "(select coalesce(sum(total),0) from bookings b where b.partner_id=p.id and b.status='completed') rev, "
           "(select round(avg(rating),1) from reviews r where r.partner_id=p.id) rating from partners p")
    return page("Người dùng và đối tác", blocks=[
        dict(h="Đối tác", cols=["Tên", "Loại", "Thành phố", "Số đơn", "Doanh thu hoàn thành", "Đánh giá"], rows=[[p["name"], p["kind"], p["city"], p["n"], vnd(p["rev"]), p["rating"] or "-"] for p in ps]),
        dict(h="Tất cả tài khoản", cols=["Tên", "Email", "Vai trò", "Điểm", "Ngày tạo"], rows=[[u["name"], u["email"], u["role"], u["points"], u["created"]] for u in us])])

def concept_page(pid=None):
    base = "/partner" if pid else "/admin"
    ps = q("select po.*, p.name pname from posts po join partners p on p.id=po.partner_id" + (" where po.partner_id=?" if pid else "") + " order by po.id", (pid,) if pid else ())
    rows = []
    for r in ps:
        link = ""
        if r["img"] and not r["img"].startswith("post-"):
            link = Markup(f'<a href="https://unsplash.com/s/photos/{escape(r["img"])}" target="_blank" rel="noopener">Tìm trên Unsplash</a>')
        rows.append([r["id"], r["caption"], r["style"], r["pname"], r["img"] or "-", tag("Có ảnh", "g") if img_url(r["img"]) else tag("Chưa có ảnh", "r"), link])
    add = ([] if pid else [F("partner", "Đối tác", "select", [(p["id"], p["name"]) for p in q("select id, name from partners")])]) + \
          [F("caption", "Tên concept"), F("style", "Phong cách (ví dụ Wedding)"), F("file", "Ảnh (tuỳ chọn)", "file")]
    return page("Concept và hình ảnh", sub="Ảnh được lưu theo tên trong cột \"Tên file\" (thư mục static/img). Chỉ dùng ảnh bạn có quyền sử dụng; kiểm tra giấy phép trước khi tải ảnh từ Unsplash/Pexels.", blocks=[
        dict(cols=["ID", "Concept", "Phong cách", "Đối tác", "Tên file", "Ảnh", "Gợi ý tìm ảnh"], rows=rows),
        dict(h="Tải ảnh cho concept", form=dict(action=base + "/concepts/upload", submit="Tải ảnh lên", fields=[
            F("post", "Concept", "select", [(r["id"], r["caption"]) for r in ps]), F("file", "Ảnh (jpg, png, webp; tối đa 5MB)", "file")])),
        dict(h="Thêm concept mới", form=dict(action=base + "/concepts/add", submit="Thêm concept", fields=add))])

def upload_post(owner):
    po = q("select * from posts where id=?", (request.form["post"],), True)
    if not po or (owner and po["partner_id"] != owner):
        abort(404)
    ok = save_img(po["img"], request.files.get("file"))
    flash("Đã cập nhật ảnh." if ok else "File ảnh không hợp lệ (chỉ nhận jpg, png, webp).")

def add_post(owner):
    f = request.form
    n = x("insert into posts(partner_id,caption,style,c1,c2,likes,img) values(?,?,?,?,?,0,'')",
          (owner or int(f["partner"]), f["caption"], f["style"], "#7FA6C9", "#1D3557"))
    slug = f"post-{n}"
    x("update posts set img=? where id=?", (slug, n))
    save_img(slug, request.files.get("file"))
    flash("Đã thêm concept.")

@app.route("/admin/concepts")
@need("admin")
def admin_concepts():
    return concept_page()

@app.post("/admin/concepts/upload")
@need("admin")
def admin_concept_upload():
    upload_post(None)
    return redirect("/admin/concepts")

@app.post("/admin/concepts/add")
@need("admin")
def admin_concept_add():
    add_post(None)
    return redirect("/admin/concepts")

@app.route("/partner/concepts")
@need("partner")
def partner_concepts():
    return concept_page(mypartner()["id"])

@app.post("/partner/concepts/upload")
@need("partner")
def partner_concept_upload():
    upload_post(mypartner()["id"])
    return redirect("/partner/concepts")

@app.post("/partner/concepts/add")
@need("partner")
def partner_concept_add():
    add_post(mypartner()["id"])
    return redirect("/partner/concepts")

def _loop():
    while True:
        time.sleep(300)
        try:
            automation.run_scheduled()
        except Exception as e:
            print("automation lỗi:", e)

if __name__ == "__main__":
    automation.run_scheduled()
    threading.Thread(target=_loop, daemon=True).start()
    app.run(debug=False, port=5000)
