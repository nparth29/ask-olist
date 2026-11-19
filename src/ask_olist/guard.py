"""SQL safety guard. An LLM must never be trusted to run DELETE, so we check every query first.

Allowed: exactly one statement, and it must be a SELECT (optionally with WITH, or SELECTs joined by UNION).
"""
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class GuardError(ValueError):
    """The SQL was rejected. The message is fed back to the LLM in the retry loop."""


# If any of these appears ANYWHERE in the tree (even nested), reject.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.Command, exp.Pragma, exp.Attach, exp.Detach, exp.Use, exp.Transaction, exp.Commit, exp.Rollback,
)


def check_sql(sql: str) -> str:
    """Return the SQL if it is safe, otherwise raise GuardError."""
    if not sql or not sql.strip():
        raise GuardError("The SQL is empty.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except ParseError as exc:
        raise GuardError(f"The SQL could not be parsed: {exc}") from exc

    if len(statements) != 1:
        raise GuardError(f"Exactly one statement is allowed, found {len(statements)}.")

    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):  # "WITH ... SELECT" parses as a Select
        raise GuardError(f"Only SELECT queries are allowed, got {type(tree).__name__}.")

    for node_type in FORBIDDEN_NODES:
        if tree.find(node_type) is not None:
            raise GuardError(f"{node_type.__name__} is not allowed.")

    return sql.strip().rstrip(";")
