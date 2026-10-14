"""
Figuras Plotly no padrão do painel.

Cores: séries usam a paleta categórica VALIDADA (dataviz/validate_palette.js —
slots 1..3 passam CVD e contraste no fundo branco); a cor da marca (#1B365D)
fica para a interface. Uma escala por gráfico (nunca eixo duplo), marcas finas,
grade recessiva, rótulos pt-BR.
"""
from __future__ import annotations

import plotly.graph_objects as go

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
OUTROS = "#9AA5B4"
TEXTO, TEXTO_2, GRADE = "#14213D", "#4A5568", "#E3E9F1"
ALERTA = "#B42318"
FONTE = "Hanken Grotesk, Arial, sans-serif"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def rotulo_mes(ano_mes: str) -> str:
    ano, mes = str(ano_mes).split("-")[:2]
    return f"{MESES[int(mes) - 1]}/{ano[2:]}"


def base(fig: go.Figure, altura: int = 300, legenda: bool = True) -> go.Figure:
    fig.update_layout(
        height=altura, margin=dict(l=4, r=12, t=28 if legenda else 8, b=4),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONTE, size=12, color=TEXTO_2), separators=",.", hovermode="closest", showlegend=legenda,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=11.5)),
        hoverlabel=dict(bgcolor="white", bordercolor=GRADE, font=dict(color=TEXTO, family=FONTE, size=12)),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRADE, tickfont=dict(color=TEXTO_2), automargin=True)
    fig.update_yaxes(gridcolor=GRADE, zeroline=False, tickfont=dict(color=TEXTO_2), automargin=True)
    return fig


def vazio(msg: str = "Sem dados para os filtros atuais", altura: int = 220) -> go.Figure:
    fig = base(go.Figure(), altura, legenda=False)
    fig.add_annotation(text=msg, showarrow=False, font=dict(color=TEXTO_2, size=13))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def barras_mes(df, coluna: str, nome: str, prefixo="R$ ") -> go.Figure:
    """Uma série por mês (sem eixo duplo). prefixo="" = contagem (sem R$, sem casas)."""
    if df.empty:
        return vazio()
    x = [rotulo_mes(m) for m in df["ano_mes"]]
    fmt = "%{y:,.2f}" if prefixo else "%{y:,.0f}"
    fig = go.Figure(go.Bar(x=x, y=df[coluna], name=nome, marker=dict(color=SERIES[0], cornerradius=4),
                           hovertemplate="%{x}<br>" + nome + ": " + prefixo + fmt + "<extra></extra>"))
    fig.update_yaxes(tickprefix=prefixo)
    fig.update_xaxes(type="category")
    return base(fig, 260, legenda=False)


def linhas_preco(df, x="data_pedido", y="preco_base", serie="fornecedor", destaque=None, max_series=5,
                 unidade="un") -> go.Figure:
    """Preço comparável ao longo do tempo por série (top-N por volume; resto = 'Outros'); atípicos em X."""
    if df.empty:
        return vazio()
    vol = df.groupby(serie)["valor"].sum().sort_values(ascending=False)
    top = list(vol.index[:max_series])
    fig = go.Figure()
    for i, s in enumerate(top + (["Outros"] if len(vol) > max_series else [])):
        d = df[df[serie].isin(top) == False] if s == "Outros" else df[df[serie] == s]  # noqa: E712
        normal = d[~d["atipico"]] if "atipico" in d else d
        if normal.empty:
            continue
        # várias compras no mesmo dia viram UM ponto (média ponderada pela quantidade)
        dia = (normal.assign(_v=normal[y] * normal["qtd_base"]).groupby(x)
               .agg(_v=("_v", "sum"), q=("qtd_base", "sum"), n=("cod_pedido", "size"),
                    pedidos=("cod_pedido", lambda p: ", ".join(map(str, sorted(set(p))[:4])))).reset_index())
        dia["preco"] = dia["_v"] / dia["q"]
        cor = OUTROS if s == "Outros" else SERIES[i % len(SERIES)]
        fig.add_scatter(x=dia[x], y=dia["preco"], name=str(s)[:40], mode="lines+markers" if s != "Outros" else "markers",
                        line=dict(color=cor, width=2), marker=dict(size=8, color=cor, line=dict(color="white", width=1.5)),
                        customdata=dia[["n", "pedidos"]].to_numpy(),
                        hovertemplate=(f"{str(s)[:40]}<br>%{{x|%d/%m/%Y}}<br>R$ %{{y:,.4f}}/{unidade}"
                                       "<br>%{customdata[0]} compra(s) · pedido(s) %{customdata[1]}<extra></extra>"))
    if "atipico" in df:
        at = df[df["atipico"]]
        if len(at):
            fig.add_scatter(x=at[x], y=at[y], name="Atípico (fora da análise)", mode="markers",
                            marker=dict(symbol="x", size=10, color=ALERTA),
                            customdata=at[["cod_pedido", "fornecedor"]].to_numpy(),
                            hovertemplate="Atípico<br>%{x|%d/%m/%Y} · R$ %{y:,.4f}<br>Pedido %{customdata[0]} · "
                                          "%{customdata[1]}<extra></extra>")
    fig.update_yaxes(tickprefix="R$ ", title_text=f"R$ por {unidade}", title_font=dict(size=11))
    fig.update_xaxes(tickformat="%m/%Y", hoverformat="%d/%m/%Y")
    return base(fig, 340)


