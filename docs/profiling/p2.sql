-- null/empty counts orders
select sum(order_approved_at is null),sum(order_approved_at=''),sum(order_delivered_carrier_date is null),sum(order_delivered_carrier_date=''),sum(order_delivered_customer_date is null),sum(order_delivered_customer_date=''),sum(order_estimated_delivery_date=''),sum(order_purchase_timestamp='') from orders;
-- date formats (length distribution)
select length(order_purchase_timestamp),length(order_approved_at),length(order_delivered_customer_date),length(order_estimated_delivery_date),count(*) from orders group by 1,2,3,4 order by 5 desc limit 8;
-- delivered with null delivered_customer
select count(*) from orders where order_status='delivered' and order_delivered_customer_date='';
select count(*) from orders where order_status='delivered' and order_approved_at='';
select count(*) from orders where order_status='delivered' and order_delivered_carrier_date='';
-- non-delivered with delivered date
select order_status,count(*) from orders where order_status<>'delivered' and order_delivered_customer_date<>'' group by 1;
-- shipped/canceled with carrier date
select order_status,count(*),sum(order_delivered_carrier_date<>''),sum(order_approved_at<>'') from orders group by 1;
-- anomalies
select count(*) from orders where order_delivered_customer_date<>'' and order_delivered_customer_date<order_purchase_timestamp;
select count(*) from orders where order_approved_at<>'' and order_approved_at<order_purchase_timestamp;
select count(*) from orders where order_delivered_carrier_date<>'' and order_delivered_customer_date<>'' and order_delivered_carrier_date>order_delivered_customer_date;
select count(*) from orders where order_delivered_carrier_date<>'' and order_delivered_carrier_date<order_purchase_timestamp;
select count(*) from orders where order_estimated_delivery_date<order_purchase_timestamp;
select count(*) from orders where order_approved_at<>'' and order_delivered_carrier_date<>'' and order_delivered_carrier_date<order_approved_at;
select count(*) from orders where order_delivered_customer_date<>'' and order_delivered_customer_date>order_estimated_delivery_date;
select min(order_purchase_timestamp),max(order_purchase_timestamp),min(order_delivered_customer_date),max(order_delivered_customer_date),min(order_estimated_delivery_date),max(order_estimated_delivery_date) from orders;
-- months
select substr(order_purchase_timestamp,1,7) m,count(*),sum(order_status='delivered'),sum(order_status='canceled'),sum(order_status='unavailable') from orders group by 1 order by 1;
-- trailing spaces / case in status etc
select count(*) from orders where order_status<>lower(trim(order_status));
select count(*) from orders where order_id<>trim(order_id) or customer_id<>trim(customer_id);
select count(*) from orders where length(order_id)<>32;
select length(customer_id),count(*) from cust group by 1;
-- items dates
select min(shipping_limit_date),max(shipping_limit_date),sum(shipping_limit_date=''),length(shipping_limit_date) from items group by 4;
select count(*) from items i join orders o using(order_id) where i.shipping_limit_date<o.order_purchase_timestamp;
select count(*) from items i join orders o using(order_id) where o.order_delivered_carrier_date<>'' and o.order_delivered_carrier_date>i.shipping_limit_date;
select count(*) from items i join orders o using(order_id) where substr(i.shipping_limit_date,1,4) not in ('2016','2017','2018');
select substr(shipping_limit_date,1,4),count(*) from items group by 1;
