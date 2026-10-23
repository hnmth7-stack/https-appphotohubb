"""Module Automation: quy tắc theo sự kiện (đơn mới, hoàn thành) và theo lịch (tồn kho, khách im lặng, nhắc cọc)."""
from datetime import date, datetime, timedelta
from core import q, x, notify
from modules import crm, forecasting, inventory

def _log(r, detail):
    x("insert into logs(ts,rule,detail) values(?,?,?)", (datetime.now().strftime("%d/%m %H:%M"), r["name"], detail))
    x("update rules set runs=runs+1 where id=?", (r["id"],))

def _rules(trigger):
    return q("select * from rules where enabled=1 and trigger=?", (trigger,))

def fire(event, bid):
    b = q("select b.*, p.user_id puid from bookings b join partners p on p.id=b.partner_id where b.id=?", (bid,), True)
    for r in _rules(event):
        if event == "booking_created":
            notify(b["puid"], f"Đơn mới #{bid} cho ngày {b['day']}. Hãy xác nhận lịch.")
            _log(r, f"Thông báo đối tác về đơn #{bid}")
        elif event == "booking_completed":
            pts = b["total"] // 10000
            x("update users set points=points+? where id=?", (pts, b["user_id"]))
            notify(b["user_id"], f"Bạn nhận {pts} PhotoPoint. Hãy đánh giá buổi chụp #{bid}.")
            _log(r, f"Cộng {pts} điểm cho khách (đơn #{bid})")

def run_scheduled():
    n = 0
    for r in _rules("low_stock"):
        for it in inventory.items():
            plan = forecasting.item_plan(it)
            if it["stock"] <= max(it["reorder"], plan["rop"]):
                prefix = f"Nhập thêm {it['name']}"
                if not q("select 1 from tasks where partner_id=? and done=0 and title like ?", (it["partner_id"], prefix + "%")):
                    x("insert into tasks(partner_id,title) values(?,?)", (it["partner_id"], f"{prefix} (đề xuất {plan['order']})"))
                    notify(it["puid"], f"{it['name']} sắp hết, đề xuất nhập {plan['order']}.")
                    _log(r, f"Tạo việc nhập hàng: {it['name']}")
                    n += 1
    for r in _rules("inactive"):
        for c in crm.customers():
            if c["n"] and "at_risk" not in c["tags"] and (date.today() - date.fromisoformat(c["last"])).days > r["param"]:
                x("update users set tags=? where id=?", ((c["tags"] + " at_risk").strip(), c["id"]))
                notify(c["id"], "Lâu rồi chưa gặp! Dùng PhotoPoint để giảm giá cho buổi chụp tiếp theo.")
                _log(r, f"Gắn thẻ at_risk và gửi ưu đãi cho {c['name']}")
                n += 1
    for r in _rules("deposit"):
        lim = (date.today() - timedelta(days=r["param"])).isoformat()
        for b in q("select id,user_id from bookings where status='pending' and deposit_paid=0 and created<=?", (lim,)):
            body = f"Nhắc thanh toán cọc cho đơn #{b['id']} để giữ lịch."
            if not q("select 1 from notifs where user_id=? and body=?", (b["user_id"], body)):
                notify(b["user_id"], body)
                _log(r, f"Nhắc cọc đơn #{b['id']}")
                n += 1
    return n
