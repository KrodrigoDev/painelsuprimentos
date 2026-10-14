"""SLA de insumos e serviços — dados SINTÉTICOS (sem banco)."""
import numpy as np
import pandas as pd
import pytest

from app.services import servicos as sv
from app.services import sla


def linha(grupo=2001, s1="concluida", d1=5.0, i1=np.nan, s2="concluida", d2=10.0, i2=np.nan, item=True, obra=10,
          atraso_obra=np.nan, data="2026-03-01", comprador=None, distribuido="ANA"):
    return dict(id_grupo=grupo, grupo_insumo=f"G{grupo}", status_fase1=s1, dias_fase1=d1, idade_fase1=i1,
                status_fase2=s2, dias_fase2=d2, idade_fase2=i2, linha_do_item=item, cod_obra=obra, obra=f"{obra} - OBRA",
                data_solicitacao=pd.Timestamp(data), atraso_obra=atraso_obra, analista="X", comprador=comprador,
                comprador_distribuido=distribuido, fornecedor="F", tipo_grupo="Material de Consumo",
                dias_aprovacao_solicitacao=1.0, dias_autorizacao_pedido=1.0, dias_fornecedor=d2)


PRAZOS = pd.DataFrame({"id_grupo": [2001], "lt_fase1": [10.0], "lt_fase2": [15.0], "lt_total": [25.0],
                       "origem": ["planilha"]})


def prep(linhas, risco=80):
    return sla.preparar(pd.DataFrame(linhas), PRAZOS, risco)


def test_situacoes_por_fase():
    d = prep([linha(d1=5, d2=10), linha(d1=12, d2=20), linha(s1="aberta", d1=np.nan, i1=11, s2="sem_pedido"),
              linha(s1="aberta", d1=np.nan, i1=9, s2="sem_pedido"), linha(s1="aberta", d1=np.nan, i1=2, s2="sem_pedido"),
              linha(grupo=9999), linha(s1="cancelada", s2="cancelada")])
    assert d["f1"].tolist() == ["no_prazo", "fora_prazo", "atrasado", "em_risco", "aberto_no_prazo", "sem_prazo", "fora"]
    assert d["f2"].tolist()[:2] == ["no_prazo", "fora_prazo"]


def test_fase1_conta_uma_vez_por_item():
    d = prep([linha(), linha(item=False)])
    assert (d["f1"] != "fora").sum() == 1 and (d["f2"] != "fora").sum() == 2


def test_backlog_vencido_entra_no_percentual_quando_configurado():
    d = prep([linha(d1=5), linha(s1="aberta", d1=np.nan, i1=30, s2="sem_pedido")])
    assert sla.resumo_fase(d, "f1", True)["pct"] == pytest.approx(50)
    assert sla.resumo_fase(d, "f1", False)["pct"] == pytest.approx(100)    # critério do Power BI


def test_prazo_editado_muda_o_resultado_na_hora():
    d1 = sla.preparar(pd.DataFrame([linha(d1=12)]), PRAZOS)
    d2 = sla.preparar(pd.DataFrame([linha(d1=12)]), PRAZOS.assign(lt_fase1=15.0))
    assert d1["f1"].iat[0] == "fora_prazo" and d2["f1"].iat[0] == "no_prazo"


def test_comprador_distribuido_quando_nao_ha_pedido_e_tabela_por():
    d = prep([linha(comprador=None, distribuido="ANA"), linha(comprador="BIA")])
    assert set(d["comprador"]) == {"ANA", "BIA"}
    t = sla.por(d, "comprador").set_index("comprador")
    assert t.loc["ANA", "n_f1"] == 1


def test_abertos_atrasados_ordenados():
    d = prep([linha(s1="aberta", d1=np.nan, i1=30, s2="sem_pedido"), linha(s1="aberta", d1=np.nan, i1=50, s2="sem_pedido")])
    a = sla.abertos_atrasados(d)
    assert a["dias_alem_prazo"].tolist() == [40, 20]


def servicos_base():
    return pd.DataFrame({
        "cod_solicitacao": [1, 2, 3, 4], "cod_obra": [10, 10, 20, None], "obra": ["A", "A", "B", None],
        "solicitante": ["S1", "S1", "S2", None], "autorizador": ["X", "X", "Y", "Y"], "departamento": [None] * 4,
        "segmento": ["MCMV"] * 4, "situacao": ["Totalmente atendida", "Pendente", "Cancelada", "Pendente"],
        "situacao_autorizacao": ["Aprovada", "Aguardando autorização", "Aprovada", "Aprovada"],
        "data_cadastro": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-02-10", "2026-03-01"]),
        "em_aberto": [False, True, False, True], "idade_dias": [np.nan, 100, np.nan, 10],
        "aguardando_dias": [np.nan, 100, np.nan, np.nan], "termino_vencido": [False, True, False, False],
        "dias_previstos": [30, 60, 10, 20], "dias_cadastro_alteracao": [0, np.nan, 2, 1], "observacao": ["", "", "", ""]})


def test_servicos_resumo_e_alertas():
    d = sv.preparar(servicos_base(), dias_aut=7, dias_aberto=60)
    r = sv.resumo(d)
    assert r["solicitado"] == 4 and r["pendente"] == 2 and r["aguardando"] == 1
    assert r["pct_atendido"] == pytest.approx(100 / 3)          # canceladas fora da base
    assert r["alerta_aut"] == 1 and r["alerta_aberto"] == 1
    assert d.loc[d["cod_solicitacao"] == 2, "alerta"].iat[0].startswith("aguardando")
    assert sv.por(d, "obra_rotulo").set_index("obra_rotulo").loc["10 - A", "em_aberto"] == 1
