"""Module Inventory: tồn kho vật tư, thiết bị cho thuê, giấy in..."""
from datetime import date
from core import q, x

def items(partner_id=None):
    sql = "select i.*, p.name pname, p.user_id puid from items i join partners p on p.id=i.partner_id"
    if partner_id:
        return q(sql + " where i.partner_id=? order by i.name", (partner_id,))
    return q(sql + " order by p.name, i.name")

def move(item_id, kind, qty, note=""):
    """kind: in (nhập), out (xuất/cho thuê), return (khách trả)."""
    qty = abs(int(qty))
    sign = 1 if kind in ("in", "return") else -1
    it = q("select stock from items where id=?", (item_id,), True)
    if it is None or qty == 0:
        raise ValueError("Mặt hàng hoặc số lượng không hợp lệ")
    if sign < 0 and qty > it["stock"]:
        raise ValueError("Không đủ tồn kho")
    x("insert into moves(item_id,kind,qty,day,note) values(?,?,?,?,?)", (item_id, kind, qty, date.today().isoformat(), note))
    x("update items set stock=stock+? where id=?", (sign * qty, item_id))

def status(it, rop=None):
    if it["stock"] <= 0:
        return "Hết hàng"
    if it["stock"] <= it["reorder"] or (rop is not None and it["stock"] <= rop):
        return "Sắp hết"
    return "Ổn định"
