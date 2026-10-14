"""
Exportação das tabelas de decomposição (PDF e CSV).

Colunas descritas por uma lista de dicts:
    {"campo": "saldo", "rotulo": "Saldo", "formato": "brl", "total": True, "peso": 1.2}
formatos: texto | brl | brl4 | num | num2 | int | pct | data
"""
from __future__ import annotations

import io
import math
from datetime import date, datetime

import pandas as pd

from app.formatacao import brl, num, pct

AZUL = "#1B365D"
NUMERICOS = {"brl", "brl4", "num", "num2", "int", "pct"}


def formatar(valor, formato: str) -> str:
    if valor is None or (isinstance(valor, float) and math.isnan(valor)) or valor is pd.NaT:
        return ""
    try:
        if formato == "brl":
            return brl(float(valor), 2)
        if formato == "brl4":
            return brl(float(valor))
        if formato == "num":
            return num(float(valor), 0)
        if formato == "num2":
            return num(float(valor), 2)
        if formato == "int":
            return num(float(valor), 0)
        if formato == "pct":
            return pct(float(valor), 2)
        if formato == "data":
            return pd.Timestamp(valor).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(valor)
    return str(valor)


def totais(df: pd.DataFrame, colunas: list[dict]) -> dict:
    return {c["campo"]: float(pd.to_numeric(df[c["campo"]], errors="coerce").sum())
            for c in colunas if c.get("total") and c["campo"] in df}


def csv_bytes(df: pd.DataFrame, colunas: list[dict]) -> bytes:
    """CSV ';' e vírgula decimal (abre direto no Excel pt-BR), valores sem formatação de moeda."""
    out = pd.DataFrame({c["rotulo"]: df[c["campo"]] for c in colunas if c["campo"] in df})
    for c in colunas:
        if c.get("formato") == "data" and c["rotulo"] in out:
            out[c["rotulo"]] = pd.to_datetime(out[c["rotulo"]], errors="coerce").dt.strftime("%d/%m/%Y")
    return out.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig").encode("utf-8-sig")


def pdf_bytes(titulo: str, subtitulo: str, df: pd.DataFrame, colunas: list[dict], rodape: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    buf = io.BytesIO()
    pagina = landscape(A4)
    margem = 12 * mm
    doc = SimpleDocTemplate(buf, pagesize=pagina, leftMargin=margem, rightMargin=margem, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=titulo, author="Painel de Suprimentos")
    s_tit = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, textColor=colors.HexColor(AZUL), leading=18)
    s_sub = ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, textColor=colors.HexColor("#4A5568"), leading=11)
    s_cel = ParagraphStyle("c", fontName="Helvetica", fontSize=7.6, leading=9.2)
    s_num = ParagraphStyle("n", parent=s_cel, alignment=TA_RIGHT)
    s_cab = ParagraphStyle("h", parent=s_cel, fontName="Helvetica-Bold", textColor=colors.HexColor("#4A5568"),
                           fontSize=6.9)
    s_cab_n = ParagraphStyle("hn", parent=s_cab, alignment=TA_RIGHT)

    def esc(t: str) -> str:
        return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    cols = [c for c in colunas if c["campo"] in df]
    padrao = {"texto": 2.2, "brl": 1.5, "brl4": 1.4}
    pesos = [max(c.get("peso", 0) or 0, padrao.get(c.get("formato", "texto"), 1.0))
             if c.get("formato") in ("brl", "brl4") else c.get("peso", padrao.get(c.get("formato", "texto"), 1.0))
             for c in cols]
    larg_util = pagina[0] - 2 * margem
    larguras = [larg_util * p / sum(pesos) for p in pesos]

    dados = [[Paragraph(esc(c["rotulo"].upper()), s_cab_n if c.get("formato") in NUMERICOS else s_cab) for c in cols]]
    for r in df[[c["campo"] for c in cols]].itertuples(index=False):
        dados.append([Paragraph(esc(formatar(v, c.get("formato", "texto"))).replace("R$ ", "R$&nbsp;"),
                                s_num if c.get("formato") in NUMERICOS else s_cel) for v, c in zip(r, cols)])
    tot = totais(df, cols)
    tem_total = bool(tot)
    if tem_total:
        linha = []
        for i, c in enumerate(cols):
            if c["campo"] in tot:
                linha.append(Paragraph("<b>" + esc(formatar(tot[c["campo"]], c["formato"])) + "</b>", s_num))
            else:
                linha.append(Paragraph("<b>Total</b>" if i == 0 else "", s_cel))
        dados.append(linha)

    tabela = LongTable(dados, colWidths=larguras, repeatRows=1)
    estilo = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2 if tem_total else -1), [colors.white, colors.HexColor("#F6F8FB")]),
    ]
    if tem_total:
        estilo += [("LINEABOVE", (0, -1), (-1, -1), 1.0, colors.HexColor("#94A3B8")),
                   ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EEF2F7"))]
    tabela.setStyle(TableStyle(estilo))

    gerado = datetime.now().strftime("%d/%m/%Y %H:%M")

    def pagina_rodape(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(margem, 8 * mm, f"Painel de Suprimentos · gerado em {gerado}" + (f" · {rodape}" if rodape else ""))
        canvas.drawRightString(pagina[0] - margem, 8 * mm, f"página {doc_.page}")
        canvas.restoreState()

    doc.build([Paragraph(esc(titulo), s_tit), Spacer(1, 2), Paragraph(esc(subtitulo), s_sub), Spacer(1, 8), tabela],
              onFirstPage=pagina_rodape, onLaterPages=pagina_rodape)
    return buf.getvalue()


def nome_arquivo(titulo: str, extensao: str) -> str:
    import re
    import unicodedata
    base = unicodedata.normalize("NFKD", titulo.lower()).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:60] or "detalhe"
    return f"{base}_{date.today():%Y%m%d}.{extensao}"
