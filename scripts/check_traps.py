"""Run one SQL check per data trap (as numbered in the README) and write reports/data_traps.md.

Every number in the report comes from a query run here, on a read-only connection.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ask_olist.config import DB_PATH  # noqa: E402

REPORT = ROOT / "reports" / "data_traps.md"

# (title, what the trap is, [(label, sql), ...])
TRAPS = [
    (
        "1. Fan trap (items x payments)",
        "`orders -> order_items` and `orders -> order_payments` are both one-to-many. "
        "Joining both on `order_id` multiplies rows, so sums get inflated.",
        [
            (
                "Orders with more than one item row / more than one payment row",
                """
                SELECT
                  (SELECT COUNT(*) FROM (SELECT order_id FROM order_items GROUP BY order_id HAVING COUNT(*) > 1)) AS orders_with_multi_items,
                  (SELECT COUNT(*) FROM (SELECT order_id FROM order_payments GROUP BY order_id HAVING COUNT(*) > 1)) AS orders_with_multi_payments,
                  (SELECT COUNT(*) FROM (
                      SELECT i.order_id FROM order_items i GROUP BY i.order_id HAVING COUNT(*) > 1
                      INTERSECT
                      SELECT p.order_id FROM order_payments p GROUP BY p.order_id HAVING COUNT(*) > 1)) AS orders_with_both
                """,
            ),
            (
                "WRONG: SUM(price) after joining items and payments directly (delivered orders)",
                """
                SELECT ROUND(SUM(i.price), 2) AS inflated_product_revenue
                FROM orders o
                JOIN order_items i ON i.order_id = o.order_id
                JOIN order_payments p ON p.order_id = o.order_id
                WHERE o.order_status = 'delivered'
                """,
            ),
            (
                "RIGHT: SUM(price) from order_items alone (delivered orders)",
                """
                SELECT ROUND(SUM(i.price), 2) AS product_revenue
                FROM orders o
                JOIN order_items i ON i.order_id = o.order_id
                WHERE o.order_status = 'delivered'
                """,
            ),
            (
                "RIGHT (with the fix): each child table aggregated to order level in a CTE first",
                """
                WITH items AS (SELECT order_id, SUM(price) AS item_total FROM order_items GROUP BY order_id),
                     pays  AS (SELECT order_id, SUM(payment_value) AS pay_total FROM order_payments GROUP BY order_id)
                SELECT ROUND(SUM(items.item_total), 2) AS product_revenue,
                       ROUND(SUM(pays.pay_total), 2)   AS payment_total
                FROM orders o
                JOIN items ON items.order_id = o.order_id
                JOIN pays  ON pays.order_id  = o.order_id
                WHERE o.order_status = 'delivered'
                """,
            ),
            (
                "Why the two 'RIGHT' totals differ: delivered orders that have items but no payment row "
                "(the inner join to payments drops them)",
                """
                SELECT COUNT(*) AS delivered_orders_without_payment,
                       ROUND(SUM(it.item_total), 2) AS their_product_revenue
                FROM orders o
                JOIN (SELECT order_id, SUM(price) AS item_total FROM order_items GROUP BY order_id) it
                  ON it.order_id = o.order_id
                WHERE o.order_status = 'delivered'
                  AND NOT EXISTS (SELECT 1 FROM order_payments p WHERE p.order_id = o.order_id)
                """,
            ),
        ],
    ),
    (
        "2. customer_id vs customer_unique_id",
        "`customer_id` is new for every order; the real person is `customer_unique_id`.",
        [
            (
                "Distinct ids vs rows",
                """
                SELECT COUNT(*) AS customer_rows,
                       COUNT(DISTINCT customer_id) AS distinct_customer_id,
                       COUNT(DISTINCT customer_unique_id) AS distinct_customer_unique_id
                FROM customers
                """,
            ),
            (
                "Repeat customers: by customer_id (always 0) vs by customer_unique_id",
                """
                SELECT
                  (SELECT COUNT(*) FROM (SELECT customer_id FROM orders GROUP BY customer_id HAVING COUNT(*) > 1)) AS repeat_by_customer_id,
                  (SELECT COUNT(*) FROM (
                      SELECT c.customer_unique_id FROM orders o JOIN customers c ON c.customer_id = o.customer_id
                      GROUP BY c.customer_unique_id HAVING COUNT(*) > 1)) AS repeat_by_customer_unique_id
                """,
            ),
        ],
    ),
    (
        "3. Revenue definition",
        "Product revenue = `SUM(price)`; with freight = `SUM(price + freight_value)`; payments use `payment_value`. "
        "The three numbers differ, so the answer must say which one it used.",
        [
            (
                "Three revenue definitions on delivered orders",
                """
                WITH items AS (SELECT order_id, SUM(price) AS price_sum, SUM(freight_value) AS freight_sum
                               FROM order_items GROUP BY order_id),
                     pays  AS (SELECT order_id, SUM(payment_value) AS pay_sum FROM order_payments GROUP BY order_id)
                SELECT ROUND(SUM(items.price_sum), 2) AS sum_price,
                       ROUND(SUM(items.price_sum + items.freight_sum), 2) AS sum_price_plus_freight,
                       ROUND(SUM(pays.pay_sum), 2) AS sum_payment_value
                FROM orders o
                JOIN items ON items.order_id = o.order_id
                JOIN pays  ON pays.order_id  = o.order_id
                WHERE o.order_status = 'delivered'
                """,
            ),
        ],
    ),
    (
        "4. Order status",
        "Many orders are not delivered (canceled, unavailable, ...). Revenue questions default to `delivered`.",
        [
            (
                "Orders per status",
                """
                SELECT order_status, COUNT(*) AS orders,
                       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM orders), 2) AS pct
                FROM orders GROUP BY order_status ORDER BY orders DESC
                """,
            ),
            (
                "Item revenue by status (non-delivered orders also carry items)",
                """
                SELECT o.order_status, ROUND(SUM(i.price), 2) AS sum_price
                FROM orders o JOIN order_items i ON i.order_id = o.order_id
                GROUP BY o.order_status ORDER BY sum_price DESC
                """,
            ),
        ],
    ),
    (
        "5. Late delivery",
        "Late = `order_delivered_customer_date > order_estimated_delivery_date`, both not null. "
        "**Rule: late-delivery questions also filter `order_status = 'delivered'`**, because some canceled "
        "orders carry a delivered date (see the first table below).",
        [
            (
                "Late orders by status: without the status filter, non-delivered orders can be counted as late",
                """
                SELECT order_status, COUNT(*) AS late_orders
                FROM orders
                WHERE order_delivered_customer_date IS NOT NULL
                  AND order_estimated_delivery_date IS NOT NULL
                  AND order_delivered_customer_date > order_estimated_delivery_date
                GROUP BY order_status ORDER BY late_orders DESC
                """,
            ),
            (
                "Delivered date is NULL for which statuses?",
                """
                SELECT order_status,
                       SUM(order_delivered_customer_date IS NULL) AS null_delivered_date,
                       SUM(order_delivered_customer_date IS NOT NULL) AS has_delivered_date
                FROM orders GROUP BY order_status ORDER BY null_delivered_date DESC
                """,
            ),
            (
                "Late vs on-time vs not comparable",
                """
                SELECT
                  SUM(order_delivered_customer_date > order_estimated_delivery_date) AS late,
                  SUM(order_delivered_customer_date <= order_estimated_delivery_date) AS on_time,
                  SUM(order_delivered_customer_date IS NULL OR order_estimated_delivery_date IS NULL) AS not_comparable
                FROM orders
                """,
            ),
        ],
    ),
    (
        "6. Category names are Portuguese",
        "`products.product_category_name` is Portuguese; `category_translation` gives English.",
        [
            (
                "Sample of Portuguese vs English names",
                """
                SELECT product_category_name, product_category_name_english
                FROM category_translation ORDER BY product_category_name LIMIT 5
                """,
            ),
            (
                "Products with no category, or a category missing from the translation table",
                """
                SELECT
                  SUM(p.product_category_name IS NULL) AS null_category,
                  SUM(p.product_category_name IS NOT NULL AND t.product_category_name IS NULL) AS category_without_translation
                FROM products p
                LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
                """,
            ),
            (
                "Which untranslated category names exist (with product counts)",
                """
                SELECT p.product_category_name, COUNT(*) AS products
                FROM products p
                LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
                WHERE p.product_category_name IS NOT NULL AND t.product_category_name IS NULL
                GROUP BY p.product_category_name
                """,
            ),
        ],
    ),
    (
        "7. geolocation has many rows per zip prefix",
        "Joining it directly multiplies rows.",
        [
            (
                "Rows vs distinct zip prefixes",
                """
                SELECT COUNT(*) AS rows_, COUNT(DISTINCT geolocation_zip_code_prefix) AS distinct_zip_prefixes,
                       ROUND(1.0 * COUNT(*) / COUNT(DISTINCT geolocation_zip_code_prefix), 1) AS avg_rows_per_zip
                FROM geolocation
                """,
            ),
            (
                "Join inflation: customers rows vs customers JOIN geolocation rows",
                """
                SELECT (SELECT COUNT(*) FROM customers) AS customers_rows,
                       (SELECT COUNT(*) FROM customers c
                        JOIN geolocation g ON g.geolocation_zip_code_prefix = c.customer_zip_code_prefix) AS rows_after_join
                """,
            ),
        ],
    ),
    (
        "8. order_reviews: more than one review per order",
        "Some orders have several reviews; averaging raw review rows over-weights them. "
        "**Rule: average per order first.** The overall average barely moves, but the rule matters most for "
        "per-seller and per-category averages (see the last table).",
        [
            (
                "Orders with more than one review; duplicated review_id values",
                """
                SELECT
                  (SELECT COUNT(*) FROM (SELECT order_id FROM order_reviews GROUP BY order_id HAVING COUNT(*) > 1)) AS orders_with_multi_reviews,
                  (SELECT COUNT(*) FROM (SELECT review_id FROM order_reviews GROUP BY review_id HAVING COUNT(*) > 1)) AS review_ids_used_more_than_once,
                  (SELECT COUNT(*) FROM order_reviews) AS review_rows,
                  (SELECT COUNT(DISTINCT order_id) FROM order_reviews) AS distinct_orders_reviewed
                """,
            ),
            (
                "Average score: over review rows vs per order (average within order first)",
                """
                SELECT
                  (SELECT ROUND(AVG(review_score), 4) FROM order_reviews) AS avg_over_review_rows,
                  (SELECT ROUND(AVG(s), 4) FROM (SELECT AVG(review_score) AS s FROM order_reviews GROUP BY order_id)) AS avg_per_order
                """,
            ),
            (
                "Per-seller average score: raw review rows vs per-order-first (sellers with at least 1 review)",
                """
                WITH seller_orders AS (SELECT DISTINCT order_id, seller_id FROM order_items),
                     per_order AS (SELECT order_id, AVG(review_score) AS s FROM order_reviews GROUP BY order_id),
                     raw AS (SELECT so.seller_id, AVG(r.review_score) AS avg_raw
                             FROM seller_orders so JOIN order_reviews r ON r.order_id = so.order_id
                             GROUP BY so.seller_id),
                     fixed AS (SELECT so.seller_id, AVG(po.s) AS avg_fixed
                               FROM seller_orders so JOIN per_order po ON po.order_id = so.order_id
                               GROUP BY so.seller_id)
                SELECT COUNT(*) AS sellers,
                       SUM(ABS(raw.avg_raw - fixed.avg_fixed) > 0.0001) AS sellers_where_avg_differs,
                       ROUND(MAX(ABS(raw.avg_raw - fixed.avg_fixed)), 4) AS max_difference
                FROM raw JOIN fixed ON fixed.seller_id = raw.seller_id
                """,
            ),
        ],
    ),
]


def run(con: sqlite3.Connection, sql: str) -> tuple[list[str], list[tuple]]:
    cur = con.execute(sql)
    return [d[0] for d in cur.description], cur.fetchall()


def md_table(cols: list[str], rows: list[tuple]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        out.append("| " + " | ".join(f"{v:,}" if isinstance(v, int) else str(v) for v in r) + " |")
    return "\n".join(out)


def clean(sql: str) -> str:
    lines = [ln[16:] if ln.startswith(" " * 16) else ln.strip() for ln in sql.strip("\n").splitlines()]
    return "\n".join(lines).strip()


def main() -> None:
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    out = [
        "# Data traps: SQL evidence",
        "",
        "Generated by `scripts/check_traps.py` on `data/olist.db`. Every number below comes from the query shown.",
        "",
    ]
    for title, claim, checks in TRAPS:
        out += [f"## {title}", "", claim, ""]
        for label, sql in checks:
            cols, rows = run(con, sql)
            out += [f"**{label}**", "", "```sql", clean(sql), "```", "", md_table(cols, rows), ""]
    REPORT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
