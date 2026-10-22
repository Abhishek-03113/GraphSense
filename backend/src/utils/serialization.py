"""JSON-friendly conversion of database values shared by the API layers."""

import datetime as dt
from decimal import Decimal
from typing import Any


def json_value(value: Any) -> Any:
    """A database value as plain JSON.

    Dates and times become ISO strings and decimals become numbers (integers
    when they have no fractional part), so clients see one consistent shape.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return str(value)
