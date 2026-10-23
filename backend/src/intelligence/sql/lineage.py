"""Where do the output columns of a query come from?

Works on a *qualified* sqlglot tree (every column carries its table alias and
``*`` is expanded).  For each output column it resolves the base-table columns
it reads, through subqueries, CTEs and set operations, and notes whether it is
a plain copy of one column or a summary (aggregate).  Entity extraction and the
privacy masking both build on this.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from src.intelligence.models import Projection, SourceColumn


@dataclass(frozen=True)
class _Out:
    name: str
    sources: frozenset[SourceColumn]
    direct: SourceColumn | None
    aggregate: bool
    constant: bool
    agg: str | None


def _unwrap(node: exp.Expression) -> exp.Expression:
    """Strip parentheses, casts and aliases: they do not change which value is shown."""
    while isinstance(node, exp.Alias | exp.Paren | exp.Cast | exp.TryCast):
        node = node.this
    return node


def _branches(scope: Scope) -> list[Scope]:
    """Scopes of the operands of a set operation (the attribute was renamed between sqlglot versions)."""
    found = getattr(scope, "set_operation_scopes", None)
    if found is None:
        found = getattr(scope, "union_scopes", [])
    return list(found)


_AGG_CONTAINERS = (exp.AggFunc, exp.Filter, exp.WithinGroup)


def _is_aggregate(item: exp.Expression) -> tuple[bool, str | None]:
    """True when the expression summarises rows: it has an aggregate and no bare column outside one."""
    core = _unwrap(item)
    aggs = [a for a in item.find_all(exp.AggFunc) if not a.find_ancestor(exp.Window)]
    if not aggs:
        return False, None
    for col in item.find_all(exp.Column):
        if col.find_ancestor(exp.Window):
            return False, None
        if not col.find_ancestor(*_AGG_CONTAINERS):
            # A column outside every aggregate: it only counts if it sits in a nested query.
            if col.find_ancestor(exp.Select) is not item.find_ancestor(exp.Select):
                continue
            return False, None
    name = None
    if isinstance(core, exp.Filter):
        core = core.this
    if isinstance(core, exp.AggFunc):
        name = core.key.lower()
    return True, name


class _Analyzer:
    def __init__(self, root: exp.Expression) -> None:
        self.by_expr: dict[int, Scope] = {id(s.expression): s for s in traverse_scope(root)}
        self.memo: dict[tuple[int, str], list[_Out]] = {}

    # --- outputs of a query scope --------------------------------------------

    def outputs(self, scope: Scope, prefix: str) -> list[_Out]:
        key = (id(scope), prefix)
        if key in self.memo:
            return self.memo[key]
        self.memo[key] = []  # guards against cycles
        expr = scope.expression
        if isinstance(expr, exp.SetOperation):
            branches = [self.outputs(s, prefix) for s in _branches(scope)]
            result = self._merge(branches)
        else:
            result = [self._item(item, scope, prefix) for item in expr.selects]
        self.memo[key] = result
        return result

    @staticmethod
    def _merge(branches: list[list[_Out]]) -> list[_Out]:
        if not branches:
            return []
        width = min(len(b) for b in branches)
        merged = []
        for i in range(width):
            column = [b[i] for b in branches]
            first = column[0]
            same_direct = all(c.direct == first.direct for c in column)
            merged.append(
                _Out(
                    name=first.name,
                    sources=frozenset().union(*(c.sources for c in column)),
                    direct=first.direct if same_direct else None,
                    aggregate=any(c.aggregate for c in column),
                    constant=all(c.constant for c in column),
                    agg=first.agg if all(c.agg == first.agg for c in column) else None,
                )
            )
        return merged

    def _item(self, item: exp.Expression, scope: Scope, prefix: str) -> _Out:
        inner = item.unalias() if isinstance(item, exp.Alias) else item
        sources: set[SourceColumn] = set()
        for col in inner.find_all(exp.Column):
            owner = col.find_ancestor(exp.Select)
            found, _ = self._resolve(col, self.by_expr.get(id(owner), scope), prefix)
            sources |= found
        direct = None
        core = _unwrap(inner)
        if isinstance(core, exp.Column):
            owner = core.find_ancestor(exp.Select)
            found, direct = self._resolve(core, self.by_expr.get(id(owner), scope), prefix)
            if len(found) != 1:
                direct = None
        aggregate, agg = _is_aggregate(inner)
        constant = not any(True for _ in inner.find_all(exp.Column)) and not any(
            True for _ in inner.find_all(exp.Subquery)
        )
        return _Out(
            name=item.alias_or_name or "",
            sources=frozenset(sources),
            direct=direct,
            aggregate=aggregate,
            constant=constant,
            agg=agg,
        )

    def _resolve(
        self, col: exp.Column, scope: Scope, prefix: str
    ) -> tuple[frozenset[SourceColumn], SourceColumn | None]:
        alias = col.table
        source = scope.sources.get(alias) if alias else None
        if isinstance(source, exp.Table):
            found = SourceColumn(instance=f"{prefix}{alias}", table=source.name, column=col.name)
            return frozenset({found}), found
        if isinstance(source, Scope):
            for out in self.outputs(source, f"{prefix}{alias}/"):
                if out.name == col.name:
                    return out.sources, out.direct
        return frozenset(), None


def _root_scope(root: exp.Expression) -> Scope | None:
    scopes = traverse_scope(root)
    return scopes[-1] if scopes else None


def analyze_projections(qualified: exp.Expression) -> tuple[Projection, ...]:
    """Output columns of a qualified query, in order, with their sources."""
    scope = _root_scope(qualified)
    if scope is None:
        return ()
    analyzer = _Analyzer(qualified)
    outs = analyzer.outputs(scope, "")
    return tuple(
        Projection(
            name=o.name,
            sources=tuple(sorted(o.sources, key=lambda s: (s.instance, s.table, s.column))),
            direct=o.direct,
            aggregate=o.aggregate,
            constant=o.constant,
            agg=o.agg,
        )
        for o in outs
    )


def is_aggregate_only(qualified: exp.Expression, projections: tuple[Projection, ...]) -> bool:
    """One summary row: no grouping, and every output is an aggregate or a constant."""
    if not isinstance(qualified, exp.Select) or not projections:
        return False
    if qualified.args.get("group") or qualified.args.get("distinct"):
        return False
    return all(p.aggregate or p.constant for p in projections)
