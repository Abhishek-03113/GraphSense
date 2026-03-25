"""Guardrails to restrict queries to the SAP O2C dataset domain."""

import re

# Keywords that indicate the query is about the O2C domain
DOMAIN_KEYWORDS: set[str] = {
    "order", "orders", "sales", "customer", "customers", "delivery", "deliveries",
    "invoice", "invoices", "billing", "payment", "payments", "product", "products",
    "material", "journal", "entry", "accounting", "document", "revenue", "amount",
    "quantity", "address", "plant", "shipped", "delivered", "billed", "paid",
    "unpaid", "cancelled", "flow", "trace", "o2c", "sap", "supply chain",
    "fulfillment", "shipment", "outstanding", "overdue", "receivable",
    "total", "average", "count", "how many", "top", "highest", "lowest",
    "most", "least", "trend", "monthly", "yearly", "status", "incomplete",
    "broken", "missing", "currency", "partner", "business",
    "table", "tables", "schema", "data", "database", "entities", "relationships",
    "graph", "node", "edge", "summary", "overview", "describe",
}

# Patterns that indicate off-topic queries
OFF_TOPIC_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(write|compose|create)\s+(a\s+)?(poem|story|essay|song|code|script)\b", re.I),
    re.compile(r"\b(who\s+is|what\s+is|tell\s+me\s+about)\s+(the\s+)?(president|capital|population)\b", re.I),
    re.compile(r"\b(weather|recipe|joke|riddle|trivia|news)\b", re.I),
    re.compile(r"\b(translate|summarize\s+this\s+article|explain\s+quantum)\b", re.I),
    re.compile(r"\b(play|game|chess|tic.tac.toe)\b", re.I),
    re.compile(r"\b(ignore\s+previous|forget\s+instructions|pretend\s+you)\b", re.I),
    re.compile(r"\b(drop\s+table|delete\s+from|truncate|alter\s+table|insert\s+into|update\s+\w+\s+set)\b", re.I),
]

REJECTION_MESSAGE = (
    "This system is designed to answer questions related to the SAP Order-to-Cash "
    "dataset only. Please ask about sales orders, deliveries, invoices, payments, "
    "customers, products, or their relationships."
)

SQL_INJECTION_MESSAGE = (
    "This query appears to contain data-modification statements. "
    "Only read-only (SELECT) queries are supported."
)


def check_guardrails(message: str) -> str | None:
    """Returns an error message if the query should be rejected, None if it passes."""
    stripped = message.strip()

    if len(stripped) < 3:
        return "Please provide a more specific question about the dataset."

    # Check for SQL injection / mutation attempts
    mutation_pattern = re.compile(
        r"\b(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|INSERT\s+INTO|UPDATE\s+\w+\s+SET|CREATE\s+TABLE)\b",
        re.I,
    )
    if mutation_pattern.search(stripped):
        return SQL_INJECTION_MESSAGE

    # Check for prompt injection attempts
    injection_pattern = re.compile(
        r"\b(ignore\s+(all\s+)?previous|forget\s+(all\s+)?instructions|pretend\s+you|you\s+are\s+now|act\s+as)\b",
        re.I,
    )
    if injection_pattern.search(stripped):
        return REJECTION_MESSAGE

    # Check for off-topic patterns
    for pattern in OFF_TOPIC_PATTERNS:
        if pattern.search(stripped):
            return REJECTION_MESSAGE

    # Check if at least one domain keyword is present
    lower = stripped.lower()
    has_domain_relevance = any(kw in lower for kw in DOMAIN_KEYWORDS)

    # Also allow questions that are clearly analytical (numbers, comparisons)
    analytical_patterns = re.compile(
        r"\b(how\s+many|what\s+is|show|list|find|get|display|which|where|total|sum|avg|average|count|max|min|top\s+\d+)\b",
        re.I,
    )
    has_analytical_intent = bool(analytical_patterns.search(stripped))

    if not has_domain_relevance and not has_analytical_intent:
        return REJECTION_MESSAGE

    return None
