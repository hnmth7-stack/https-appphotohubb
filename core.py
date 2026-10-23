import os, sqlite3
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photohub.db")

def _run(sql, a, fetch):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        cur = c.execute(sql, a)
        if fetch:
            return cur.fetchall()
        c.commit()
        return cur.lastrowid
    finally:
        c.close()

def q(sql, a=(), one=False):
    r = _run(sql, a, True)
    return (r[0] if r else None) if one else r

def x(sql, a=()):
    return _run(sql, a, False)

def notify(uid, body):
    x("insert into notifs(user_id,body,ts) values(?,?,?)", (uid, body, datetime.now().strftime("%d/%m %H:%M")))

SCHEMA = """
create table if not exists users(id integer primary key, email text unique, name text, pw text, role text, points int default 0, tags text default '', created text);
create table if not exists partners(id integer primary key, user_id int, name text, kind text, city text, bio text);
create table if not exists services(id integer primary key, partner_id int, title text, style text, price int, descr text);
create table if not exists items(id integer primary key, partner_id int, name text, cat text, stock int, reorder int, lead int default 2, price int);
create table if not exists moves(id integer primary key, item_id int, kind text, qty int, day text, note text);
create table if not exists bookings(id integer primary key, user_id int, service_id int, partner_id int, day text, status text, total int, deposit_paid int default 0, note text, created text);
create table if not exists reviews(id integer primary key, booking_id int, partner_id int, rating int, comment text);
create table if not exists posts(id integer primary key, partner_id int, caption text, style text, c1 text, c2 text, likes int default 0);
create table if not exists saves(user_id int, post_id int);
create table if not exists leads(id integer primary key, name text, contact text, source text, stage int default 0, value int);
create table if not exists notes(id integer primary key, user_id int, body text, created text);
create table if not exists rules(id integer primary key, name text, trigger text, param int, action text, enabled int default 1, runs int default 0);
create table if not exists logs(id integer primary key, ts text, rule text, detail text);
create table if not exists notifs(id integer primary key, user_id int, body text, ts text);
create table if not exists settings(k text primary key, v text);
create table if not exists tasks(id integer primary key, partner_id int, title text, done int default 0);
"""

def init():
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    for t in ("posts", "services"):          # nâng cấp DB cũ: thêm cột ảnh
        try:
            c.execute(f"alter table {t} add column img text default ''")
        except sqlite3.OperationalError:
            pass
    c.commit()
    c.close()

CONTACT = {"hotline": "1900 0000", "phone": "0900 000 000", "email": "admin@photohub.vn", "address": "TP. Hồ Chí Minh"}

def contact():
    d = dict(CONTACT)
    d.update({r["k"]: r["v"] for r in q("select k, v from settings")})
    return d
