"""Entity extraction for graph highlighting reads column hints from the registry."""

from src.ai.chat import _extract_entities


def test_extracts_entities_from_known_columns():
    rows = [
        {
            "billing_document": "90000001",
            "sales_order": "10001",
            "customer": "CUST1",
            "material": "M-1",
            "total_net_amount": 12,
            "delivery_document": None,
        }
    ]
    assert _extract_entities(rows) == [
        {"id": "Invoice:90000001", "type": "Invoice", "value": "90000001"},
        {"id": "SalesOrder:10001", "type": "SalesOrder", "value": "10001"},
        {"id": "Customer:CUST1", "type": "Customer", "value": "CUST1"},
        {"id": "Product:M-1", "type": "Product", "value": "M-1"},
    ]


def test_first_matching_hint_wins_and_duplicates_are_dropped():
    rows = [{"invoice_customer": "7"}, {"invoice_customer": "7"}]
    assert _extract_entities(rows) == [{"id": "Invoice:7", "type": "Invoice", "value": "7"}]
