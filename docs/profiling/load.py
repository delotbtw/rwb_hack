import csv,sqlite3,sys,os
D='/Users/nick/Documents/hack/data/'
db=sqlite3.connect('/private/tmp/claude-501/-Users-nick-Documents-hack/d776d94d-0a42-45e0-9cc4-4f938b944ec0/scratchpad/p.db')
m={'orders':'olist_orders_dataset','items':'olist_order_items_dataset','pay':'olist_order_payments_dataset','rev':'olist_order_reviews_dataset','prod':'olist_products_dataset','sel':'olist_sellers_dataset','cust':'olist_customers_dataset','tr':'product_category_name_translation'}
for t,f in m.items():
    raw=open(D+f+'.csv','rb').read(3)
    print(t,'BOM' if raw==b'\xef\xbb\xbf' else 'noBOM')
    with open(D+f+'.csv',newline='',encoding='utf-8-sig') as fh:
        r=csv.reader(fh);h=next(r)
        db.execute(f'drop table if exists {t}')
        db.execute(f'create table {t}({",".join(c+" text" for c in h)})')
        rows=list(r)
        bad=sum(1 for x in rows if len(x)!=len(h))
        db.executemany(f'insert into {t} values({",".join("?"*len(h))})',rows)
        print(t,len(rows),'badlen',bad,h[:3])
db.commit()
