"""
Conteúdo do relatório em PowerPoint de cada aba (botão "Gerar relatório").

Cada função recebe os MESMOS filtros da tela e devolve os bytes do .pptx. Usa os mesmos
serviços das telas, então os números do relatório são os da tela no momento do clique.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.formatacao import brl, brl_curto, num, pct
from app.relatorios.apresentacao import Apresentacao


def _c(campo, rotulo, formato="texto", total=False, peso=None):
    d = {"campo": campo, "rotulo": rotulo, "formato": formato, "total": total}
    if peso:
        d["peso"] = peso
    return d


def _periodo(ini, fim, fmt="%d/%m/%Y") -> str:
    if not ini and not fim:
        return "todo o período"
    f = lambda d: pd.Timestamp(d).strftime(fmt) if d else "…"  # noqa: E731
    return f"{f(ini)} a {f(fim)}"


def _filtros(**kw) -> str:
    partes = [f"{k}: {v if isinstance(v, str) else (', '.join(map(str, v[:3])) + ('…' if len(v) > 3 else ''))}"
              for k, v in kw.items() if v]
    return " · ".join(partes) if partes else "sem filtros adicionais"


def _vazio(ap: Apresentacao, msg: str) -> bytes:
    ap.capa()
    ap.notas("Sem dados", [msg])
    return ap.salvar()


# ── Oportunidades ────────────────────────────────────────────────────────────
def oportunidades(ini, fim, obras, fornecedores, categorias, cfg) -> bytes:
    from app.repositories import catalogo_repo
    from app.services import inteligencia as ig
    ops, base_f = ig.oportunidades(ini, fim, obras, fornecedores, categorias, cfg)
    ap = Apresentacao("Oportunidades de negociação", f"Período {_periodo(ini, fim)} · " + _filtros(
        obras=obras, fornecedores=fornecedores, categorias=categorias), "pedidos de compra (API Sienge)",
        "Inteligência de compras")
    if ops.empty:
        return _vazio(ap, "Nenhuma oportunidade com os filtros atuais.")
    somadas = ops[ops["entra_no_total"].astype(bool)]
    comerciais = ops[ops["tipo"] != "verificar_registro"]
    economia = float(somadas["impacto"].sum())
    ap.capa([("economia potencial estimada", brl_curto(economia)), ("oportunidades", num(len(comerciais))),
             ("compras analisadas", brl_curto(float(base_f["valor"].sum()))),
             ("fornecedores", num(base_f["cod_fornecedor"].nunique()))])
    try:
        st = catalogo_repo.contagem_status().set_index("status")["n"]
    except Exception:  # noqa: BLE001
        st = pd.Series(dtype=int)
    ap.kpis("Visão geral", [
        ("Economia potencial estimada", brl_curto(economia), f"{len(somadas)} oportunidades somadas, sem dupla contagem", "bom"),
        ("Oportunidades identificadas", num(len(comerciais)), f"{num((comerciais['prioridade'] >= 60).sum())} de prioridade alta"),
        ("Compras analisadas", brl_curto(float(base_f["valor"].sum())), f"{num(len(base_f))} itens de pedido"),
        ("Fornecedores analisados", num(base_f["cod_fornecedor"].nunique()), f"{num(base_f['cod_obra'].nunique())} obras"),
        ("Pendentes de validação", num(int(st.get("pendente", 0) + st.get("revisar_mudanca", 0))), "pares de insumos"),
        ("Preços atípicos", num(int((ops["tipo"] == "verificar_registro").sum())), "conferir registro — não é economia",
         "alerta"),
    ], "Economia potencial = (preço pago − preço de referência) × volume já comprado. É estimativa, não economia negociada.")
    mes = ig.evolucao_mensal(base_f, cfg)
    if len(mes):
        from app.components.graficos import rotulo_mes
        ap.linhas("Excesso pago acima do menor preço do mês", [rotulo_mes(m) for m in mes["ano_mes"]],
                  {"Excesso pago": mes["excesso"].tolist()}, colunas=True,
                  nota="Por mês: (preço − menor preço comparável do mesmo mês) × quantidade, em materiais com 2+ fornecedores.")
    tipos = somadas.groupby("tipo")["impacto"].sum().sort_values(ascending=False)
    rotulos = ig.TIPOS
    top = somadas.sort_values("impacto", ascending=False).copy()
    top["tipo_rotulo"] = top["tipo"].map(rotulos)
    if len(tipos):
        ap.barras("Economia potencial por tipo", [rotulos.get(t, t) for t in tipos.index], tipos.values,
                  comentario=[f"{brl_curto(economia)} no total",
                              f"{len(somadas)} oportunidades entram na soma",
                              "Diferenças entre obras e volume para consolidar são informativas e não somam."])
    ap.tabela("Maiores oportunidades", ig.com_rastreio(top), [
        _c("material", "Material", peso=2.6), _c("fornecedor", "Fornecedor atual", peso=2), _c("obra", "Obra", peso=1.6),
        _c("solicitacao_atual", "Solic. atual", peso=0.9), _c("solicitacao_ref", "Solic. ref.", peso=0.9),
        _c("preco_atual", "Preço atual", "brl4"), _c("preco_referencia", "Referência", "brl4"),
        _c("diferenca_pct", "Dif.", "pct", peso=0.7), _c("impacto", "Economia pot.", "brl", True)],
        "Solicitação da compra atual e da referência para abrir o caso no Sienge (painel de compras, 2025+).")
    forn = top.groupby("fornecedor")["impacto"].sum().sort_values(ascending=False).head(10)
    ap.barras("Fornecedores com mais economia potencial", forn.index.tolist(), forn.values)
    ap.notas("Como ler este relatório", [
        "Só entram materiais com equivalência de alta confiança (ou validada por pessoa) e unidade comparável.",
        "Referência = menor preço de OUTRO fornecedor, dentro da janela configurada, sem preços atípicos.",
        "O total soma no máximo uma oportunidade por material e fornecedor.",
        "Aumentos podem refletir reajuste de mercado, frete ou prazo: confirmar antes de negociar."])
    return ap.salvar()


# ── Comparativo / Histórico ──────────────────────────────────────────────────
def comparativo(grupo, ini, fim, obras) -> bytes:
    from app.services import inteligencia as ig
    ap = Apresentacao("Comparativo de fornecedores", f"Período {_periodo(ini, fim)}", "pedidos de compra (API Sienge)",
                      "Inteligência de compras")
    if not grupo:
        return _vazio(ap, "Escolha um material na tela antes de gerar o relatório.")
    d = ig.detalhe_material(grupo, ini, fim, obras)
    if d.empty:
        return _vazio(ap, "Sem compras deste material no período.")
    nome = d["nome_grupo"].iat[0]
    ap.titulo = f"Comparativo · {str(nome)[:60]}"
    u = d["unidade_base"].iat[0]
    ok = d[d["comparavel"] & ~d["atipico"]]
    forn = ig.resumo_por(d, ["cod_fornecedor", "fornecedor"])
    ap.capa([("compras comparáveis", num(len(ok))), ("fornecedores", num(ok["cod_fornecedor"].nunique())),
             ("preço mediano", f"{brl(ok['preco_base'].median())}/{u}" if len(ok) else "—"),
             ("pago acima da referência", brl_curto(float(d["economia_potencial"].sum())))])
    if len(forn):
        f = forn.sort_values("preco_medio")
        ap.barras(f"Preço médio por fornecedor (R$/{u})", f["fornecedor"].str[:40].tolist(), f["preco_medio"].tolist(),
                  formato="brl4", comentario=[f"Menor preço médio: {f['fornecedor'].iat[0][:40]}",
                                             f"{brl(f['preco_medio'].iat[0])}/{u}",
                                             f"Maior: {brl(f['preco_medio'].iat[-1])}/{u}"])
        ap.tabela("Resumo por fornecedor", f, [
            _c("fornecedor", "Fornecedor", peso=3), _c("n", "Compras", "int", True, 0.7),
            _c("mediana", "Mediana", "brl4"), _c("minimo", "Mínimo", "brl4"), _c("ultimo_preco", "Último", "brl4"),
            _c("qtd", f"Volume ({u})", "num2", True), _c("valor", "Valor", "brl", True)])
    comp = d.sort_values("data_pedido", ascending=False)
    ap.tabela("Compras mais recentes", comp, [
        _c("data_pedido", "Data", "data", peso=0.8), _c("fornecedor", "Fornecedor", peso=2.4), _c("obra", "Obra", peso=2),
        _c("cod_pedido", "Pedido", "int", peso=0.7), _c("preco_base", f"Preço/{u}", "brl4"),
        _c("preco_referencia", "Referência", "brl4"), _c("economia_potencial", "Acima da ref.", "brl", True)])
    return ap.salvar()


def historico(grupo, ini, fim) -> bytes:
    from app.components.graficos import rotulo_mes
    from app.services import inteligencia as ig
    ap = Apresentacao("Histórico de preços", f"Período {_periodo(ini, fim)}", "pedidos de compra (API Sienge)",
                      "Inteligência de compras")
    if not grupo:
        return _vazio(ap, "Escolha um material na tela antes de gerar o relatório.")
    d = ig.detalhe_material(grupo, ini, fim)
    ok = d[d["comparavel"] & ~d["atipico"]] if len(d) else d
    if ok.empty:
        return _vazio(ap, "Sem compras com preço comparável neste material.")
    u = d["unidade_base"].iat[0]
    ap.titulo = f"Histórico · {str(d['nome_grupo'].iat[0])[:60]}"
    ult = ok.iloc[-1]
    ap.capa([("mediana", f"{brl(ok['preco_base'].median())}/{u}"), ("mínimo", f"{brl(ok['preco_base'].min())}/{u}"),
             ("última compra", f"{brl(ult.preco_base)}/{u}"), ("compras", num(len(ok)))])
    m = ig.estatisticas_mensais(d)
    if len(m):
        ap.linhas(f"Preço por mês (R$/{u})", [rotulo_mes(x) for x in m["ano_mes"]],
                  {"Mediana": m["mediana"].tolist(), "Média ponderada": m["media_pond"].tolist(),
                   "Mínimo": m["minimo"].tolist()}, formato="brl4")
    obra = ig.resumo_por(d, ["cod_obra", "obra"])
    if len(obra):
        o = obra.sort_values("preco_medio")
        ap.barras(f"Preço médio por obra (R$/{u})", o["obra"].str[:40].head(15).tolist(), o["preco_medio"].head(15).tolist(),
                  formato="brl4")
    ap.tabela("Compras", d.sort_values("data_pedido", ascending=False), [
        _c("data_pedido", "Data", "data", peso=0.8), _c("fornecedor", "Fornecedor", peso=2.5), _c("obra", "Obra", peso=2),
        _c("quantidade", "Qtd.", "num2", peso=0.8), _c("preco_base", f"Preço/{u}", "brl4"),
        _c("valor", "Valor", "brl", True)], "Preços atípicos (mediana/MAD) ficam fora das estatísticas.")
    return ap.salvar()


# ── Correspondências ─────────────────────────────────────────────────────────
def correspondencias(visao, categoria, texto) -> bytes:
    from app.repositories import catalogo_repo as repo
    ap = Apresentacao("Correspondência de insumos", "Catálogo de equivalências · " + _filtros(
        categoria=categoria, busca=texto), "catálogo do painel (schema painel)", "Inteligência de compras")
    try:
        st = repo.contagem_status().set_index("status")["n"]
    except Exception:  # noqa: BLE001
        return _vazio(ap, "Catálogo ainda não criado.")
    g = lambda k: int(st.get(k, 0))  # noqa: E731
    ap.capa([("fila de revisão", num(g("pendente") + g("revisar_mudanca"))), ("aprovados", num(g("aprovado") + g("auto_aprovado"))),
             ("rejeitados", num(g("rejeitado"))), ("conflitos técnicos", num(g("incompativel")))])
    rot = {"pendente": "Pendente", "revisar_mudanca": "Revisar (mudou)", "aprovado": "Aprovado por pessoa",
           "auto_aprovado": "Aprovado automático", "rejeitado": "Rejeitado", "incompativel": "Conflito técnico",
           "nao_comparavel": "Não comparável", "baixa": "Baixa similaridade"}
    s = st.sort_values(ascending=False)
    ap.barras("Pares por situação", [rot.get(k, k) for k in s.index], s.values, formato="int", nome_serie="Pares")
    pend = repo.listar_pares(status=["pendente", "revisar_mudanca"], categoria=categoria, texto=texto, limite=3000)
    ap.tabela("Fila de revisão (maior score primeiro)", pend, [
        _c("descricao_a", "Insumo A", peso=3), _c("descricao_b", "Insumo B", peso=3), _c("categoria", "Categoria", peso=1.4),
        _c("score", "Score", "num", peso=0.6), _c("status", "Situação", peso=1)], "Decida na tela Correspondências.")
    return ap.salvar()


# ── Busca por similaridade ───────────────────────────────────────────────────
def busca(sel, unidade, ini, fim, obras, consulta) -> bytes:
    from datetime import date

    from app.repositories import suprimentos_repo
    from app.services import saving
    ap = Apresentacao("Busca por similaridade", f"Busca: {consulta or '—'} · período {_periodo(ini, fim)}",
                      "pedidos de compra (API Sienge)", "Inteligência de compras")
    if not sel:
        return _vazio(ap, "Faça a busca e marque os itens similares antes de gerar o relatório.")
    ids = [s["id_insumo"] for s in sel if (not unidade or s["unidade_padrao"] == unidade)]
    df = suprimentos_repo.itens_dos_insumos(ids, date.fromisoformat(ini[:10]) if ini else None,
                                            date.fromisoformat(fim[:10]) if fim else None, obras or None)
    if df.empty:
        return _vazio(ap, "Sem compras para os itens marcados.")
    df = saving.enriquecer(df)
    r = saving.resumo(df)
    u = unidade or ""
    ap.capa([("total gasto", brl_curto(r.total_gasto)), ("preço médio ponderado", f"{brl(r.preco_medio_pond)}/{u}"),
             ("menor preço", f"{brl(r.menor_preco)}/{u}"), ("dif. p/ menor do mês", brl_curto(r.saving_menor_mes))])
    ap.kpis("Resumo dos itens marcados", [
        ("Total gasto", brl_curto(r.total_gasto), f"{num(r.quantidade, 1)} {u} em {r.n_itens} compras"),
        ("Preço médio ponderado", f"{brl(r.preco_medio_pond)}/{u}", ""),
        ("Menor preço", f"{brl(r.menor_preco)}/{u}", str(r.fornecedor_menor_preco)[:40], "bom"),
        ("Maior preço", f"{brl(r.maior_preco)}/{u}", ""),
        ("Fornecedores · obras · pedidos", f"{r.n_fornecedores} · {r.n_obras} · {r.n_pedidos}", ""),
        ("Diferença p/ menor preço do mês", brl_curto(r.saving_menor_mes), "estimativa", "alerta"),
    ], f"{len(ids)} insumo(s) marcados na busca.")
    f = saving.por_fornecedor(df)
    if len(f):
        ap.barras(f"Preço médio ponderado por fornecedor (R$/{u})", f["fornecedor"].str[:40].head(15).tolist(),
                  f["preco_medio_pond"].head(15).tolist(), formato="brl4")
        ap.tabela("Por fornecedor", f, [
            _c("fornecedor", "Fornecedor", peso=3), _c("pedidos", "Pedidos", "int", True, 0.7),
            _c("preco_medio_pond", "Preço médio", "brl4"), _c("menor_preco", "Menor", "brl4"),
            _c("total_gasto", "Total gasto", "brl", True)])
    return ap.salvar()


# ── Curva ABC ────────────────────────────────────────────────────────────────
def curva_abc(d_base: pd.DataFrame, ano, ano_ant, grupos, tabelas, tipos, chave, detalhes) -> bytes:
    from app.services import curva_abc as ca
    d = ca.filtrar(d_base, None, tabelas, grupos, tipos)
    ano_ant = ano_ant if ano_ant != ano else None
    rank = ca.ranking(d, ano, ano_ant)
    ap = Apresentacao("Curva ABC de insumos", f"Ano {ano}" + (f" comparado a {ano_ant}" if ano_ant else "") + " · "
                      + _filtros(grupos=grupos, tabelas=tabelas, tipos=tipos), "Curva ABC de Apropriações (Sienge, via RPA)")
    if rank.empty:
        return _vazio(ap, "Sem insumos no recorte.")
    r = ca.resumo_ano(rank)
    ap.capa([(f"valor apropriado em {ano}", brl_curto(r["valor"])), ("insumos", num(r["insumos"])),
             ("classe A", f"{num(r['a_n'])} insumos"), ("efeito preço A/B", brl_curto(r["efeito_preco_ab"]))])
    ap.kpis(f"Visão de {ano}", [
        ("Valor apropriado", brl_curto(r["valor"]), f"{num(r['insumos'])} insumos no recorte"),
        ("Classe A", f"{num(r['a_n'])} insumos", f"{pct(r['a_pct_itens'], 1)} dos itens = {pct(r['a_valor'] / r['valor'] * 100, 1)} do valor"),
        ("Classes B e C", f"{num(r['b_n'])} · {num(r['c_n'])}", "insumos"),
        ("Alta de preço em A/B", num(r["altas_ab"]), f"insumos mais caros que em {ano_ant}" if ano_ant else "sem comparação",
         "alerta"),
        ("Efeito preço (A/B)", brl_curto(r["efeito_preco_ab"]), "pago a mais pela alta, mesmos detalhes", "alerta"),
        ("Quantidade não convertida", num(int(rank["nao_convertida"].sum())), "insumos com '*' do Sienge"),
    ], "Classe no recorte: A até 80% do valor acumulado, B até 95%, C o resto.")
    g = ca.por_grupo(d, ano).head(12)
    ap.barras(f"Valor por grupo de insumo — {ano}", g["grupo_rotulo"].str[:45].tolist(), g["valor"].tolist(),
              comentario=[f"{g['grupo_rotulo'].iat[0][:40]}", f"{pct(g['pct'].iat[0], 1)} do valor do ano",
                          f"Top 12 grupos = {pct(g['pct'].sum(), 1)} do valor"])
    cols = [_c("posicao", "#", "int", peso=0.4), _c("classe", "Classe", peso=0.5), _c("insumo", "Insumo", peso=3.2),
            _c("unidade", "Un.", peso=0.5), _c("quantidade", "Qtd.", "num2"), _c("preco_medio", "Preço médio", "brl4"),
            _c("var_preco_pct", "Var. preço", "pct", peso=0.8), _c("valor", "Valor", "brl", True, 1.2),
            _c("pct_acum", "% acum.", "pct", peso=0.7)]
    ap.tabela(f"Maiores insumos de {ano}", rank, cols, "Var. preço compara o mesmo detalhe nos dois anos (sem efeito de mix).")
    if ano_ant:
        altas = rank[rank["classe"].isin(["A", "B"]) & (rank["var_preco_pct"] > 0)].sort_values("efeito_preco",
                                                                                                ascending=False)
        ap.tabela(f"Maiores altas de preço (A/B) vs {ano_ant}", altas, [
            _c("classe", "Classe", peso=0.5), _c("insumo", "Insumo", peso=3.2), _c("unidade", "Un.", peso=0.5),
            _c("var_preco_pct", "Var. preço", "pct", peso=0.8), _c("efeito_preco", "Efeito preço", "brl", True),
            _c("valor", "Valor", "brl", True)])
    if chave:
        s, info = ca.serie_insumo(d_base, chave, detalhes)
        if len(s) >= 2:
            u = info["unidade"]
            ap.linhas(f"{info['insumo'][:55]} — preço médio (R$/{u})", s["ano"].astype(str).tolist(),
                      {"Preço médio": s["preco_medio"].tolist()}, formato="brl4",
                      comentario=[info["grupo"][:40], f"Atual: {brl(info['preco_atual'])}/{u}",
                                  "Variação (mesmos detalhes): " + ("—" if info["var_yoy"] != info["var_yoy"]
                                                                   else f"{info['var_yoy']:+.2f}%".replace(".", ",")),
                                  f"Valor acumulado: {brl_curto(info['valor_total'])}"])
    return ap.salvar()


# ── Adiantamento ─────────────────────────────────────────────────────────────
def adiantamento(ini, fim, empresas, credores, tipos, vinculos, doc) -> bytes:
    from app.components.graficos import rotulo_mes
    from app.repositories import rpa_repo
    from app.services import adiantamento as ad
    mov, posicao, ref = ad.filtrar(rpa_repo.adiantamentos(), ini, fim, empresas, credores, tipos, vinculos, doc)
    ap = Apresentacao("Adiantamentos a fornecedores", f"Período {_periodo(ini, fim)} · posição em {ref:%d/%m/%Y}",
                      "Saldo de adiantamento (Sienge, via RPA)")
    if posicao.empty:
        return _vazio(ap, "Nenhuma movimentação com os filtros atuais.")
    docs = ad.por_documento(posicao, ref)
    r = ad.resumo(mov, posicao, ref)
    ap.capa([("saldo a abater", brl_curto(r["saldo"])), ("total adiantado", brl_curto(r["adiantado"])),
             ("total abatido", brl_curto(r["abatido"])), ("credores com saldo", num(r["credores_com_saldo"]))])
    ap.kpis("Visão geral", [
        ("Total adiantado", brl_curto(r["adiantado"]), f"{num(r['n_adiantamentos'])} adiantamentos · {num(r['credores'])} credores"),
        ("Total abatido", brl_curto(r["abatido"]), f"{pct(r['pct_abatido'], 1)} do adiantado", "bom"),
        ("Saldo a abater", brl_curto(r["saldo"]), f"posição em {ref:%d/%m/%Y}", "alerta"),
        ("Credores com saldo", num(r["credores_com_saldo"]), f"{num(r['documentos_abertos'])} documentos em aberto"),
        ("Saldo há mais de 1 ano", brl_curto(r["saldo_mais_1_ano"]), "adiantado e ainda não abatido", "alerta"),
        ("Realocações (saída)", brl_curto(r["realocado"]), "reduzem o saldo sem nota fiscal"),
    ], "Saldo = adiantamentos − abatimentos − realocações de saída; confere com o total de cada relatório do Sienge.")
    idade = ad.idade_saldo(docs)
    ap.barras("Há quanto tempo o saldo está em aberto", idade["faixa"].tolist(), idade["saldo"].tolist(),
              comentario=[f"{brl_curto(r['saldo_mais_1_ano'])} há mais de 1 ano",
                          "Idade = dias desde o 1º adiantamento do documento",
                          "Saldo antigo = fornecedor recebeu e não entregou/faturou"])
    v = ad.por_vinculo(mov, docs)
    if len(v):
        ap.barras("Saldo a abater por tipo de vínculo", v["tipo_vinculo"].tolist(), v["saldo"].tolist())
    m = ad.mensal(mov)
    if len(m) > 1:
        ultimos = m.tail(24)
        ap.linhas("Adiantado × abatido por mês (últimos 24 meses)", [rotulo_mes(x) for x in ultimos["ano_mes"]],
                  {"Adiantado": ultimos["adiantado"].tolist(), "Abatido": ultimos["abatido"].tolist()})
    cred = ad.por_credor(docs)
    cred = cred[cred["saldo"] > ad.TOL]
    ap.tabela("Credores com maior saldo a abater", cred, [
        _c("credor", "Credor", peso=3), _c("documentos", "Docs.", "int", peso=0.6), _c("adiantado", "Adiantado", "brl", True),
        _c("abatido", "Abatido", "brl", True), _c("saldo", "Saldo a abater", "brl", True),
        _c("maior_idade", "Maior idade (dias)", "int", peso=0.9)])
    ab = docs[docs["saldo"] > ad.TOL]
    ap.tabela("Documentos com maior saldo", ab, [
        _c("credor", "Credor", peso=2.6), _c("empresa", "Empresa", peso=2.2), _c("documento_vinculado", "Documento", peso=1.1),
        _c("tipo_vinculo", "Vínculo", peso=1), _c("saldo", "Saldo", "brl", True), _c("dias_em_aberto", "Dias", "int", peso=0.6)])
    return ap.salvar()


# ── Avaliação de fornecedores ────────────────────────────────────────────────
def avaliacao(ini, fim, fornecedores, classes, base, minimo) -> bytes:
    from app.components.graficos import rotulo_mes
    from app.repositories import rpa_repo
    from app.services import avaliacao as av
    b = rpa_repo.avaliacoes()
    d = av.filtrar(b, ini, fim, fornecedores)
    base = base or av.BASE_PADRAO
    forn = av.por_fornecedor(d, base, rpa_repo.compras_por_fornecedor())
    forn = forn[forn["avaliacoes"] >= int(minimo or 1)]
    if classes:
        forn = forn[forn["classe"].isin(classes)]
    d = d[d["cod_fornecedor"].isin(forn["cod_fornecedor"])]
    ap = Apresentacao("Avaliação de fornecedores", f"Período {_periodo(ini, fim, '%m/%Y')} · classificação pela "
                      f"{av.BASES[base].lower()}", "Avaliações de Fornecedor (Sienge, via RPA)")
    if forn.empty:
        return _vazio(ap, "Nenhum fornecedor avaliado com os filtros atuais.")
    r = av.resumo(d, forn)
    ap.capa([("fornecedores avaliados", num(r["fornecedores"])), ("avaliações", num(r["avaliacoes"])),
             ("nota média", num(r["media"], 2)), ("críticos (A)", num(r["a"]))])
    ap.kpis("Visão geral", [
        ("Fornecedores avaliados", num(r["fornecedores"]), ""),
        ("Avaliações realizadas", num(r["avaliacoes"]), ""),
        ("Nota média (ponderada)", num(r["media"], 2), f"mediana dos fornecedores {num(r['mediana'], 2)}"),
        ("Críticos (A, até 2,0)", num(r["a"]), f"{pct(r['pct_a'], 1)} dos avaliados", "alerta"),
        ("Em atenção (B, 2,1 a 3,4)", num(r["b"]), f"{num(r['c'])} na classe C"),
        ("Comprado de críticos", brl_curto(r["valor_criticos"]), f"{num(r['criticos_com_compra'])} fornecedores A com pedidos",
         "alerta"),
    ], "Escala 0 a 4, nota arredondada a 1 casa. Médias ponderadas pelo nº de avaliações.")
    m = av.mensal(d)
    if len(m):
        ap.linhas("Nota média por mês", [rotulo_mes(x) for x in m["ano_mes"]], {"Nota média": m["media"].round(2).tolist()},
                  formato="num2", eixo=(0, 4), comentario=["A (crítico) até 2,0", "B de 2,1 a 3,4", "C de 3,5 a 4,0",
                                              f"{num(int(m['avaliacoes'].sum()))} avaliações no período"])
    cont = forn["classe"].value_counts().reindex(["A", "B", "C"]).fillna(0)
    from app.relatorios.apresentacao import VERDE, VERMELHO
    from pptx.dml.color import RGBColor
    ap.barras("Fornecedores por classe", ["A · crítico", "B · atenção", "C · bom"], cont.values, formato="int",
              horizontal=False, nome_serie="Fornecedores", cores_pontos=[VERMELHO, RGBColor(0xC9, 0x8A, 0x00), VERDE])
    crit = forn[forn["classe"] == "A"]
    cols = [_c("rotulo", "Fornecedor", peso=3.2), _c("nota", "Nota", "num2", peso=0.6), _c("nota_media", "Média", "num2", peso=0.6),
            _c("nota_atual", "Nota Sienge", "num2", peso=0.8), _c("avaliacoes", "Avaliações", "int", True, 0.8),
            _c("meses_criticos", "Meses ≤ 2", "int", peso=0.7), _c("valor_comprado", "Comprado", "brl", True)]
    ap.tabela("Fornecedores críticos (A)", crit, cols, "Prioridade para plano de ação: nota baixa e volume comprado alto.")
    ap.tabela("Fornecedores em atenção (B) — piores notas", forn[forn["classe"] == "B"], cols)
    return ap.salvar()


# ── Estoque ──────────────────────────────────────────────────────────────────
def estoque(d: pd.DataFrame, filtros_txt: str, incompleto: str | None) -> bytes:
    from app.services import estoque as es
    ap = Apresentacao("Estoque de obras", filtros_txt, "Estoque de obras (Sienge, via RPA)")
    if not d["com_saldo"].any():
        return _vazio(ap, "Nenhum item com saldo nos filtros atuais.")
    r = es.resumo(d, d)
    ap.capa([("valor em estoque", brl_curto(r["valor"])), ("insumos com saldo", num(r["insumos"])),
             ("centros de custo", num(r["centros"])), ("do valor em 20% dos itens", pct(r["pct_top20"], 0))])
    ap.kpis("Visão geral", [
        ("Valor em estoque", brl_curto(r["valor"]), f"{num(r['posicoes'])} itens com saldo"),
        ("Insumos com saldo", num(r["insumos"]), f"em {num(r['centros'])} centros de custo"),
        ("Concentração", pct(r["pct_top20"], 0), "do valor em 20% dos itens"),
        ("Abaixo do mínimo", num(r["abaixo_minimo"]), f"{num(r['acima_maximo'])} acima do máximo", "alerta"),
        ("Inativos", num(r["inativos"]), f"{num(r['inativos_com_saldo'])} ainda com saldo"),
        ("10 maiores itens", brl_curto(r["top10_valor"]), f"{pct(r['top10_valor'] / r['valor'] * 100, 1)} do valor em estoque"),
    ], incompleto or "Valor = Σ custo médio × quantidade apropriada (igual ao total do relatório do Sienge).")
    seg = es.por(d, "segmento")
    ap.barras("Valor em estoque por segmento", seg["segmento"].tolist(), seg["valor"].tolist(),
              comentario=[f"{seg['segmento'].iat[0]}: {pct(seg['pct'].iat[0], 1)} do valor",
                          f"{num(len(seg))} segmento(s)", f"{brl_curto(r['valor'])} no total"])
    cen = es.por(d, "centro_rotulo").head(15)
    ap.barras("Valor por centro de custo (15 maiores)", cen["centro_rotulo"].str[:45].tolist(), cen["valor"].tolist())
    gru = es.por(d, "grupo_rotulo")
    ap.barras("Valor por grupo de insumo (15 maiores)", gru["grupo_rotulo"].str[:45].head(15).tolist(),
              gru["valor"].head(15).tolist(), cor=None)
    ap.tabela("Por grupo de insumo", gru, [
        _c("grupo_rotulo", "Grupo de insumo", peso=3), _c("posicoes", "Itens com saldo", "int", True),
        _c("insumos", "Insumos", "int"), _c("centros", "Centros", "int"), _c("valor", "Valor", "brl", True, 1.2),
        _c("pct", "% do valor", "pct", True)])
    it = es.itens(d)
    ap.tabela("Itens de maior valor em estoque", it, [
        _c("centro_rotulo", "Centro de custo", peso=2.3), _c("descricao_completa", "Insumo", peso=3.3),
        _c("unidade", "Un.", peso=0.5), _c("quantidade", "Quantidade", "num2"), _c("custo_medio", "Custo médio", "brl4"),
        _c("valor_estoque", "Valor", "brl", True)])
    remanejar = es.mesmo_insumo_em_varios_centros(d)
    if len(remanejar):
        ap.tabela("Mesmo insumo com saldo em várias obras", remanejar, [
            _c("descricao_completa", "Insumo", peso=3.6), _c("unidade", "Un.", peso=0.5), _c("centros", "Obras", "int", peso=0.6),
            _c("quantidade", "Quantidade total", "num2"), _c("valor", "Valor", "brl", True)],
            "Candidatos a remanejamento entre obras antes de uma nova compra.")
    notas = ["O relatório vem por apropriação; o valor soma as apropriações, a quantidade é o saldo físico (não somado).",
             "Segmento vem do cadastro de centros de custo; analista, da planilha por grupo e tipo de obra."]
    if incompleto:
        notas.insert(0, incompleto)
    ap.notas("Como ler este relatório", notas)
    return ap.salvar()


# ── Contratos ────────────────────────────────────────────────────────────────
def contratos(d: pd.DataFrame, filtros_txt: str) -> bytes:
    from app.relatorios.apresentacao import AZUL, VERMELHO
    from app.services import contratos as ct
    ap = Apresentacao("Contratos", filtros_txt, "Relatório de contratos (Sienge, via RPA)")
    if d.empty:
        return _vazio(ap, "Nenhum contrato nos filtros atuais.")
    r = ct.resumo(d)
    ap.capa([("contratos", num(r["contratos"])), ("valor contratado", brl_curto(r["valor_total"])),
             ("saldo a medir", brl_curto(r["saldo"])), ("vencidos com saldo", num(r["vencidos"]))])
    ap.kpis("Visão geral", [
        ("Contratos", num(r["contratos"]), f"{num(r['fornecedores'])} fornecedores"),
        ("Valor contratado", brl_curto(r["valor_total"]), f"medido {pct(r['pct_medido'], 1)}"),
        ("Saldo a medir", brl_curto(r["saldo"]), f"{num(r['em_andamento'])} contratos em andamento", "bom"),
        ("Vencidos com saldo", num(r["vencidos"]), f"{brl_curto(r['saldo_vencidos'])} a medir", "alerta"),
        ("Vencem em breve", num(r["vence_breve"]), f"{brl_curto(r['saldo_breve'])} a medir"),
        ("Aguardando autorização", num(r["aguardando"]), brl_curto(r["valor_aguardando"])),
    ], "Saldo a medir = valor − medido dos contratos Pendentes ou Parcialmente medidos.")
    posicao = d["posicao_em"].max() if d["posicao_em"].notna().any() else pd.Timestamp.today()
    v = ct.vencimentos(d, posicao)
    if len(v) and v["saldo"].sum():
        ap.barras("Saldo a medir por mês de término", v["periodo"].tolist(), v["saldo"].tolist(), horizontal=False,
                  cores_pontos=[VERMELHO if x else AZUL for x in v["vencido"]],
                  comentario=[f"Vencidos: {brl_curto(r['saldo_vencidos'])} em {num(r['vencidos'])} contrato(s)",
                              f"Próximos dias: {brl_curto(r['saldo_breve'])}"])
    seg = ct.por(d, "segmento")
    ap.barras("Saldo a medir por segmento", seg["segmento"].tolist(), seg["saldo"].tolist())
    forn = ct.por(d[d["em_andamento"]], "cod_fornecedor", "fornecedor_rotulo").head(15)
    ap.barras("Maiores saldos a medir — fornecedores", forn["fornecedor_rotulo"].str[:45].tolist(), forn["saldo"].tolist())
    obra = ct.por(d[d["em_andamento"]], "cod_obra", "obra_rotulo").head(15)
    ap.barras("Maiores saldos a medir — obras", obra["obra_rotulo"].str[:45].tolist(), obra["saldo"].tolist())
    venc = d[d["vencido_com_saldo"]].sort_values("saldo_aberto", ascending=False)
    if len(venc):
        ap.tabela("Contratos vencidos com saldo", venc, [
            _c("numero_contrato", "Contrato", peso=1), _c("fornecedor_rotulo", "Fornecedor", peso=2.6),
            _c("obra_rotulo", "Obra", peso=2.2), _c("data_termino", "Término", "data", peso=0.9),
            _c("valor_total", "Valor", "brl"), _c("saldo_aberto", "Saldo a medir", "brl", True)],
            "Término já passou e ainda há saldo: encerrar, aditar o prazo ou medir.")
    tipo = ct.por(d, "tipo_contrato")
    ap.tabela("Por tipo de contrato", tipo, [
        _c("tipo_contrato", "Tipo", peso=2.6), _c("contratos", "Contratos", "int", True),
        _c("valor_total", "Valor", "brl", True), _c("valor_medido", "Medido", "brl", True),
        _c("saldo", "Saldo a medir", "brl", True), _c("pct_medido", "% medido", "pct")])
    ap.notas("Como ler este relatório", [
        "Fonte: relatório de contratos do Sienge exportado pelo RPA e conferido com a linha de total de cada arquivo.",
        "Saldo a medir só existe para contratos em andamento; encerrados mostram o valor não executado (valor − medido).",
        "Obra = 1ª obra do contrato (poucos contratos têm mais de uma)."])
    return ap.salvar()


# ── SLA de insumos ───────────────────────────────────────────────────────────
def sla_insumos(d: pd.DataFrame, filtros_txt: str, contar_abertos: bool) -> bytes:
    from app.services import sla
    ap = Apresentacao("SLA - Insumos", filtros_txt, "Painel de compras do Sienge (via RPA)")
    if d.empty:
        return _vazio(ap, "Nenhum item nos filtros atuais.")
    r1, r2 = sla.resumo_fase(d, "f1", contar_abertos), sla.resumo_fase(d, "f2", contar_abertos)
    ent = d[d["atraso_obra"].notna()]
    apos = (ent["atraso_obra"] > 0).mean() * 100 if len(ent) else 0
    ap.capa([("no prazo · fase 1", pct(r1["pct"], 1)), ("no prazo · fase 2", pct(r2["pct"], 1)),
             ("vencidos em aberto", num(r1["atrasados_abertos"] + r2["atrasados_abertos"])),
             ("entregue após a data da obra", pct(apos, 0))])
    for fase, r, nome in (("f1", r1, "Fase 1 · solicitação → pedido"), ("f2", r2, "Fase 2 · pedido → entrega")):
        ap.kpis(nome, [
            ("Itens com SLA mensurável", num(r["base_pct"]), f"{num(r['mensuraveis'])} concluídos"),
            ("SLA atendido", pct(r["pct"], 1), f"{num(r['atendidos'])} itens", "bom"),
            ("SLA não atendido", num(r["nao_atendidos"] + (r["atrasados_abertos"] if contar_abertos else 0)),
             pct(100 - r["pct"], 1), "alerta"),
            ("Em aberto já vencidos", num(r["atrasados_abertos"]), f"{num(r['em_risco'])} em risco"),
            ("Mediana real × prazo médio", f"{num(r['mediana_dias'])} | {num(r['prazo_medio'])} d",
             f"média {num(r['media_dias'], 1)} d · 80% até {num(r['p80_dias'])} d"),
            ("Concluídos no prazo", pct(r["pct_concluidos"], 1), "só o que já terminou (critério do Power BI)"),
        ], "Itens em aberto que já passaram do prazo " + ("contam" if contar_abertos else "não contam") +
           " como não atendidos.")
    et = sla.etapas(d).dropna(subset=["mediana"])
    if len(et):
        ap.barras("Onde o tempo é gasto (mediana de cada etapa, dias)", et["etapa"].tolist(), et["mediana"].tolist(),
                  formato="num", comentario=sla.gargalos(d, contar_abertos)[:4])
    m = sla.mensal(d, contar_abertos)
    if len(m):
        ap.linhas("% no prazo por mês da solicitação", [graficos_rotulo(x) for x in m["ano_mes"]],
                  {"Fase 1": m["pct_f1"].round(1).tolist(), "Fase 2": m["pct_f2"].round(1).tolist()}, formato="pct")
    g = sla.por(d, "grupo_insumo", contar_abertos)
    if len(g):
        ap.tabela("Por grupo de insumo (mais não atendidos primeiro)", g, [
            _c("grupo_insumo", "Grupo", peso=2.8), _c("n_f1", "Itens F1", "int", True), _c("pct_f1", "% F1", "pct"),
            _c("mediana_f1", "Med. F1", "num"), _c("prazo_f1", "Prazo F1", "num"), _c("n_f2", "Pedidos F2", "int", True),
            _c("pct_f2", "% F2", "pct"), _c("mediana_f2", "Med. F2", "num"), _c("prazo_f2", "Prazo F2", "num")])
    for dim, titulo in (("analista", "Por analista"), ("comprador", "Por comprador")):
        t = sla.por(d, dim, contar_abertos)
        if len(t):
            ap.tabela(titulo, t, [
                _c(dim, titulo.split()[-1].title(), peso=2.4), _c("n_f1", "Itens F1", "int", True),
                _c("pct_f1", "% F1", "pct"), _c("atrasados_f1", "Vencidos F1", "int", True),
                _c("n_f2", "Pedidos F2", "int", True), _c("pct_f2", "% F2", "pct"),
                _c("atrasados_f2", "Vencidos F2", "int", True), _c("pct_entregue_apos_obra", "Após data obra", "pct")])
    a = sla.abertos_atrasados(d)
    if len(a):
        ap.tabela("Em aberto há mais tempo além do prazo", a, [
            _c("fase", "Fase", peso=1.6), _c("cod_solicitacao", "Solic.", peso=0.7), _c("insumo", "Insumo", peso=3),
            _c("obra_rotulo", "Obra", peso=2), _c("comprador", "Comprador", peso=1.3),
            _c("dias_alem_prazo", "Além do prazo (d)", "int")])
    ap.notas("Como ler este relatório", [
        "Fase 1 = autorização da solicitação até o 1º pedido do item; fase 2 = pedido até a ÚLTIMA entrega do item.",
        "Prazos por grupo de insumo: planilha de Suprimentos, com as alterações feitas em Configurações no painel.",
        "Dias corridos. 'Em risco' = em aberto perto de estourar o prazo.",
        "Diferenças para o Power BI: aqui cada item conta 1 vez (o Power BI contava 1 vez por nota fiscal) e o backlog "
        "vencido aparece."])
    return ap.salvar()


def graficos_rotulo(ano_mes: str) -> str:
    from app.components.graficos import rotulo_mes
    return rotulo_mes(ano_mes)


# ── Serviços ─────────────────────────────────────────────────────────────────
def servicos(d: pd.DataFrame, filtros_txt: str) -> bytes:
    from app.services import servicos as sv
    ap = Apresentacao("Serviços", filtros_txt, "Solicitações de serviço (Sienge, via RPA)")
    if d.empty:
        return _vazio(ap, "Nenhuma solicitação nos filtros atuais.")
    r = sv.resumo(d)
    ap.capa([("solicitações", num(r["solicitado"])), ("atendidas", pct(r["pct_atendido"], 0)),
             ("em aberto", num(r["em_aberto"])), ("aguardando autorização", num(r["aguardando"]))])
    ap.kpis("Visão geral", [
        ("Solicitado", num(r["solicitado"]), f"{pct(r['pct_atendido'], 1)} atendido"),
        ("Totalmente atendido", num(r["totalmente"]), f"parcial {num(r['parcial'])}", "bom"),
        ("Pendente", num(r["pendente"]), f"idade mediana {num(r['idade_mediana_aberto'])} d"),
        ("Aguardando autorização", num(r["aguardando"]), f"{num(r['alerta_aut'])} acima do alerta", "alerta"),
        ("Término previsto vencido", num(r["termino_vencido"]), "em aberto", "alerta"),
        ("Duração prevista média", f"{num(r['duracao_media'])} d", f"mediana {num(r['duracao_mediana'])} d"),
    ], "Duração = término − início previstos; resposta = alteração − cadastro.")
    m = sv.mensal(d)
    ap.barras("Solicitações por mês do cadastro", [graficos_rotulo(x) for x in m["ano_mes"]], m["solicitado"].tolist(),
              formato="int", horizontal=False)
    for dim, titulo in (("obra_rotulo", "Por obra"), ("autorizador", "Por autorizador"), ("solicitante", "Por solicitante")):
        t = sv.por(d, dim)
        ap.tabela(titulo + " (mais em aberto primeiro)", t, [
            _c(dim, titulo.split()[-1].title(), peso=2.8), _c("solicitado", "Solicitado", "int", True),
            _c("atendido", "Atendido", "int", True), _c("pct_atendido", "% atendido", "pct"),
            _c("em_aberto", "Em aberto", "int", True), _c("aguardando", "Aguard. aut.", "int", True),
            _c("termino_vencido", "Término vencido", "int", True)])
    ab = d[d["em_aberto"]].sort_values("idade_dias", ascending=False)
    if len(ab):
        ap.tabela("Solicitações em aberto há mais tempo", ab, [
            _c("cod_solicitacao", "Nº", peso=0.6), _c("obra_rotulo", "Obra", peso=2.4),
            _c("solicitante", "Solicitante", peso=1.6), _c("situacao", "Situação", peso=1.3),
            _c("data_cadastro", "Cadastro", "data"), _c("idade_dias", "Em aberto (d)", "int")])
    ap.notas("Como ler este relatório", [
        "Fonte: relatório de solicitações de serviço do Sienge (RPA do legado).",
        "Início e término são o período PREVISTO do serviço; a execução real não vem no relatório.",
        "Alertas configuráveis em Configurações (dias aguardando autorização e em aberto)."])
    return ap.salvar()


# ── Visão geral (relatório geral: todas as abas + uma página por vertical) ──
_COLS_PAN = [_c("compras", "Compras", "brl", True), _c("economia", "Economia pot.", "brl", True),
             _c("estoque", "Estoque", "brl", True), _c("contratos_saldo", "Contratos a medir", "brl", True),
             _c("contratos_vencido", "…vencidos", "brl", True), _c("sla_f1", "SLA compra", "pct", peso=0.8),
             _c("sla_f2", "SLA entrega", "pct", peso=0.8), _c("servicos_abertos", "Serv. abertos", "int", True, 0.8)]


def visao_geral(segmentos, obras, ini, fim, filtros_txt: str) -> bytes:
    from app.relatorios.apresentacao import AZUL, VERMELHO
    from app.services import visao_geral as vg
    areas = vg.carregar(segmentos, obras, ini, fim)
    ap = Apresentacao("Visão geral de Suprimentos", filtros_txt, "Todas as abas do painel", "Relatório geral")
    if not any(a.ok for a in areas.values()):
        return _vazio(ap, "Nenhuma fonte disponível (ou nada no seu escopo de acesso).")
    k = lambda a, campo, padrao=0: areas[a].kpis.get(campo, padrao) if areas[a].ok else padrao  # noqa: E731
    fontes = vg.fontes()
    pontos = vg.pontos_de_atencao(areas, fontes)
    ap.capa([("comprado no período", brl_curto(k("compras", "valor"))),
             ("contratos a medir", brl_curto(k("contratos", "saldo"))),
             ("em estoque", brl_curto(k("estoque", "valor"))),
             ("SLA compra | entrega", f"{pct(k('sla', 'pct_f1', np.nan), 0)} | {pct(k('sla', 'pct_f2', np.nan), 0)}")])
    ap.kpis("Sumário executivo", [
        ("Compras no período", brl_curto(k("compras", "valor")),
         f"economia potencial {brl_curto(k('compras', 'economia'))}"),
        ("Contratos: saldo a medir", brl_curto(k("contratos", "saldo")),
         f"{num(k('contratos', 'vencidos'))} vencidos ({brl_curto(k('contratos', 'saldo_vencidos'))})", "alerta"),
        ("Estoque", brl_curto(k("estoque", "valor")), f"{num(k('estoque', 'insumos'))} insumos com saldo"),
        ("SLA no prazo (compra | entrega)", f"{pct(k('sla', 'pct_f1', np.nan), 0)} | {pct(k('sla', 'pct_f2', np.nan), 0)}",
         f"{num(k('sla', 'vencidos_f1') + k('sla', 'vencidos_f2'))} itens vencidos em aberto", "alerta"),
        ("Serviços em aberto", num(k("servicos", "em_aberto")), f"{num(k('servicos', 'aguardando'))} aguardando autorização"),
        ("Adiantamento a abater", brl_curto(k("adiantamento", "saldo")),
         f"{brl_curto(k('adiantamento', 'saldo_mais_1_ano'))} há mais de 1 ano"),
    ], f"Fornecedores críticos: {num(k('avaliacao', 'a'))} ({k('avaliacao', 'periodo', '')}). Curva ABC "
       f"{k('curva_abc', 'ano', '')}: {brl_curto(k('curva_abc', 'valor'))} apropriados. Adiantamentos, avaliação e curva "
       "ABC não têm obra/vertical no Sienge: são sempre o total.")
    textos = [f"[{p['nivel'].upper()}] {p['area']}: {p['texto']}" for p in pontos]
    for i in range(0, len(textos), 5):
        ap.notas("Pontos de atenção" + (f" ({i // 5 + 1}/{(len(textos) + 4) // 5})" if len(textos) > 5 else ""),
                 textos[i:i + 5])
    ap.tabela("Atualização das fontes", fontes.assign(posicao=fontes["posicao"].dt.strftime("%d/%m/%Y %H:%M")), [
        _c("fonte", "Fonte", peso=2.2), _c("posicao", "Posição", peso=1.2), _c("situacao", "Situação", peso=1),
        _c("detalhe", "Detalhe", peso=3)], total=False)

    seg = vg.panorama(areas, "segmento")
    if len(seg):
        seg = seg[(seg[["compras", "estoque", "contratos_saldo", "servicos_abertos", "sla_vencidos"]].sum(axis=1) > 0)]
        ap.tabela("Panorama por vertical", seg, [_c("segmento", "Vertical", peso=1.6)] + _COLS_PAN)
        ap.barras("Compras no período por vertical", seg["segmento"].tolist(), seg["compras"].tolist())
        ap.barras("Contratos a medir por vertical (vermelho = parte vencida > 25%)", seg["segmento"].tolist(),
                  seg["contratos_saldo"].tolist(),
                  cores_pontos=[VERMELHO if v > 0.25 * t else AZUL for v, t in
                                zip(seg["contratos_vencido"], seg["contratos_saldo"].replace(0, np.nan).fillna(1))])
    obra = vg.panorama(areas, "cod_obra")
    if len(obra):
        obra = obra.assign(obra=obra["cod_obra"].astype("Int64").astype(str) + " - " +
                           obra["nome"].fillna("").astype(str).str.replace(r"^\d+\s*-\s*", "", regex=True))
        for v in seg["segmento"].tolist() if len(seg) else []:
            o = obra[obra["segmento"] == v]
            linha = seg[seg["segmento"] == v].iloc[0]
            ap.kpis(f"Vertical {v}", [
                ("Compras no período", brl_curto(linha["compras"]), f"economia potencial {brl_curto(linha['economia'])}"),
                ("Estoque", brl_curto(linha["estoque"]), f"{num(len(o))} obra(s) com movimento"),
                ("Contratos a medir", brl_curto(linha["contratos_saldo"]), f"vencidos {brl_curto(linha['contratos_vencido'])}",
                 "alerta" if linha["contratos_vencido"] else None),
                ("SLA compra", pct(linha["sla_f1"], 0), "no prazo", "alerta" if linha["sla_f1"] < 70 else "bom"),
                ("SLA entrega", pct(linha["sla_f2"], 0), "no prazo", "alerta" if linha["sla_f2"] < 70 else "bom"),
                ("Itens vencidos | serviços em aberto", f"{num(linha['sla_vencidos'])} | {num(linha['servicos_abertos'])}",
                 "SLA de insumos | serviços"),
            ])
            if len(o):
                ap.tabela(f"Vertical {v} — obras (maiores compras)", o, [_c("obra", "Obra", peso=2.6)] + _COLS_PAN)

    # ── destaques de cada área ──
    if areas["compras"].ok and len(areas["compras"].kpis.get("_ops", [])):
        ops = areas["compras"].kpis["_ops"].sort_values("impacto", ascending=False)
        ap.tabela("Compras: maiores oportunidades de negociação", ops, [
            _c("material", "Material", peso=3), _c("fornecedor", "Fornecedor", peso=2), _c("obra", "Obra", peso=2),
            _c("diferenca_pct", "Dif.", "pct", peso=0.7), _c("impacto", "Economia pot.", "brl", True)],
            "Estimativa: (preço − referência comparável) × volume. Não é economia negociada.")
    if areas["contratos"].ok:
        v = areas["contratos"].dados
        v = v[v["vencido_com_saldo"]].sort_values("saldo_aberto", ascending=False)
        if len(v):
            ap.tabela("Contratos: vencidos com saldo a medir", v, [
                _c("numero_contrato", "Contrato", peso=1), _c("fornecedor_rotulo", "Fornecedor", peso=2.4),
                _c("obra_rotulo", "Obra", peso=2.2), _c("data_termino", "Término", "data"),
                _c("saldo_aberto", "Saldo a medir", "brl", True)])
    if areas["sla"].ok:
        from app.services import sla
        d = areas["sla"].dados
        g = sla.por(d, "tipo_grupo", areas["sla"].kpis.get("contar", True))
        if len(g):
            ap.tabela("SLA de insumos por tipo de grupo", g, [
                _c("tipo_grupo", "Tipo", peso=2.2), _c("n_f1", "Itens F1", "int", True), _c("pct_f1", "% F1", "pct"),
                _c("atrasados_f1", "Vencidos F1", "int", True), _c("n_f2", "Pedidos F2", "int", True),
                _c("pct_f2", "% F2", "pct"), _c("atrasados_f2", "Vencidos F2", "int", True),
                _c("pct_entregue_apos_obra", "Após data obra", "pct")],
                " · ".join(areas["sla"].kpis.get("gargalos", [])[:2]))
    if areas["servicos"].ok:
        from app.services import servicos as sv
        t = sv.por(areas["servicos"].dados, "obra_rotulo")
        if len(t):
            ap.tabela("Serviços: pendências por obra", t, [
                _c("obra_rotulo", "Obra", peso=2.8), _c("solicitado", "Solicitado", "int", True),
                _c("pct_atendido", "% atendido", "pct"), _c("em_aberto", "Em aberto", "int", True),
                _c("aguardando", "Aguard. aut.", "int", True), _c("termino_vencido", "Término vencido", "int", True)])
    if areas["estoque"].ok:
        from app.services import estoque as es
        e = es.por(areas["estoque"].dados, "centro_rotulo")
        ap.tabela("Estoque: centros de custo com mais valor", e, [
            _c("centro_rotulo", "Centro de custo", peso=3), _c("posicoes", "Itens", "int", True),
            _c("valor", "Valor", "brl", True), _c("pct", "% do valor", "pct", True)])
    if areas["adiantamento"].ok:
        from app.services import adiantamento as ad
        c = ad.por_credor(areas["adiantamento"].dados)
        c = c[c["saldo"] > 0.01]
        if len(c):
            ap.tabela("Adiantamentos: credores com maior saldo a abater", c, [
                _c("credor", "Credor", peso=3), _c("documentos", "Docs", "int", peso=0.6),
                _c("adiantado", "Adiantado", "brl"), _c("saldo", "Saldo a abater", "brl", True),
                _c("maior_idade", "Maior idade (d)", "int")])
    if areas["avaliacao"].ok and len(areas["avaliacao"].dados):
        ap.tabela(f"Fornecedores críticos ({areas['avaliacao'].kpis['periodo']})", areas["avaliacao"].dados, [
            _c("rotulo", "Fornecedor", peso=3), _c("nota", "Nota", "num2", peso=0.6),
            _c("avaliacoes", "Avaliações", "int"), _c("valor_comprado", "Comprado (pedidos)", "brl", True)])
    if areas["curva_abc"].ok:
        r = areas["curva_abc"].dados
        al = r[r["classe"].isin(["A", "B"]) & (r["var_preco_pct"] > 0)].sort_values("efeito_preco", ascending=False)
        if len(al):
            ap.tabela(f"Curva ABC {areas['curva_abc'].kpis['ano']}: insumos A/B que mais encareceram", al, [
                _c("insumo", "Insumo", peso=3.2), _c("classe", "Classe", peso=0.5), _c("valor", "Valor no ano", "brl"),
                _c("var_preco_pct", "Var. preço", "pct", peso=0.7), _c("efeito_preco", "Efeito preço", "brl", True)])
    ap.notas("Como ler este relatório", [
        "Os números são os mesmos das abas do painel, com os filtros e o escopo de acesso de quem gerou.",
        "Vertical e obra filtram compras, oportunidades, estoque, contratos, SLA e serviços; adiantamentos, avaliação "
        "e curva ABC não têm obra no Sienge e entram sempre no total.",
        "Período vale para compras, SLA e serviços; estoque e saldos são a posição da última carga (ver Fontes).",
        "Economia potencial é estimativa; SLA conta o backlog vencido conforme Configurações."])
    return ap.salvar()


# ── permissão: todo relatório exige a ação "gerar_relatorio" (o botão já fica desabilitado sem ela) ──
def _exigindo_permissao(fn):
    import functools

    @functools.wraps(fn)
    def envolvido(*args, **kwargs):
        from app.seguranca import sessao
        sessao.exigir("gerar_relatorio")
        return fn(*args, **kwargs)
    return envolvido


for _nome in ("oportunidades", "comparativo", "historico", "correspondencias", "busca", "curva_abc", "adiantamento",
              "avaliacao", "estoque", "contratos", "sla_insumos", "servicos", "visao_geral"):
    if _nome in globals():
        globals()[_nome] = _exigindo_permissao(globals()[_nome])
