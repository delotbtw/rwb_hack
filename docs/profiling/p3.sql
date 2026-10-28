-- price stats
select min(cast(price as real)),max(cast(price as real)),sum(cast(price as real)<=0),min(cast(freight_value as real)),max(cast(freight_value as real)),sum(cast(freight_value as real)=0),sum(price=''),sum(freight_value='') from items;
select round(sum(cast(price as real)),2),round(sum(cast(freight_value as real)),2) from items;
-- payments
select payment_type,count(*),round(sum(cast(payment_value as real)),2),sum(cast(payment_value as real)=0),sum(cast(payment_installments as int)=0) from pay group by 1;
select count(*),sum(cast(payment_value as real)=0),sum(cast(payment_installments as int)=0),min(cast(payment_value as real)),max(cast(payment_value as real)),max(cast(payment_installments as int)),round(sum(cast(payment_value as real)),2) from pay;
select o.order_status,p.payment_type,count(*) from pay p join orders o using(order_id) where p.payment_type='not_defined' or cast(payment_value as real)=0 group by 1,2;
select payment_sequential, count(*) from pay where cast(payment_sequential as int)>20 group by 1 limit 3;
select max(cast(payment_sequential as int)) from pay;
-- order level reconciliation
create temp table it as select order_id, sum(cast(price as real)) p, sum(cast(freight_value as real)) f, count(*) n from items group by 1;
create temp table pp as select order_id, sum(cast(payment_value as real)) v, count(*) n from pay group by 1;
select count(*) from it join pp using(order_id);
select count(*), sum(abs(it.p+it.f-pp.v)>0.01), sum(abs(it.p+it.f-pp.v)>1), sum(abs(it.p+it.f-pp.v)>10) from it join pp using(order_id);
select round(sum(it.p+it.f),2), round(sum(pp.v),2), round(sum(pp.v-it.p-it.f),2) from it join pp using(order_id);
select count(*) from it join pp using(order_id) where pp.v>it.p+it.f+0.01;
select count(*) from it join pp using(order_id) where pp.v<it.p+it.f-0.01;
-- mismatch on installments
select round(min(pp.v-it.p-it.f),2),round(max(pp.v-it.p-it.f),2) from it join pp using(order_id);
-- mismatch among orders with voucher
select count(*) from it join pp using(order_id) where abs(it.p+it.f-pp.v)>0.01 and it.order_id in (select order_id from pay where payment_type='voucher');
select count(*) from it join pp using(order_id) where abs(it.p+it.f-pp.v)>0.01 and it.order_id in (select order_id from pay group by 1 having count(*)=1);
select count(*) from it join pp using(order_id) where abs(it.p+it.f-pp.v)>0.01 and it.order_id in (select order_id from pay where payment_type='credit_card' and cast(payment_installments as int)>1);
-- orders with items but status not delivered: pay sums
select count(*) from pay where order_id in (select order_id from orders where order_status in ('canceled','unavailable'));
-- payments order without items
select count(*) from pp where order_id not in (select order_id from it);
select o.order_status,count(*) from pp join orders o using(order_id) where pp.order_id not in (select order_id from it) group by 1;
