# Ask-Olist

Parth Mishra · github.com/nparth29

Ask a data question in plain English. Ask-Olist writes a **safe** SQL query on the Olist e-commerce database, runs it, and answers in plain English, showing the SQL it used.

> **Status:** work in progress. The text-to-SQL pipeline, the safety guard, the self-correction loop, the RAG retrieval, the FastAPI endpoint and the Streamlit demo are built and tested. The accuracy evaluation and the Docker image are not done yet, so this README has **no accuracy numbers**. They will be added from `reports/` once the evaluation has run.

## The problem

Business users have data questions but cannot write SQL. A general chatbot that guesses SQL is risky on this dataset: several well-known traps (below) silently produce wrong totals. Ask-Olist gives the model the schema, the trap rules and similar verified examples, checks every query before it runs, and only lets the answer use numbers that are in the result rows.

It handles counts, sums, averages, top-N, monthly trends, and comparisons by state, category or seller, as well as delivery delays and review scores.

## One example

**Question:** "Which 5 customer states have the most late deliveries?"

The app shows the SQL, the result and a short answer. This is the verified example SQL for that question and its result, from `reports/examples_check.md`:

```sql
SELECT c.customer_state, COUNT(*) AS late_orders
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_estimated_delivery_date IS NOT NULL
  AND o.order_delivered_customer_date > o.order_estimated_delivery_date
GROUP BY c.customer_state
ORDER BY late_orders DESC
LIMIT 5
```

| customer_state | late_orders |
|---|---|
| SP | 2387 |
| RJ | 1664 |
| MG | 637 |
| BA | 457 |
| RS | 382 |

An answer written from these rows would read like: "SP had the most late deliveries (2,387), followed by RJ (1,664), MG (637), BA (457) and RS (382). Only delivered orders were counted."

## How it works

```text
question
  -> retrieve top-3 similar verified examples (Gemini embeddings + FAISS)          <- RAG
  -> build prompt: schema doc + data-trap rules + examples + question
       (prompts/sql_v*.txt, versioned; new wording = new version = new cache key)
  -> Gemini -> structured JSON {sql, assumptions}
  -> guard: parse with sqlglot; exactly one statement; SELECT / WITH only;
           no PRAGMA, ATTACH, DDL or DML
  -> run on a read-only connection (file:data/olist.db?mode=ro, PRAGMA query_only=ON),
           row cap 1000, 10-second timeout
  -> if error or guard rejection: send SQL + error back to Gemini to fix (max 2 retries)   <- agent loop
  -> second Gemini call writes the plain-English answer using ONLY numbers from the
           result rows (prompts/answer_v1.txt)                                    <- hallucination control
  -> return {answer, sql, assumptions, rows (first 20), attempts,
            retrieved_example_ids, latency_s}
```

Every attempt is logged to `logs/runs.jsonl`. Every LLM and embedding call is cached on disk, so a repeated question makes no API calls. The pipeline is plain Python, with no LangChain or LlamaIndex, so each step is easy to read (see `DECISIONS.md`).

**Safety.** An LLM must never be trusted to run `DELETE`. The guard rejects anything that is not a single `SELECT`, and the query then runs on a read-only SQLite connection, so even a guard bug cannot write. The app never writes to the database.

## The data traps

These are real mistakes on this dataset. They are written into the schema document (`schema/schema.md`) as rules the model must follow, and the SQL evidence for each is in [`reports/data_traps.md`](reports/data_traps.md).

1. **Fan trap.** `orders -> order_items` and `orders -> order_payments` are both one-to-many. Joining both multiplies rows. On delivered orders, joining items and payments directly gives a product revenue of 13,813,828.71, instead of the correct 13,221,498.11. *Rule:* aggregate each child table to order level in a CTE before joining.
2. **`customer_id` vs `customer_unique_id`.** There are 99,441 `customer_id` values but only 96,096 real people. *Rule:* count customers by `customer_unique_id`.
3. **Revenue definition.** On delivered orders the three common definitions give 13,221,363.14 (`SUM(price)`), 15,419,630.29 (price plus freight) and 15,422,461.77 (`SUM(payment_value)`). *Rule:* product revenue is `SUM(price)`, freight only if the question says so, and the answer states which one was used.
4. **Order status.** 97.02% of orders are delivered, but other statuses still carry items. *Rule:* sales and revenue questions default to `delivered`, and the answer states the assumption.
5. **Late delivery.** *Rule:* delivered date later than estimated date, both not null, and `order_status = 'delivered'`. Without the status filter, a canceled order is counted as late.
6. **Portuguese category names.** *Rule:* join `category_translation` for English names. 610 products have no category and 13 have a category with no translation, so the join must be a `LEFT JOIN`.
7. **`geolocation`.** It has 1,000,163 rows for 19,015 zip prefixes; joining it to customers turns 99,441 rows into 15,083,455. *Rule:* never join it directly; aggregate first or avoid it.
8. **Several reviews per order.** 547 orders have more than one review. *Rule:* average per order first. The overall average hardly moves, but 234 of 3,090 sellers get a different average without this rule.

## How to run

