"""Parâmetros de conversão e perfis (presets)."""
from __future__ import annotations
from dataclasses import dataclass, fields, asdict

# Campos que mudam a ANÁLISE da página (entram na chave do cache de layout)
LAYOUT_FIELDS = (
    "render_dpi", "threshold", "crop_top_mm", "crop_bottom_mm", "crop_left_mm",
    "crop_right_mm", "max_cols", "col_gap_mm", "col_min_height_mm", "line_gap_mm",
    "word_gap", "detect_figures",
)


@dataclass
class Params:
    # --- análise (caro; fica em cache) ---
    render_dpi: int = 300
    threshold: int = 190          # pixel mais escuro que isto = tinta
    crop_top_mm: float = 0.0      # margens de origem a ignorar (cabeçalho/rodapé)
    crop_bottom_mm: float = 0.0
    crop_left_mm: float = 0.0
    crop_right_mm: float = 0.0
    max_cols: int = 2             # 1 = sem detecção de colunas; 2 ou 4
    col_gap_mm: float = 2.5       # largura mínima da calha entre colunas (K2pdfopt: 0,1 pol)
    col_min_height_mm: float = 38.0  # altura mínima para dividir em colunas (K2pdfopt: 1,5 pol)
    line_gap_mm: float = 0.3      # espaço mínimo entre linhas
    word_gap: float = 0.18        # espaço mínimo entre palavras (x altura da linha)
    detect_figures: bool = True
    # --- composição (barato; roda a cada mudança) ---
    wrap: bool = True             # reorganizar o texto em novas linhas
    justify: bool = True          # justificar parágrafos (se o original for justificado)
    size: float = 1.0             # 1.0 = coluna ocupa a largura da tela; 1.5 = 50% maior
    margin_mm: float = 2.0
    leading: float = 0.12         # espaço extra entre linhas (x altura da linha)
    para_gap: float = 0.45        # espaço entre parágrafos
    para_short: float = 0.30      # linha mais curta que isto (fração da coluna) encerra o parágrafo
    rotate_figures: bool = True   # gira figuras largas para aproveitar a tela
    title_balance: float = 0.35   # 0 = título igual ao corpo; 1 = proporção original do documento
    small_fig_boost: float = 1.4  # amplia figuras pequenas (texto dentro delas fica legível)
    contrast: float = 1.0
    invert: bool = False
    color: bool = False           # manter as cores do original (PDF colorido)
    clean_bg: bool = True         # clareia fundos acinzentados/texturizados atrás do texto
    continuous: bool = True       # fluir o conteúdo entre páginas de origem

    def layout_key(self):
        return tuple(getattr(self, n) for n in LAYOUT_FIELDS)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


PRESETS: dict[str, dict] = {
    "Artigo científico (2 colunas)": {},
    "Prova / simulado (2 colunas)": {"size": 1.25, "leading": 0.2, "para_gap": 0.6},
    "Livro de RPG (várias colunas)": {"max_cols": 4, "threshold": 150, "rotate_figures": True,
                                       "size": 1.0, "justify": False},
    "Baixa visão (texto grande)": {"title_balance": 0.5, "size": 1.8, "justify": False, "contrast": 1.4,
                                    "leading": 0.25, "para_gap": 0.8, "margin_mm": 4.0},
    "Só ajustar à tela (sem reorganizar)": {"wrap": False},
}


def preset(name: str) -> Params:
    return Params.from_dict(PRESETS.get(name, {}))