def estatisticas_mes(m, unidade="un") -> go.Figure:
    """Mediana, média ponderada e mínimo comparáveis por mês — mesma unidade, mesmo eixo."""
    if m.empty:
        return vazio()
    x = [rotulo_mes(a) for a in m["ano_mes"]]
    fig = go.Figure()
    for i, (col, nome, tracejado) in enumerate((("mediana", "Mediana", None), ("media_pond", "Média ponderada", "dot"),
                                                 ("minimo", "Mínimo comparável", "dash"))):
        fig.add_scatter(x=x, y=m[col], name=nome, mode="lines+markers", line=dict(color=SERIES[i], width=2, dash=tracejado),
                        marker=dict(size=7), hovertemplate=f"%{{x}}<br>{nome}: R$ %{{y:,.4f}}/{unidade}<extra></extra>")
    fig.update_yaxes(tickprefix="R$ ")
    fig.update_xaxes(type="category")
    return base(fig, 300)


def barras_preco(df, rotulo: str, codigo: str, unidade="un", limite: int = 15) -> go.Figure:
    """Preço comparável médio ponderado por grupo (barras) + menor preço (marcador)."""
    if df.empty:
        return vazio()
    d = df.sort_values("preco_medio").head(limite).iloc[::-1]
    nomes = _unicos(d[rotulo].tolist(), d[codigo].tolist())
    fig = go.Figure()
    fig.add_bar(y=nomes, x=d["preco_medio"], orientation="h", name="Preço médio ponderado",
                marker=dict(color=SERIES[0], cornerradius=4), width=0.55,
                customdata=d[["n", "valor"]].to_numpy(),
                hovertemplate="%{y}<br>Médio pond.: R$ %{x:,.4f}/" + unidade +
                              "<br>Compras: %{customdata[0]} · R$ %{customdata[1]:,.2f}<extra></extra>")
    fig.add_scatter(y=nomes, x=d["minimo"], mode="markers", name="Menor preço",
                    marker=dict(color=SERIES[1], size=9, symbol="diamond", line=dict(color="white", width=2)),
                    hovertemplate="%{y}<br>Menor: R$ %{x:,.4f}<extra></extra>")
    fig.update_xaxes(tickprefix="R$ ", showgrid=True, gridcolor=GRADE)
    fig.update_yaxes(showgrid=False)
    return base(fig, max(240, 26 * len(d) + 70))


def _unicos(nomes, codigos, tam=38):
    curtos = [str(n)[:tam] for n in nomes]
    rep = {c for c in curtos if curtos.count(c) > 1}
    return [f"{c} · {k}" if c in rep else c for c, k in zip(curtos, codigos)]


