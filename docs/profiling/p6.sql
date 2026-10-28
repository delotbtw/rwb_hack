-- products category
select count(*),sum(product_category_name=''),count(distinct product_category_name) from prod;
select count(*) from tr;
select count(distinct product_category_name) from tr;
-- categories in prod not in tr
select p.product_category_name,count(*) from prod p where p.product_category_name<>'' and p.product_category_name not in (select product_category_name from tr) group by 1;
-- categories in tr without products
select product_category_name from tr where product_category_name not in (select product_category_name from prod);
-- categories in items(delivered) 
select count(distinct p.product_category_name), sum(p.product_category_name='') from items i join orders o using(order_id) join prod p using(product_id) where o.order_status='delivered';
select count(distinct p.product_category_name) from items i join prod p using(product_id) ;
select count(distinct p.product_category_name) from items i join orders o using(order_id) join prod p using(product_id) where o.order_status='delivered' and p.product_category_name<>'';
-- rev by cat
select p.product_category_name,round(sum(cast(price as real)),2) from items i join orders o using(order_id) join prod p using(product_id) where o.order_status='delivered' group by 1 order by 2 desc limit 3;
select round(sum(cast(price as real)),2),count(*) from items i join orders o using(order_id) join prod p using(product_id) where o.order_status='delivered' and p.product_category_name='';
select count(*) from (select 1 from items i join orders o using(order_id) join prod p using(product_id) where o.order_status='delivered' group by p.product_category_name);
-- inner join with translation loses
select round(sum(cast(price as real)),2) from items i join orders o using(order_id) join prod p using(product_id) join tr t on t.product_category_name=p.product_category_name where o.order_status='delivered';
-- english dupes in tr
select count(distinct product_category_name_english) from tr;
select * from tr where product_category_name<>lower(trim(product_category_name)) or product_category_name_english<>lower(trim(product_category_name_english)) limit 5;
-- products numerics
select sum(product_weight_g=''),sum(product_length_cm=''),sum(product_height_cm=''),sum(product_width_cm=''),sum(product_photos_qty=''),sum(product_name_lenght=''),sum(product_description_lenght=''),sum(cast(product_weight_g as real)=0 and product_weight_g<>'') from prod;
select count(*) from prod where product_category_name='' and product_name_lenght<>'';
select count(*) from prod where product_category_name='' and product_weight_g='';
select min(cast(product_weight_g as real)),max(cast(product_weight_g as real)),min(cast(product_length_cm as real)),min(cast(product_height_cm as real)),min(cast(product_width_cm as real)) from prod where product_weight_g<>'';
select sum(product_weight_g<>'' and cast(product_weight_g as real)=0) from prod;
-- non-integer numeric formats
select product_weight_g from prod where product_weight_g like '%.%' limit 2;
-- sellers
select seller_state,count(*) from sel group by 1 order by 2 desc limit 30;
select count(distinct seller_state) from sel;
select count(distinct seller_city),count(distinct lower(trim(seller_city))) from sel;
select seller_city from sel where seller_city glob '*[^a-z ]*' limit 15;
select count(*) from sel where seller_city glob '*[^a-z ]*';
select count(*) from sel where seller_city<>lower(trim(seller_city));
select length(seller_zip_code_prefix),count(*) from sel group by 1;
select length(customer_zip_code_prefix),count(*) from cust group by 1;
select count(distinct customer_state) from cust;
select customer_state,count(*) from cust group by 1 order by 2 desc limit 30;
select count(*) from cust where customer_city glob '*[^a-z ]*';
select customer_city from cust where customer_city glob '*[^a-z ]*' limit 12;
select count(distinct customer_city),count(distinct lower(trim(customer_city))) from cust;
select count(*) from cust where customer_city<>lower(trim(customer_city));
