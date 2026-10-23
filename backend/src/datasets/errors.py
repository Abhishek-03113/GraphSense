"""Errors raised by the dataset package engine."""

from __future__ import annotations

from dataclasses import dataclass


class UnknownDatasetError(ValueError):
    """Raised when a dataset id does not name a loadable dataset package."""


@dataclass(frozen=True)
class LintIssue:
    """One finding of the package validator."""

    code: str
    message: str
    where: str = ""

    def __str__(self) -> str:
        return f"[{self.code}] {self.where + ': ' if self.where else ''}{self.message}"


class PackageError(ValueError):
    """A dataset package could not be loaded or failed validation.

    ``issues`` lists every problem found, so an author can fix them in one pass.
    """

    def __init__(self, message: str, issues: list[LintIssue] | None = None):
        self.issues = list(issues or [])
        text = message
        if self.issues:
            text += "\n" + "\n".join(f"  - {issue}" for issue in self.issues)
        super().__init__(text)
