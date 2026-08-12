"""Opérateurs de filtre supportés par la query string de prestd.

Voir https://docs.prestd.com/api-reference/parameters — prestd attend des
filtres de la forme `field=$operateur.valeur`, ex: `age=$gt.25`.
L'égalité sans opérateur (`field=valeur`) est aussi valide et c'est ce que
produit `Op.eq`.

Ces helpers renvoient uniquement la *valeur* du paramètre `field=valeur` ;
c'est `QueryBuilder` qui associe le nom du champ.
"""
from __future__ import annotations

from typing import Any, Iterable


def _join(values: Iterable[Any]) -> str:
    return ",".join(str(v) for v in values)


class Op:
    """Constructeurs statiques pour les opérateurs de filtre prestd."""

    @staticmethod
    def eq(value: Any) -> str:
        return str(value)

    @staticmethod
    def gt(value: Any) -> str:
        return f"$gt.{value}"

    @staticmethod
    def gte(value: Any) -> str:
        return f"$gte.{value}"

    @staticmethod
    def lt(value: Any) -> str:
        return f"$lt.{value}"

    @staticmethod
    def lte(value: Any) -> str:
        return f"$lte.{value}"

    @staticmethod
    def ne(value: Any) -> str:
        return f"$ne.{value}"

    @staticmethod
    def in_(values: Iterable[Any]) -> str:
        return f"$in.{_join(values)}"

    @staticmethod
    def nin(values: Iterable[Any]) -> str:
        return f"$nin.{_join(values)}"

    @staticmethod
    def is_null() -> str:
        return "$null"

    @staticmethod
    def is_not_null() -> str:
        return "$notnull"

    @staticmethod
    def is_true() -> str:
        return "$true"

    @staticmethod
    def is_not_true() -> str:
        return "$nottrue"

    @staticmethod
    def is_false() -> str:
        return "$false"

    @staticmethod
    def is_not_false() -> str:
        return "$notfalse"

    @staticmethod
    def like(pattern: str) -> str:
        return f"$like.{pattern}"

    @staticmethod
    def ilike(pattern: str) -> str:
        return f"$ilike.{pattern}"

    @staticmethod
    def nlike(pattern: str) -> str:
        return f"$nlike.{pattern}"

    @staticmethod
    def nilike(pattern: str) -> str:
        return f"$nilike.{pattern}"

    @staticmethod
    def ltree_ancestor(path: str) -> str:
        return f"$ltreelanc.{path}"

    @staticmethod
    def ltree_descendant(path: str) -> str:
        return f"$ltreerdesc.{path}"

    @staticmethod
    def ltree_match(lquery: str) -> str:
        return f"$ltreematch.{lquery}"

    @staticmethod
    def ltree_match_text(ltxtquery: str) -> str:
        return f"$ltreematchtxt.{ltxtquery}"


class Agg:
    """Fonctions d'agrégation utilisables dans `_select` / `_groupby`.

    Supportées par prestd : SUM, AVG, MAX, MIN, STDDEV, VARIANCE.
    """

    @staticmethod
    def sum(field: str) -> str:
        return f"sum:{field}"

    @staticmethod
    def avg(field: str) -> str:
        return f"avg:{field}"

    @staticmethod
    def max(field: str) -> str:
        return f"max:{field}"

    @staticmethod
    def min(field: str) -> str:
        return f"min:{field}"

    @staticmethod
    def stddev(field: str) -> str:
        return f"stddev:{field}"

    @staticmethod
    def variance(field: str) -> str:
        return f"variance:{field}"
