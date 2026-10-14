# Módulo de Inteligência de Compras — diagnóstico, regras e validação

Regras do motor: versão **2026.10.1** (`app/matching/config.py`).

## 1. Diagnóstico das fontes (validado no DW real em 11/10/2026)

| Fonte | Onde | O que tem |
|---|---|---|
| Itens de pedido | `suprimentos.fato_pedido_compra_item` | 37.716 itens, 10.886 pedidos, de 02/01 a 09/10/2026: insumo, quantidade, unidade, preço unitário e líquido, frete unitário, % IPI/ICMS/ISS, cotação |
| Pedido (cabeçalho) | `suprimentos.dim_pedido` | fornecedor, centro de custo, comprador, condição de pagamento, tipo de frete, datas |
| Insumo | `suprimentos.dim_insumo` | código + detalhe, descrição, categoria (grupo de insumo), unidade |
| Fornecedor | `suprimentos.dim_fornecedor` | nome e CNPJ (via `credores.csv`; 71 sem nome no relatório) |
| Obra / centro de custo | `suprimentos.dim_centro_custo` | obra, empreendimento, vertical |

**Ausente na fonte atual:**
- notas fiscais (XML/DANFE) e solicitações;
- marca/modelo, preenchidos raramente.

Por isso, o cruzamento pedido × NF (seção 5 do escopo) e os cenários de teste 9 e 13 ficam para quando o ETL trouxer `purchase-invoices` e `purchase-requests`. As telas mostram "NF não disponível na fonte atual".

**Problema real observado** (`relatorio_teste_dw.txt`):
- a busca antiga juntava telas soldadas Q92/Q113/Q138/Q166, com preço de R$ 4 a R$ 7.200 e um "saving" de 41%;
- "Almoço" aparecia de R$ 1,32 a R$ 6.631 na mesma unidade.

## 2. Arquitetura (sem nova extração, sem tocar no schema do ETL)

```
DW suprimentos (ETL, só leitura) ──► app/matching (normalização, atributos, pontuação, grupos)
                                         │  lote incremental: scripts/processar_equivalencias.py
                                         ▼
                         schema painel (Alembic 0002)
                         vocabulario · insumo_perfil · equivalencia_par · equivalencia_decisao
                         material_grupo · processamento_log
                                         │
                                         ▼
          app/services/inteligencia.py (base comparável, estatística robusta, oportunidades)
                                         │
                                         ▼
        Telas: Oportunidades · Comparativo · Histórico · Correspondências · Busca
```

## 3. Motor de correspondência

1. **Normalização** (`normalizacao.py`):
   - o original é preservado;
   - minúsculas, acentos e pontuação são padronizados;
   - números, frações, medidas e códigos são mantidos (`1,5mm²` vira `1.5 mm2`, `3/4''` vira `3/4 pol`);
   - normas NBR são removidas do texto comparado;
   - vocabulário padrão + vocabulário da tela.
2. **Atributos técnicos** (`atributos.py`), em três grupos:
   - **crítico** (divergência = conflito): diâmetro/DN/mm, polegadas, dimensões AxB, seção mm², MPa, tensão, corrente, kA, potência, polos, curva, CA-25/50/60, CP + adição + classe, AC-I/II/III, tela Q, brita, granulometria, furos, PN, SCH, ângulo, tamanho, nº, tipo-letra, série, linha (PVCH/PVCS…), variantes opostas (macho/fêmea, superior/inferior, com/sem…), tipo do material, números livres disjuntos;
   - **embalagem** (kg, l, m, m², qtd por caixa): só pesa quando a unidade de compra é de contagem;
   - **informativo** (cor, marca).
3. **Candidatos** (`pipeline.py`):
   - só dentro da categoria;
   - TF-IDF de caracteres com top-12 por insumo, mais textos idênticos;
   - 13 mil insumos viram cerca de 66 mil pares em vez de cerca de 88 milhões.
4. **Pontuação de 0 a 100**:
   - 15% edição + 25% tokens + 20% TF-IDF + 30% atributos + 10% unidade;
   - pesos ajustáveis em `config_matching.json`.
5. **Níveis**:

| Nível | Regra |
|---|---|
| `incompativel` | conflito técnico crítico (nenhuma pontuação compensa) |
| `nao_comparavel` | unidade ou embalagem sem conversão segura |
| `alta` | score ≥ 85 e sem atributo crítico de um lado só |
| `media` | score ≥ 65 → revisão humana |
| `baixa` | abaixo de 65 → não usado |

6. **Aprovação automática** (precisão primeiro): só `alta` **e** todas as condições abaixo:
   - sem palavras exclusivas de nenhum dos lados, salvo cor ou marca;
   - sem códigos ou siglas de um lado só;
   - sem "linha" comercial de um lado só;
   - descrição não genérica;
   - textos iguais, ou iguais descontando cor, ou ≥ 1 atributo crítico idêntico e texto ≥ 0,85.
7. **Grupos de material**:
   - só pares aprovados por pessoa ou auto-aprovados;
   - uniões que juntariam itens conflitantes por transitividade são recusadas.
