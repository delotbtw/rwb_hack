import sqlite3
db=sqlite3.connect('/private/tmp/claude-501/-Users-nick-Documents-hack/d776d94d-0a42-45e0-9cc4-4f938b944ec0/scratchpad/p.db')
T=13221498.11
sets={'delivered':"('delivered')",'del+shipped':"('delivered','shipped')",'not canc/unav':"('delivered','shipped','invoiced','processing','created','approved')",'excl canceled':"('delivered','shipped','invoiced','processing','created','approved','unavailable')",'all':"('delivered','shipped','invoiced','processing','created','approved','unavailable','canceled')",'del+ship+inv+proc+appr':"('delivered','shipped','invoiced','processing','approved')"}
for nm,s in sets.items():
  for per in ['full','sep16-aug18']:
    w=" and substr(o.order_purchase_timestamp,1,7)<='2018-08'" if per!='full' else ''
    r=db.execute(f"select round(sum(cast(price as real)),2),round(sum(cast(price as real)+cast(freight_value as real)),2),count(distinct o.order_id) from items i join orders o using(order_id) where o.order_status in {s}{w}").fetchone()
    print(nm,per,r,'MATCH' if T in r[:2] else '')
