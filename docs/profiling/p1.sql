-- orders pk dup
select count(*),count(distinct order_id),count(distinct customer_id) from orders;
-- cust
select count(*),count(distinct customer_id),count(distinct customer_unique_id) from cust;
-- items pk
select count(*),count(distinct order_id),count(distinct order_id||'|'||order_item_id),count(distinct product_id),count(distinct seller_id) from items;
-- pay pk
select count(*),count(distinct order_id),count(distinct order_id||'|'||payment_sequential) from pay;
-- rev
select count(*),count(distinct review_id),count(distinct order_id),count(distinct review_id||'|'||order_id) from rev;
-- prod/sel
select count(*),count(distinct product_id) from prod;
select count(*),count(distinct seller_id) from sel;
-- status
select order_status,count(*) from orders group by 1 order by 2 desc;
-- orders w/o items
select count(*) from orders where order_id not in (select order_id from items);
select order_status,count(*) from orders where order_id not in (select order_id from items) group by 1;
-- orders w/o pay
select count(*) from orders where order_id not in (select order_id from pay);
select order_status,count(*) from orders where order_id not in (select order_id from pay) group by 1;
-- orders w/o reviews
select count(*) from orders where order_id not in (select order_id from rev);
-- orphans
select count(*) from items where order_id not in (select order_id from orders);
select count(*) from pay where order_id not in (select order_id from orders);
select count(*) from rev where order_id not in (select order_id from orders);
select count(*) from orders where customer_id not in (select customer_id from cust);
select count(*) from cust where customer_id not in (select customer_id from orders);
select count(*) from items where product_id not in (select product_id from prod);
select count(*) from items where seller_id not in (select seller_id from sel);
select count(distinct seller_id) from items;
select count(*) from sel where seller_id not in (select seller_id from items);
select count(*) from prod where product_id not in (select product_id from items);
-- orders with >1 review
select n,count(*) from (select order_id,count(*) n from rev group by 1) group by 1;
-- reviews id with >1 order
select n,count(*) from (select review_id,count(distinct order_id) n from rev group by 1) group by 1;
select count(*) from (select review_id from rev group by 1 having count(*)>1);
-- fully duplicate review rows
select count(*) from (select 1 from rev group by review_id,order_id,review_score,review_comment_title,review_comment_message,review_creation_date,review_answer_timestamp having count(*)>1);
-- items per order
select n,count(*) from (select order_id,count(*) n from items group by 1) group by 1 order by 1 limit 25;
select max(cast(order_item_id as int)) from items;
-- sellers per order
select n,count(*) from (select order_id,count(distinct seller_id) n from items group by 1) group by 1;
-- items dup same product in order
select count(*) from (select order_id,product_id,seller_id from items group by 1,2,3 having count(*)>1);
-- pay per order
select n,count(*) from (select order_id,count(*) n from pay group by 1) group by 1 order by 1 limit 12;
-- customers with >1 order, unique ids
select n,count(*) from (select customer_unique_id,count(*) n from cust group by 1) group by 1 order by 1;
