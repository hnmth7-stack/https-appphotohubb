"""Module CRM: phân khúc khách hàng (RFM đơn giản), ghi chú, chiến dịch."""
from datetime import date, datetime
from core import q, x, notify

SEGMENTS = ["VIP", "Đang hoạt động", "Mới", "Nguy cơ rời bỏ", "Ngủ đông"]

def segment(n, last, spend):
    if n == 0:
        return "Mới"
    days = (date.today() - date.fromisoformat(last)).days
    if days > 60:
        return "Nguy cơ rời bỏ" if n >= 2 else "Ngủ đông"
    if n >= 3 or spend >= 6_000_000:
        return "VIP"
    return "Đang hoạt động"

def customers(partner_id=None):
    on = " and b.partner_id=?" if partner_id else ""
    rows = q("select u.id,u.name,u.email,u.points,u.tags,count(b.id) n,coalesce(sum(b.total),0) spend,max(b.day) last "
             "from users u left join bookings b on b.user_id=u.id and b.status!='cancelled'" + on +
             " where u.role='customer' group by u.id order by spend desc", (partner_id,) if partner_id else ())
    out = []
    for r in rows:
        if partner_id and r["n"] == 0:
            continue
        d = dict(r)
        d["seg"] = segment(r["n"], r["last"], r["spend"])
        out.append(d)
    return out

def add_note(uid, body):
    x("insert into notes(user_id,body,created) values(?,?,?)", (uid, body, datetime.now().strftime("%d/%m %H:%M")))

def send_campaign(seg, text):
    targets = [c for c in customers() if c["seg"] == seg]
    for c in targets:
        notify(c["id"], text)
    x("insert into logs(ts,rule,detail) values(?,?,?)", (datetime.now().strftime("%d/%m %H:%M"), "Chiến dịch CRM", f"Gửi tới {len(targets)} khách thuộc nhóm {seg}"))
    return len(targets)
