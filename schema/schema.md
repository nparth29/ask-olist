# Olist e-commerce database (SQLite)

Brazilian marketplace data, about 100k orders placed between 2016-09-04 and 2018-10-17. Amounts are in Brazilian reais (BRL).
All timestamps are text in the form `YYYY-MM-DD HH:MM:SS`. Use `strftime(...)` and `julianday(...)` for dates.
Never use `date('now')`: the data is historical, so "this year" means a year in the data.

## Tables

### orders  (one row per order)
- `order_id` (PK)
- `customer_id` -> customers.customer_id (new id for every order, see rule 2)
- `order_status`: delivered, shipped, canceled, unavailable, invoiced, processing, created, approved
- `order_purchase_timestamp`: when the order was placed
- `order_approved_at`: payment approved
- `order_delivered_carrier_date`: handed to the carrier
- `order_delivered_customer_date`: received by the customer (NULL if not delivered)
- `order_estimated_delivery_date`: delivery date promised to the customer

### order_items  (one row per item in an order; an order has 1 or more)
- `order_id` -> orders.order_id
- `order_item_id`: 1, 2, 3 ... position of the item within the order
- `product_id` -> products.product_id
- `seller_id` -> sellers.seller_id
- `shipping_limit_date`: seller's deadline to hand the item to the carrier
- `price` (REAL): item price, without freight
- `freight_value` (REAL): shipping cost for this item

### order_payments  (one row per payment; an order has 1 or more)
- `order_id` -> orders.order_id
- `payment_sequential`: 1, 2, 3 ... when an order is paid in several payments
- `payment_type`: credit_card, boleto, voucher, debit_card, not_defined
- `payment_installments`: number of installments
- `payment_value` (REAL): amount of this payment, including freight

### order_reviews  (customer reviews; an order can have more than one)
- `review_id`, `order_id` -> orders.order_id
- `review_score` (INTEGER): 1 (worst) to 5 (best)
- `review_comment_title`, `review_comment_message`: free text, often NULL
- `review_creation_date`, `review_answer_timestamp`

### customers  (one row per customer_id, so one per order)
- `customer_id` (PK) -> joins to orders.customer_id
- `customer_unique_id`: the real person, the same across that person's orders
- `customer_zip_code_prefix` (TEXT), `customer_city`, `customer_state` (2-letter code, e.g. SP, RJ, MG)

### sellers
- `seller_id` (PK), `seller_zip_code_prefix` (TEXT), `seller_city`, `seller_state` (2-letter code)

### products
- `product_id` (PK)
- `product_category_name`: category in Portuguese (NULL for some products)
- `product_name_lenght`, `product_description_lenght`: sic, spelled "lenght" in the data
- `product_photos_qty`
- `product_weight_g`, `product_length_cm`, `product_height_cm`, `product_width_cm`

### category_translation  (71 rows)
- `product_category_name` (Portuguese) -> `product_category_name_english`

### geolocation  (about 1 million rows, many per zip prefix)
- `geolocation_zip_code_prefix` (TEXT), `geolocation_lat`, `geolocation_lng`, `geolocation_city`, `geolocation_state`

## Join keys

- orders.customer_id = customers.customer_id
- order_items.order_id = orders.order_id
- order_items.product_id = products.product_id
- order_items.seller_id = sellers.seller_id
- order_payments.order_id = orders.order_id
- order_reviews.order_id = orders.order_id
- products.product_category_name = category_translation.product_category_name

## Data-trap rules (always follow)

1. **Fan trap.** orders -> order_items and orders -> order_payments are both one-to-many. Joining both onto orders
   multiplies rows and inflates totals. Aggregate each child table to order level in a CTE
   (`SELECT order_id, SUM(...) ... GROUP BY order_id`) before joining them together. If a question needs only
   one child table, just join that one.
2. **Customers.** `customer_id` is new for every order. The real person is `customer_unique_id`. Count customers,
   repeat customers and "customers who ordered more than once" with `COUNT(DISTINCT customer_unique_id)`.
3. **Revenue.** Product revenue = `SUM(order_items.price)`. Add `freight_value` only if the question says
   "including shipping/freight". Payment questions (payment types, installments, amount paid) use
   `order_payments.payment_value`. State which definition you used in `assumptions`.
4. **Order status.** Sales and revenue questions use `order_status = 'delivered'` unless the question says
   otherwise. State this in `assumptions`.
5. **Late delivery.** Late = `order_delivered_customer_date > order_estimated_delivery_date`, both NOT NULL, and
   `order_status = 'delivered'` (a few canceled orders have a delivered date and must not be counted).
   Delivery days = `julianday(order_delivered_customer_date) - julianday(order_purchase_timestamp)`.
6. **Category names are Portuguese.** For English names, `LEFT JOIN category_translation` and use
   `COALESCE(t.product_category_name_english, p.product_category_name)`. Some products have no category (NULL)
   and 2 categories have no translation.
7. **geolocation.** Never join it directly (many rows per zip prefix). Avoid it; customers and sellers already
   have city and state. If you must use it, aggregate it to one row per zip prefix first.
8. **Reviews.** Some orders have more than one review. Average review scores per order first
   (`SELECT order_id, AVG(review_score) AS score FROM order_reviews GROUP BY order_id`), then aggregate that.
   Join reviews to items only through a per-order result, never row by row.

## SQL dialect notes (SQLite)

- Year: `strftime('%Y', order_purchase_timestamp)` (text, so compare with `'2018'`). Month: `strftime('%Y-%m', ...)`.
- Use only `SELECT` (optionally starting with `WITH`). No other statements.
- SQLite has no `DATEDIFF`; use `julianday(a) - julianday(b)` for days.
- Round money to 2 decimals with `ROUND(x, 2)`.
