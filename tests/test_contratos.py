"""Contratos: filtros e agregações (dados sintéticos)."""
import pandas as pd

from app.services import contratos as ct


def base():
    d = pd.DataFrame({
        "numero_contrato": ["CT/1", "CT/2", "CT/3", "CT/4"], "cod_fornecedor": [1, 2, 2, None],
        "fornecedor": ["A", "B", "B", None], "cod_obra": [15, 15, 20, 15], "obra": ["X", "X", "Y", "X"],
        "cod_empresa": [1, 1, 2, 1], "empresa": ["E1", "E1", "E2", "E1"], "segmento": ["MCMV", "MCMV", "PÚBLICA", "MCMV"],
        "tipo_contrato": ["T", "T", None, "T"], "situacao": ["Parcialmente medido", "Concluído", "Pendente", "Pendente"],
        "situacao_autorizacao": ["Aprovada", "Aprovada", "Aguardando autorização", "Aprovada"],
        "sit_empresa": ["Contratante", "Contratante", "Contratante", "Contratada"],
        "valor_total": [100.0, 50.0, 30.0, 999.0], "valor_medido": [40.0, 45.0, None, 0.0],
        "saldo": [60.0, None, 30.0, 999.0], "em_andamento": [True, False, True, True],
        "vencido_com_saldo": [True, False, False, False], "vence_em_breve": [False, False, True, False],
        "objeto": ["locação", "obra", "projeto", "cliente"],
        "data_contrato": pd.to_datetime(["2026-01-05", "2025-03-01", "2026-09-01", "2026-01-01"]),
        "data_termino": pd.to_datetime(["2026-08-01", "2025-12-01", "2026-10-20", "2027-01-01"]),
    })
    return ct.preparar(d)


def test_preparar_tira_contratos_de_cliente():
    assert "CT/4" not in set(base()["numero_contrato"])


def test_resumo():
    r = ct.resumo(base())
    assert r["contratos"] == 3 and r["valor_total"] == 180 and r["saldo"] == 90
    assert r["vencidos"] == 1 and r["saldo_vencidos"] == 60 and r["aguardando"] == 1
    assert r["nao_executado"] == 5                                    # concluído: 50 − 45


def test_filtros():
    d = base()
    assert ct.filtrar(d, obras=[20])["numero_contrato"].tolist() == ["CT/3"]
    assert ct.filtrar(d, texto="locaç")["numero_contrato"].tolist() == ["CT/1"]
    assert len(ct.filtrar(d, ini="2026-01-01")) == 2


def test_vencimentos_e_por():
    v = ct.vencimentos(base(), pd.Timestamp("2026-10-13"), meses=3).set_index("periodo")
    assert v.loc["Vencidos", "saldo"] == 60 and v.loc["10/2026", "saldo"] == 30
    p = ct.por(base(), "segmento").set_index("segmento")
    assert p.loc["MCMV", "saldo_vencido"] == 60 and p.loc["MCMV", "contratos"] == 2