You need Windows, Python 3.12 or newer, and a free [Google AI Studio](https://aistudio.google.com/) API key.

**1. Get the code and install**

```powershell
git clone <this repo's URL>
cd ask-olist
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

**2. Add your key.** Copy `.env.example` to `.env` and set `GEMINI_API_KEY=` to your key. The `.env` file is git-ignored.

**3. Download the data.** The dataset is not in this repo (licence: CC BY-NC-SA 4.0). Download "Brazilian E-Commerce Public Dataset by Olist" (`olistbr/brazilian-ecommerce`) from Kaggle, and put the 9 CSV files in `data\raw\`.

**4. Build the database and the example index**

```powershell
python scripts\build_db.py        # CSVs -> data\olist.db, plus reports\db_summary.md
python scripts\build_index.py     # embeds the verified examples -> data\index\
```

**5. Ask a question**

```powershell
python -m ask_olist "Which 5 product categories had the most late deliveries in 2018?"
python -m ask_olist --no-rag "Which 5 product categories had the most late deliveries in 2018?"   # zero-shot, for comparison
```

**6. Or start the API**

```powershell
uvicorn api.main:app --port 8000
```

`GET /health` checks that the database and the example index exist. `POST /ask` takes `{"question": "...", "use_rag": true}` and returns the answer, SQL, assumptions, the first 20 rows, attempts, retrieved example ids and latency. If the model is unavailable (for example the free-tier quota) it returns HTTP 503 with a message.

**7. Or open the demo app**

```powershell
streamlit run app\streamlit_app.py
```

It opens in your browser. Type a question (or click a sample), and it shows the answer, the assumptions, the SQL (in an expander), the result table, the retrieved examples with similarity scores, and the number of attempts. A sidebar switch turns RAG off for a zero-shot comparison.

**8. Run the tests** (no API key or network needed; the LLM is mocked)

```powershell
python -m pytest
```

Other scripts: `python -m ask_olist.smoke` checks the key and lists the available Flash models; `python scripts\check_traps.py` regenerates the trap evidence; `python scripts\check_examples.py` runs every example query locally; `python scripts\check_gold.py` runs the gold SQL of the evaluation questions locally.

## Project layout

```text
prompts/     versioned prompts: sql_v1 (zero-shot), sql_v2 (RAG), fix_v1 (retry), answer_v1
schema/      schema.md: the tables, join keys and trap rules the model reads
examples/    30 verified question -> SQL pairs used for retrieval
eval/        30 evaluation questions with gold SQL (separate from the examples; being verified)
src/ask_olist/   config, cache, llm, db, guard, retrieval, pipeline, CLI
api/         FastAPI app: POST /ask, GET /health
app/         Streamlit demo
scripts/     build_db, build_index, check_traps, check_examples
tests/       guard, read-only connection, retry loop (mocked), retrieval, cache
reports/     generated evidence (db summary, data traps, example check)
DECISIONS.md every design choice, with the main alternative and why
```

## What didn't work

These are real problems from building it. Each one is logged in `DECISIONS.md` with the details.

1. **The newest Flash models were unusable.** On the day I picked the model, the three newest Gemini Flash models (3.6, 3.7 and 3.8) timed out or returned "503: high demand". I used `gemini-3.5-flash` instead, which worked but was slow. The retry code now also retries 503 and 504 errors (not only 429), because they are just as temporary. The model name lives only in `config.py`, so switching later is a one-line change. (D1, D11)
2. **A lower "thinking" level looked faster but changed an answer, so I rejected it.** I tested `thinking_level=low` on 4 sample questions (the 5th could not run when the free-tier daily limit ran out). 3 of the 4 gave the same values, but the repeat-customer question changed from 2,997 customers to 2,801, because `low` added a `delivered` filter the question never asked for. That misapplies the rule that the delivered default is for sales questions, and my rule was to keep `low` only if every answer matched. I did not measure a speed gain: the first-run timings were mixed up with overload retries, so I make no latency claim. Evidence: [`reports/thinking_level_test.md`](reports/thinking_level_test.md). I kept the model's default thinking. (D13)
3. **A simple query hit the 10-second limit.** "Top 10 sellers by product revenue" timed out. The database had no table statistics, so SQLite picked a slow join plan and built a temporary index for every item row instead of using the existing `order_id` index. Running `ANALYZE` once when the database is built fixed it, and it happens at build time because the app never writes. (D17)
4. **Retrying a daily quota error is pointless.** The first retry loop backed off for about a minute on the free tier's daily-limit error, which can never succeed. It now fails immediately when Google says to wait for hours. (D14, D16)

## Limitations

- **Accuracy is not measured yet.** The evaluation on hand-verified questions (zero-shot against RAG) has not run. Until it does, treat answers as unverified and check the SQL shown.
- **Valid is not the same as right.** The guard and the read-only connection make a query *safe*, not *correct*. The model can still write a valid query that answers a slightly different question. That is why the SQL and the assumptions are always shown.
- **The answer step can still misread a table.** It is told to use only numbers from the result rows, but an LLM can still word things badly. Compare it with the table.
- **Defaults are assumptions.** Sales questions default to delivered orders; "customers" means unique people. Both are stated in the assumptions, but they may not be what a user meant.
- **Small example set.** Retrieval draws on 30 examples, so unusual question types get less help.
- **Free-tier limits.** The project uses the Gemini free tier, which has a small daily request limit and sometimes returns overload errors. Calls are cached and retried, but heavy use can still be blocked for hours. Free-tier prompts may be used by Google to improve its products; this dataset is public, so that is acceptable here.
- **English questions only,** one question at a time (no chat memory), no charts, and one fixed historical dataset (2016-2018). Results are capped at 1,000 rows and queries at 10 seconds.
- **Not built yet:** the evaluation and the Docker image.

## Data and licence

Data: Olist, "Brazilian E-Commerce Public Dataset" (Kaggle), licence CC BY-NC-SA 4.0. The CSVs and the database are not committed to this repo.