# ── Curva ABC / Adiantamento ─────────────────────────────────────────────────
VERDE = "#0F7B6C"
CLASSE_COR = {"A": SERIES[0], "B": SERIES[1], "C": OUTROS}


def pareto(r, altura: int = 300) -> go.Figure:
    """Curva ABC: % acumulado do valor × % dos insumos, pontos coloridos pela classe."""
    if r.empty:
        return vazio()
    fig = go.Figure()
    for cl in ("A", "B", "C"):
        d = r[r["classe"] == cl]
        if d.empty:
            continue
        fig.add_scatter(x=d["pct_itens"], y=d["pct_acum"], mode="lines", name=f"Classe {cl}",
                        line=dict(color=CLASSE_COR[cl], width=3), customdata=d[["insumo", "valor", "posicao"]].to_numpy(),
                        hovertemplate=("%{customdata[2]}º · %{customdata[0]}<br>R$ %{customdata[1]:,.2f}"
                                       "<br>acumulado %{y:.1f}% do valor · %{x:.1f}% dos insumos<extra></extra>"))
    for lim in (80, 95):
        fig.add_hline(y=lim, line=dict(color=GRADE, width=1, dash="dot"))
    fig.update_xaxes(title_text="% dos insumos (do maior para o menor valor)", ticksuffix="%", range=[0, 100],
                     title_font=dict(size=11), showgrid=True, gridcolor=GRADE)
    fig.update_yaxes(title_text="% acumulado do valor", ticksuffix="%", range=[0, 102], title_font=dict(size=11))
    return base(fig, altura)


def barras_h(nomes, valores, nome: str, cor=None, prefixo="R$ ", altura=None, custom=None, hover=None) -> go.Figure:
    if len(valores) == 0:
        return vazio()
    nomes = [str(n)[:42] for n in nomes]
    fig = go.Figure(go.Bar(y=nomes[::-1], x=list(valores)[::-1], orientation="h", name=nome,
                           marker=dict(color=cor or SERIES[0], cornerradius=3), width=0.62,
                           customdata=None if custom is None else custom[::-1],
                           hovertemplate=hover or ("%{y}<br>" + nome + ": " + prefixo + "%{x:,.2f}<extra></extra>")))
    fig.update_xaxes(tickprefix=prefixo, showgrid=True, gridcolor=GRADE)
    fig.update_yaxes(showgrid=False)
    return base(fig, altura or max(220, 24 * len(nomes) + 60), legenda=False)


def serie_anual(anos, valores, nome: str, prefixo="R$ ", sufixo="", cor=None, tipo="linha", casas=2) -> go.Figure:
    if len(valores) == 0:
        return vazio()
    x = [str(a) for a in anos]
    hover = "%{x}<br>" + nome + ": " + prefixo + "%{y:,." + str(casas) + "f}" + sufixo + "<extra></extra>"
    if tipo == "linha":
        tr = go.Scatter(x=x, y=valores, name=nome, mode="lines+markers+text", line=dict(color=cor or SERIES[0], width=2.5),
                        marker=dict(size=9, color=cor or SERIES[0], line=dict(color="white", width=2)),
                        text=[f"{prefixo}{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if v == v else ""
                              for v in valores], textposition="top center", textfont=dict(size=11, color=TEXTO_2),
                        hovertemplate=hover)
    else:
        tr = go.Bar(x=x, y=valores, name=nome, marker=dict(color=cor or SERIES[1], cornerradius=4), width=0.5,
                    hovertemplate=hover)
    fig = go.Figure(tr)
    fig.update_xaxes(type="category")
    fig.update_yaxes(tickprefix=prefixo, ticksuffix=sufixo, rangemode="tozero" if tipo != "linha" else "normal")
    if tipo == "linha":
        lo, hi = min(v for v in valores if v == v), max(v for v in valores if v == v)
        folga = (hi - lo) * 0.25 or hi * 0.1 or 1
        fig.update_yaxes(range=[lo - folga, hi + folga])
    return base(fig, 260, legenda=False)


