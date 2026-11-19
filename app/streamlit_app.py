"""Streamlit demo for Ask-Olist.

Run from the project folder:   streamlit run app\\streamlit_app.py
"""
import pandas as pd
import streamlit as st
from google.genai import errors as genai_errors

from ask_olist import pipeline

st.set_page_config(page_title="Ask-Olist", page_icon="🛒", layout="wide")

SAMPLE_QUESTIONS = [
    "What is the total payment value for each payment type?",
    "How many customers placed more than one order?",
    "What was the total product revenue in 2017?",
    "How many delivered orders were placed in each month of 2017?",
    "Which 5 product categories had the most late deliveries in 2018?",
]


def use_sample(question: str) -> None:
    st.session_state["question"] = question   # runs before the page redraws, so the text box shows it


def show_result(out: dict) -> None:
    st.subheader("Answer")
    st.success(out["answer"])

    if out["attempts"] > 1:
        st.warning(f"The first query failed, so the model corrected it. Attempts needed: {out['attempts']}.")

    if out["assumptions"]:
        st.markdown("**Assumptions the model made**")
        for assumption in out["assumptions"]:
            st.markdown(f"- {assumption}")

    with st.expander("SQL used", expanded=False):
        st.code(out["sql"] or "-- no valid SQL was produced", language="sql")

    if out["rows"]:
        st.markdown(f"**Result** (first {len(out['rows'])} rows)")
        st.dataframe(pd.DataFrame(out["rows"], columns=out["columns"]), width="stretch", hide_index=True)

    retrieved = out.get("retrieved_examples", [])
    if retrieved:
        with st.expander(f"Retrieved examples ({len(retrieved)}): similar verified questions shown to the model"):
            for example in retrieved:
                st.markdown(f"**{example['id']}** · similarity {example['score']:.3f}  \n{example['question']}")
                st.code(example["sql"], language="sql")
    else:
        st.caption("No examples were retrieved (zero-shot mode).")

    left, middle, right = st.columns(3)
    left.metric("Attempts", out["attempts"])
    middle.metric("Latency", f"{out['latency_s']} s")
    right.metric("Retrieved examples", len(retrieved))


st.title("🛒 Ask-Olist")
st.caption("Ask a question about the Olist e-commerce data in plain English. The app writes SQL, runs it read-only, and explains the result.")

with st.sidebar:
    st.header("Settings")
    use_rag = st.toggle("Use retrieved examples (RAG)", value=True,
                        help="On: the 3 most similar verified examples are added to the prompt. Off: zero-shot.")
    st.header("Try a sample question")
    for sample in SAMPLE_QUESTIONS:
        st.button(sample, on_click=use_sample, args=(sample,), width="stretch")
    st.caption("A question that was asked before is served from the disk cache instantly. A new one calls Gemini, "
               "whose free tier has a small daily limit.")

with st.form("ask_form"):
    question = st.text_input("Your question", key="question", placeholder="Which 5 product categories had the most late deliveries in 2018?")
    submitted = st.form_submit_button("Ask")

if submitted:
    if len(question.strip()) < 3:
        st.warning("Please type a question.")
    else:
        try:
            with st.spinner("Thinking..."):
                result = pipeline.ask(question.strip(), use_rag=use_rag)
        except genai_errors.APIError as exc:
            st.error(f"The language model is unavailable right now (error {exc.code}). This is usually the free-tier limit; try again later.")
        except (FileNotFoundError, RuntimeError) as exc:
            st.error(str(exc))
        else:
            show_result(result)
