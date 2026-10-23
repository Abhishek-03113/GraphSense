"""Evaluation of the Ask layer against a dataset package's golden questions.

``graphsense eval <dataset> --offline`` needs no key (see :mod:`src.intelligence.eval.runner`);
``--live`` asks the configured model.  The metrics are small pure functions in
:mod:`src.intelligence.eval.metrics`, and result sets are compared in
:mod:`src.intelligence.eval.compare`.
"""

from src.intelligence.eval.compare import Comparison, compare_results
from src.intelligence.eval.models import CaseResult, EvalReport, GuardrailResult
from src.intelligence.eval.runner import Evaluator, EvalOptions

__all__ = [
    "CaseResult",
    "Comparison",
    "EvalOptions",
    "EvalReport",
    "Evaluator",
    "GuardrailResult",
    "compare_results",
]
