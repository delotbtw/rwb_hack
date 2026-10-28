-- rev by month purchase (delivered, price)
select substr(o.order_purchase_timestamp,1,7) m,count(distinct o.order_id),round(sum(cast(price as real)),2) from items i join orders o using(order_id) where order_status='delivered' group by 1 order by 1 limit 6;
-- by delivered month: range & sums
select count(distinct substr(o.order_delivered_customer_date,1,7)),min(substr(o.order_delivered_customer_date,1,7)),max(substr(o.order_delivered_customer_date,1,7)) from orders o where order_status='delivered' and order_delivered_customer_date<>'';
-- top sellers
select s.seller_id,s.seller_city,s.seller_state,count(distinct i.order_id),count(*),round(sum(cast(price as real)),2) from items i join orders o using(order_id) join sel s using(seller_id) where order_status='delivered' group by 1 order by 6 desc limit 10;
-- top seller if order-level amount used (wrong)
select i.seller_id,round(sum(t.tot),2) from (select distinct order_id,seller_id from items) i join (select order_id,sum(cast(price as real)) tot from items group by 1) t using(order_id) join orders o using(order_id) where order_status='delivered' group by 1 order by 2 desc limit 2;
-- avg check
select round(avg(t),2),round(avg(n),4),count(*) from (select order_id,sum(cast(price as real)) t,count(*) n from items join orders using(order_id) where order_status='delivered' group by 1);
select round(avg(cast(price as real)),2),round(avg(cast(price as real)+cast(freight_value as real)),2) from items join orders using(order_id) where order_status='delivered';
select round(avg(cast(price as real)),2),round(avg(cast(price as real)+cast(freight_value as real)),2) from items;
select round(avg(t+f),2) from (select order_id,sum(cast(price as real)) t,sum(cast(freight_value as real)) f from items join orders using(order_id) where order_status='delivered' group by 1);
select round(sum(cast(price as real))/count(distinct order_id),2) from items;
-- buyers
select count(distinct c.customer_unique_id) from orders o join cust c using(customer_id) where order_status='delivered';
select count(*),sum(n>1),round(100.0*sum(n>1)/count(*),4) from (select c.customer_unique_id,count(distinct o.order_id) n from orders o join cust c using(customer_id) group by 1);
select count(*),sum(n>1),round(100.0*sum(n>1)/count(*),4) from (select c.customer_unique_id,count(distinct o.order_id) n from orders o join cust c using(customer_id) where order_status='delivered' group by 1);
select count(*),sum(n>1),round(100.0*sum(n>1)/count(*),4) from (select c.customer_unique_id,count(distinct o.order_id) n from orders o join cust c using(customer_id) where order_id in (select order_id from items) group by 1);
select count(*),sum(n>1),round(100.0*sum(n>1)/count(*),4) from (select c.customer_unique_id,count(distinct o.order_id) n from orders o join cust c using(customer_id) where order_status not in ('canceled','unavailable') group by 1);
-- customer_id->unique: do customer_id repeat per orders? 
select count(*) from (select customer_id from orders group by 1 having count(*)>1);
-- same unique id in diff zip/city/state
select count(*) from (select customer_unique_id from cust group by 1 having count(distinct customer_zip_code_prefix||customer_city||customer_state)>1);
select count(*) from (select customer_unique_id from cust group by 1 having count(distinct customer_state)>1);
-- repeat orders same unique at same timestamp?
select count(*) from (select c.customer_unique_id,o.order_purchase_timestamp from orders o join cust c using(customer_id) group by 1,2 having count(*)>1);
