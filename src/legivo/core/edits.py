"""Edições manuais de regiões (excluir área, marcar como figura).

Os retângulos são guardados como frações da página (0..1), então valem para
qualquer resolução e podem ser aplicados a várias páginas do mesmo tamanho.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict

KINDS = {"exclude": "Excluir área", "figure": "Manter como figura", "table": "Tratar como tabela", "text": "Tratar como texto"}
SCOPES = {"page": "só esta página", "all": "todas as páginas", "odd": "páginas ímpares", "even": "páginas pares"}


@dataclass(frozen=True)
class Edit:
    kind: str          # "exclude" | "figure"
    x0: float
    y0: float
    x1: float
    y1: float
    scope: str = "page"
    page: int = -1     # índice (base 0) quando scope == "page"

    def applies(self, i: int) -> bool:
        if self.scope == "all":
            return True
        if self.scope == "odd":
            return i % 2 == 0      # páginas 1, 3, 5... (base 1)
        if self.scope == "even":
            return i % 2 == 1
        return self.page == i

    def px(self, w: int, h: int):
        return (int(self.x0 * w), int(self.y0 * h), int(self.x1 * w), int(self.y1 * h))

    def label(self) -> str:
        s = SCOPES.get(self.scope, self.scope)
        if self.scope == "page":
            s = f"só a página {self.page + 1}"
        return f"{KINDS.get(self.kind, self.kind)} — {s}"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in ("kind", "x0", "y0", "x1", "y1", "scope", "page") if k in d})