def variacao_anual(anos, var_pct) -> go.Figure:
    """Variação YoY do preço: alta = vermelho (custo maior), queda = verde."""
    pares = [(str(a), v) for a, v in zip(anos, var_pct) if v == v]
    if not pares:
        return vazio("Precisa de pelo menos 2 anos com preço")
    x, y = zip(*pares)
    cores = [ALERTA if v > 0 else VERDE for v in y]
    fig = go.Figure(go.Bar(x=list(x), y=list(y), marker=dict(color=cores, cornerradius=4), width=0.45,
                           text=[f"{v:+.2f}%".replace(".", ",") for v in y], textposition="outside",
                           hovertemplate="%{x}<br>Variação do preço médio: %{y:+.2f}%<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=TEXTO_2, width=1))
    fig.update_xaxes(type="category")
    fig.update_yaxes(ticksuffix="%", zeroline=False)
    m = max(abs(v) for v in y) * 1.35 or 1
    fig.update_yaxes(range=[-m if min(y) < 0 else -m * 0.15, m if max(y) > 0 else m * 0.15])
    return base(fig, 260, legenda=False)


def mensal_duas(df, col1, nome1, col2, nome2) -> go.Figure:
    """Duas séries de mesma unidade (R$) por mês — mesmo eixo."""
    if df.empty:
        return vazio()
    x = pd_to_datetime(df["ano_mes"])
    fig = go.Figure()
    for col, nome, cor in ((col1, nome1, SERIES[0]), (col2, nome2, SERIES[2])):
        fig.add_scatter(x=x, y=df[col], name=nome, mode="lines", line=dict(color=cor, width=2),
                        hovertemplate="%{x|%m/%Y}<br>" + nome + ": R$ %{y:,.2f}<extra></extra>")
    fig.update_yaxes(tickprefix="R$ ")
    fig.update_xaxes(tickformat="%Y", hoverformat="%m/%Y")
    return base(fig, 300)


def pd_to_datetime(s):
    import pandas as pd
    return pd.to_datetime(s + "-01")


def empilhado_h(nomes, abatido, a_abater, altura=None, series=("Abatido", "A abater")) -> go.Figure:
    """Duas parcelas empilhadas por linha (ex.: abatido × a abater; medido × saldo a medir), em R$."""
    if len(nomes) == 0:
        return vazio()
    nomes = [str(n)[:40] for n in nomes][::-1]
    fig = go.Figure()
    fig.add_bar(y=nomes, x=list(abatido)[::-1], orientation="h", name=series[0], marker=dict(color=VERDE), width=0.62,
                hovertemplate="%{y}<br>" + series[0] + ": R$ %{x:,.2f}<extra></extra>")
    fig.add_bar(y=nomes, x=list(a_abater)[::-1], orientation="h", name=series[1], marker=dict(color=SERIES[1]),
                width=0.62, hovertemplate="%{y}<br>" + series[1] + ": R$ %{x:,.2f}<extra></extra>")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(tickprefix="R$ ", showgrid=True, gridcolor=GRADE)
    fig.update_yaxes(showgrid=False)
    return base(fig, altura or max(240, 26 * len(nomes) + 70))


# ── Avaliação de fornecedores ────────────────────────────────────────────────
CLASSE_AVAL_COR = {"A": ALERTA, "B": "#C98A00", "C": VERDE}


def _mes_x(ano_mes):
    return [rotulo_mes(m) for m in ano_mes]


def avaliacoes_mes(m) -> go.Figure:
    if m.empty:
        return vazio()
    fig = go.Figure(go.Bar(x=_mes_x(m["ano_mes"]), y=m["avaliacoes"], name="Avaliações",
                           marker=dict(color=SERIES[0], cornerradius=4), customdata=m[["fornecedores"]].to_numpy(),
                           hovertemplate="%{x}<br>%{y} avaliações · %{customdata[0]} fornecedores<extra></extra>"))
    fig.update_xaxes(type="category")
    return base(fig, 260, legenda=False)


def nota_mes(m) -> go.Figure:
    """Nota média ponderada por mês, com as faixas A/B/C como referência (escala 0 a 4)."""
    if m.empty:
        return vazio()
    x = _mes_x(m["ano_mes"])
    fig = go.Figure()
    fig.add_hrect(y0=0, y1=2.05, fillcolor=ALERTA, opacity=0.06, line_width=0)
    fig.add_hrect(y0=3.45, y1=4.1, fillcolor=VERDE, opacity=0.06, line_width=0)
    fig.add_scatter(x=x, y=m["media"], mode="lines+markers+text", name="Nota média",
                    line=dict(color="#1B365D", width=2.5), marker=dict(size=8, line=dict(color="white", width=2)),
                    text=[f"{v:.2f}".replace(".", ",") for v in m["media"]], textposition="top center",
                    textfont=dict(size=10.5, color=TEXTO_2), customdata=m[["criticos"]].to_numpy(),
                    hovertemplate="%{x}<br>Nota média: %{y:.2f}<br>%{customdata[0]} fornecedor(es) com nota ≤ 2,0"
                                  "<extra></extra>")
    lo = max(0, min(m["media"].min() - 0.4, 3.0))
    fig.update_yaxes(range=[lo, 4.05], dtick=0.5)
    fig.update_xaxes(type="category")
    fig.add_annotation(x=1, xref="paper", y=3.5, text="C ≥ 3,5", showarrow=False, xanchor="right", yanchor="bottom",
                       font=dict(size=10, color=VERDE))
    return base(fig, 260, legenda=False)


def classes_barra(forn) -> go.Figure:
    cont = forn["classe"].value_counts().reindex(["A", "B", "C"]).fillna(0)
    rot = ["A · até 2,0", "B · 2,1–3,4", "C · 3,5–4,0"]
    fig = go.Figure(go.Bar(x=rot, y=cont.values, marker=dict(color=[CLASSE_AVAL_COR[c] for c in "ABC"], cornerradius=4),
                           width=0.55, text=[int(v) for v in cont.values], textposition="outside",
                           hovertemplate="%{x}: %{y} fornecedor(es)<extra></extra>"))
    fig.update_yaxes(rangemode="tozero")
    return base(fig, 260, legenda=False)


def matriz_risco(forn) -> go.Figure:
    """Nota (x) × valor comprado (y, log): críticos com muito volume ficam no canto superior esquerdo."""
    d = forn[forn["valor_comprado"].fillna(0) > 0]
    if d.empty:
        return vazio("Sem compras (pedidos da API) para os fornecedores avaliados")
    fig = go.Figure()
    for c in ("A", "B", "C"):
        s = d[d["classe"] == c]
        if s.empty:
            continue
        fig.add_scatter(x=s["nota"], y=s["valor_comprado"], mode="markers", name=ROTULO_CLASSE_CURTO[c],
                        marker=dict(color=CLASSE_AVAL_COR[c], size=(s["avaliacoes"].clip(1, 60) ** 0.5) * 3 + 5,
                                    opacity=0.75, line=dict(color="white", width=1)),
                        customdata=s[["rotulo", "avaliacoes", "pedidos"]].to_numpy(),
                        hovertemplate=("%{customdata[0]}<br>Nota %{x:.2f} · %{customdata[1]} avaliações"
                                       "<br>Comprado: R$ %{y:,.2f} em %{customdata[2]} pedido(s)<extra></extra>"))
    fig.add_vline(x=2.05, line=dict(color=ALERTA, width=1, dash="dot"))
    fig.add_vline(x=3.45, line=dict(color=VERDE, width=1, dash="dot"))
    fig.update_xaxes(range=[-0.1, 4.1], title_text="nota no período", title_font=dict(size=11), showgrid=True,
                     gridcolor=GRADE)
    fig.update_yaxes(type="log", tickprefix="R$ ", title_text="valor comprado (pedidos)", title_font=dict(size=11))
    return base(fig, 340)


ROTULO_CLASSE_CURTO = {"A": "A · crítico", "B": "B · atenção", "C": "C · bom"}


def vencimentos(v) -> go.Figure:
    """Saldo a medir por mês de término; a barra 'Vencidos' em vermelho."""
    if v is None or v.empty or not v["saldo"].sum():
        return vazio("Nenhum contrato em andamento com saldo")
    cores = [ALERTA if x else SERIES[0] for x in v["vencido"]]
    fig = go.Figure(go.Bar(x=v["periodo"], y=v["saldo"], marker=dict(color=cores, cornerradius=4),
                           customdata=v["contratos"],
                           hovertemplate="%{x}<br>Saldo a medir: R$ %{y:,.2f}<br>%{customdata} contrato(s)<extra></extra>"))
    fig.update_yaxes(tickprefix="R$ ")
    fig.update_xaxes(type="category")
    return base(fig, 280, legenda=False)


def assinados_mes(m) -> go.Figure:
    """Valor contratado por mês (barras) e quantidade de contratos (hover)."""
    if m is None or m.empty or not m["valor"].sum():
        return vazio()
    x = [rotulo_mes(a) for a in m["ano_mes"]]
    fig = go.Figure(go.Bar(x=x, y=m["valor"], marker=dict(color=SERIES[0], cornerradius=4), customdata=m["contratos"],
                           hovertemplate="%{x}<br>Contratado: R$ %{y:,.2f}<br>%{customdata} contrato(s)<extra></extra>"))
    fig.update_yaxes(tickprefix="R$ ")
    fig.update_xaxes(type="category")
    return base(fig, 260, legenda=False)


def sla_mensal(m) -> go.Figure:
    """% no prazo por mês da solicitação, fase 1 e fase 2 (mesmo eixo: %)."""
    if m is None or m.empty:
        return vazio()
    x = [rotulo_mes(a) for a in m["ano_mes"]]
    fig = go.Figure()
    for col, n, nome, cor in (("pct_f1", "n_f1", "Fase 1 · solicitação → pedido", SERIES[0]),
                              ("pct_f2", "n_f2", "Fase 2 · pedido → entrega", SERIES[1])):
        fig.add_scatter(x=x, y=m[col], name=nome, mode="lines+markers", line=dict(color=cor, width=2),
                        marker=dict(size=6), customdata=m[n],
                        hovertemplate="%{x}<br>" + nome + ": %{y:.1f}% no prazo<br>%{customdata} itens<extra></extra>")
    fig.update_yaxes(ticksuffix="%", rangemode="tozero")
    fig.update_xaxes(type="category")
    return base(fig, 300)


def etapas_sla(e) -> go.Figure:
    """Mediana (barra) e P80 (marcador) de cada etapa do fluxo, em dias."""
    if e is None or e.empty or e["mediana"].isna().all():
        return vazio()
    e = e.iloc[::-1]
    fig = go.Figure(go.Bar(y=e["etapa"], x=e["mediana"], orientation="h", name="Mediana",
                           marker=dict(color=SERIES[0], cornerradius=3), width=0.55, customdata=e["n"],
                           hovertemplate="%{y}<br>Mediana: %{x:.0f} dias<br>%{customdata} itens<extra></extra>"))
    fig.add_scatter(y=e["etapa"], x=e["p80"], mode="markers", name="80% dos itens até",
                    marker=dict(symbol="line-ns-open", size=18, line=dict(width=3, color=ALERTA)),
                    hovertemplate="%{y}<br>80% dos itens em até %{x:.0f} dias<extra></extra>")
    fig.update_xaxes(ticksuffix=" d", showgrid=True, gridcolor=GRADE, rangemode="tozero")
    fig.update_yaxes(showgrid=False)
    return base(fig, 250)


def situacao_barras(rotulos, valores, cores) -> go.Figure:
    if not sum(valores):
        return vazio()
    fig = go.Figure(go.Bar(x=rotulos, y=valores, marker=dict(color=cores, cornerradius=4), width=0.6,
                           text=[f"{int(v):,}".replace(",", ".") for v in valores], textposition="outside",
                           hovertemplate="%{x}: %{y}<extra></extra>"))
    fig.update_yaxes(rangemode="tozero")
    fig.update_xaxes(type="category")
    return base(fig, 260, legenda=False)
