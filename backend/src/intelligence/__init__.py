"""The Ask layer: guarded text-to-SQL over a dataset, with retrieval and a safe executor.

Entry point: :class:`~src.intelligence.service.AskService`.
"""

from src.intelligence.models import AskResult, ErrorCode

__all__ = ["AskResult", "ErrorCode"]