8. **Catálogo**:
   - decisão humana é preservada enquanto o hash (descrição/unidade/categoria) não mudar; se mudar, o par vai para `revisar_mudanca`;
   - versão das regras gravada em cada par e cada decisão.
9. **Embeddings semânticos**: não adotados nesta etapa. O motor textual + atributos atingiu a precisão alvo. Embeddings exigem baixar um modelo local; recomendamos avaliar só nos pares que ficarem em `media`/`baixa` depois da revisão inicial.

## 4. Unidades

- Conversão só com relação conhecida: t↔kg; saco com X kg; barra com X m; caixa com N un; lata/galão com X l; caixa com X m², sempre **extraídos da descrição**.
- O resto aparece como "não diretamente comparável".

## 5. Oportunidades e economia

- **Fornecedor mais barato:**
  - preço atual = última compra do fornecedor;
  - referência = menor preço comparável de outro fornecedor a até 180 dias;
  - impacto = diferença × volume já comprado do fornecedor, uma hipótese de repetição.
- **Aumento sobre o histórico:**
  - última compra × mediana de ≥ 3 compras anteriores do mesmo fornecedor (≥ 10%);
  - só soma no total se não houver a oportunidade anterior para o mesmo material e fornecedor.
- **Diferença entre obras** e **volume/consolidação**: informativos, não somam.
- **Atípicos:**
  - critério: |z robusto| > 3,5 com n ≥ 5, ou preço acima de 5× / abaixo de 1/5 da mediana com n ≥ 3;
  - viram "conferir registro" e ficam fora de referências e somas.
- **Prioridade de 0 a 100, explicável:**
  - 35% impacto (escala log) + 15% diferença % + 15% recorrência + 20% confiança + 10% atualidade + 5% alternativas;
  - fica limitada a 59 se a confiança for < 90 ou o impacto < R$ 1.000.
- **Economia potencial ≠ negociada ≠ realizada.** O painel só mostra potencial estimado.

## 6. Validação do motor (descrições REAIS do catálogo Sienge)

- **Conjunto:** `tests/dados/pares_rotulados.csv`, com 160 pares estratificados (40 auto, 25 alta, 35 média, 30 conflitos com texto parecido, 15 não comparáveis, 15 baixa), rotulados na construção do motor. **Esses rótulos precisam ser confirmados pelo setor de Suprimentos.**
- **Política adotada:** cor diferente = equivalente para preço; tamanho de roupa/calçado diferente = não equivalente (conservador).

| Versão | Aprovação automática | Precisão auto | Falsos positivos | Revocação útil | Falsos conflitos |
|---|---|---|---|---|---|
| Linha de base (antes dos ajustes) | 38 | 89,5% | 4 | 91,7% | 0 |
| Final 2026.10.1 | 27 | **100%** | 0 | 93,1% | 0 |

- **Ressalva:** os ajustes foram feitos olhando esta amostra, então os 100% são otimistas.
- **Verificação independente:** três amostras novas de pares auto-aprovados foram revisadas (40, 40 e 50 pares). As duas primeiras ainda mostraram falsos positivos (disjuntor DR × comum, piso "OUT", porta corta-fogo anti-horário, fechadura banheiro), e as regras foram endurecidas. Na terceira (50 pares), nenhum falso positivo foi encontrado.
- **Tempo:** cerca de 0,7 ms por par; processamento completo de cerca de 10–20 s para 10–13 mil insumos.
- **Seguimento:** `python -m scripts.avaliar_motor --catalogo` passa a incluir as decisões humanas do banco. Elas são o conjunto de validação oficial daqui para frente.

## 7. Testes automatizados (`pytest -q`)

- 50 passam e 1 é pulado (NF/duplicidade de nota: sem fonte).
- Cobrem os cenários 1–8, 10–12, 14 e 15 do escopo: conflitos técnicos (cimento, aço, tubo, PN, revestimento, tela, cabo, disjuntor, brita, areia, ângulo, tipo de peça, macho/fêmea, com/sem, A3/A4), unidades e embalagens, conversões, transitividade, robustez a atípicos, ausência de dupla contagem, ressalvas comerciais, janela da referência, ausência de alternativa e baixa confiança.

## 8. Limitações e próximos passos

1. **NF e solicitações:** incluir `purchase-invoices` e `purchase-requests` no ETL para ativar o cruzamento pedido × NF (preço/quantidade faturados, frete, duplicidade, notas sem pedido).
2. **Demanda futura:** não existe na fonte. O impacto usa o volume histórico, sempre rotulado como hipótese.
3. **Revisão humana:** revisar a fila começando pelo maior "valor em jogo". Cada decisão melhora as comparações e o conjunto de validação.
4. **Automação:** agendar `scripts.processar_equivalencias` logo após a DAG `etl_pedidos_compra`.
5. **Usuário das decisões:** é registrado pelo login do Windows (`USERNAME`) ou `PAINEL_USUARIO`. Não há autenticação própria no painel.
