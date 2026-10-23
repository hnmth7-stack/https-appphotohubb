"""Module Forecasting: dự báo nhu cầu theo tuần (trung bình trượt / Holt), điểm đặt lại, đề xuất nhập."""
import math, statistics
from datetime import date
from core import q

def weekly(rows, weeks=26):
    s = [0.0] * weeks
    t = date.today()
    for d, v in rows:
        i = (t - date.fromisoformat(d)).days // 7
        if 0 <= i < weeks:
            s[weeks - 1 - i] += v
    return s

def _ma(s, h):
    return [sum(s[-4:]) / 4] * h

def _holt(s, h, a=0.4, b=0.2):
    l, t = s[0], s[1] - s[0]
    for y in s[1:]:
        p = l
        l = a * y + (1 - a) * (l + t)
        t = b * (l - p) + (1 - b) * t
    return [max(0.0, l + (k + 1) * t) for k in range(h)]

METHODS = {"Trung bình trượt 4 tuần": _ma, "Holt (xu hướng)": _holt}

def forecast(s, h=4):
    """Chọn phương pháp có sai số thấp nhất trên 4 tuần gần nhất (backtest)."""
    tr, te = s[:-4], s[-4:]
    err = {n: sum(abs(a - b) for a, b in zip(f(tr, 4), te)) / 4 for n, f in METHODS.items()}
    name = min(err, key=err.get)
    return METHODS[name](s, h), name, err[name]

def item_plan(it):
    rows = q("select day, qty from moves where item_id=? and kind='out'", (it["id"],))
    s = weekly([(r["day"], r["qty"]) for r in rows])
    fc, name, mae = forecast(s)
    daily = sum(fc) / 28
    sd = statistics.pstdev(s[-12:])
    safety = 1.65 * sd / math.sqrt(7) * math.sqrt(it["lead"])      # mức phục vụ ~95%
    rop = daily * it["lead"] + safety                                # điểm đặt lại
    cover = it["stock"] / daily if daily > 0 else None
    order = max(0, math.ceil(daily * (it["lead"] + 14) + safety - it["stock"]))
    return dict(series=s, fc=fc, method=name, mae=mae, rop=rop, cover=cover, order=order)

def booking_series(partner_id=None):
    sql = "select day, total from bookings where status!='cancelled'"
    rows = q(sql + (" and partner_id=?" if partner_id else ""), (partner_id,) if partner_id else ())
    return weekly([(r["day"], 1) for r in rows]), weekly([(r["day"], r["total"]) for r in rows])
