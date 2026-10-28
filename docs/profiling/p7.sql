-- seller state invalid
select count(*) from sel where seller_state not in ('AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO');
select count(*) from cust where customer_state not in ('AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO');
select count(*) from sel where seller_city like '%paulo%';
select count(distinct seller_city) from sel where seller_city like '%paulo%';
select seller_city,count(*) from sel where seller_city like '%paulo%' group by 1 order by 2 desc limit 8;
select count(*) from sel where seller_city like '%/%' or seller_city like '% - %' or seller_city like '%,%' or seller_city glob '*[0-9]*' or seller_city glob '*@*';
-- reviews
select review_score,count(*) from rev group by 1 order by 1;
select sum(review_comment_title=''),sum(review_comment_message=''),sum(review_creation_date=''),sum(review_answer_timestamp='') from rev;
select length(review_creation_date),length(review_answer_timestamp),count(*) from rev group by 1,2;
select min(review_creation_date),max(review_creation_date),min(review_answer_timestamp),max(review_answer_timestamp) from rev;
select count(*) from rev where review_answer_timestamp<review_creation_date;
select count(*) from rev r join orders o using(order_id) where r.review_creation_date<substr(o.order_purchase_timestamp,1,10);
select count(*) from rev r join orders o using(order_id) where o.order_delivered_customer_date<>'' and r.review_creation_date<substr(o.order_delivered_customer_date,1,10);
select count(*) from rev r join orders o using(order_id) where o.order_delivered_customer_date='' ;
select o.order_status,count(*) from rev r join orders o using(order_id) group by 1 order by 2 desc;
-- multi-review orders: different scores?
select count(*) from (select order_id from rev group by 1 having count(*)>1 and count(distinct review_score)>1);
-- review ids shared across orders: same score?
select count(*) from (select review_id from rev group by 1 having count(*)>1 and count(distinct order_id)>1 and count(distinct review_score)>1);
-- delivered orders w/o review
select order_status,count(*) from orders where order_id not in (select order_id from rev) group by 1 order by 2 desc limit 4;
-- delivered w/o pay
select order_id,order_status from orders where order_id not in (select order_id from pay);
select count(*) from items where order_id in (select order_id from orders where order_id not in (select order_id from pay));
-- orders purchase vs approved gap, items rows: multi-seller orders
-- orders status shipped/unavail sums
select order_status,count(*),round(sum(cast(price as real)),2) from orders join items using(order_id) group by 1;
-- delivered order with null approved
select count(*) from orders where order_status='delivered' and order_approved_at='' and order_delivered_carrier_date<>'';
-- delivered_customer null while delivered: statuses
select count(*) from orders where order_delivered_customer_date<>'' and order_delivered_carrier_date='' ;
-- 2020 shipping dates
select count(*) from items where shipping_limit_date>='2019';
-- freight zero
select count(*) from items where cast(freight_value as real)=0;
-- 2018-09/10 orders
select order_status,substr(order_purchase_timestamp,1,7),count(*) from orders where order_purchase_timestamp>='2018-09' or order_purchase_timestamp<'2016-10' group by 1,2;
-- orders w/ items out of period 2016-12
select o.order_status, count(*) from orders o where order_purchase_timestamp like '2016-12%' group by 1;
