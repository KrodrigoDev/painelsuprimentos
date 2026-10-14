# Painel de Suprimentos

App Dash que **consome** o DW `dw_sienge`. Ele não extrai nada da API: quem carrega o schema `suprimentos` é a DAG `etl_pedidos_compra` do projeto **airflow_api_sienge**.

```
API Sienge / RPA ──(airflow_api_sienge: extract → transformer → transformer_2)──► dw_sienge.suprimentos
                     transformer_2 faz o processamento PESADO: catálogo de equivalências,           │
                     preços comparáveis, atípicos, referências, oportunidades, contratos…          │
                                              painelsuprimentos (este app) ◄───────────────────────┘
                                              só lê, filtra e plota + login/perfis/decisões (schema `painel`)
```

## Como rodar (Windows, PowerShell, na raiz do projeto)

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # ajuste DATABASE_URL / DW_SCHEMA
alembic upgrade head            # schema `painel` (0001 buscas, 0002 catálogo, 0003 usuários/perfis, 0004 configurações, 0005 visão geral)
python -m scripts.criar_admin   # 1º administrador (pergunta login, nome e senha — a senha nunca fica em arquivo)
python -m scripts.seed_mock     # (opcional) cria/recarrega o mock em suprimentos_mock
python run.py                   # http://localhost:8050  -> tela de login
pytest -q                       # 86 testes (motor, filtros de oportunidades, escopo/acesso, contratos, RPA, pptx)
```

O catálogo de equivalências e as oportunidades **não são mais calculados aqui**: rodam no ETL
(`python main.py --etapa inteligencia_compras` no airflow_api_sienge, ou as DAGs `etl_pedidos_compra` /
`etl_inteligencia_compras`). `scripts/processar_equivalencias.py` só avisa isso.

`.env` também precisa de `PAINEL_SECRET_KEY` (assina o cookie de sessão; gere com
`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Opcionais: `PAINEL_SESSAO_HORAS` (padrão 10),
`PAINEL_COOKIE_SEGURO=true` quando estiver atrás de HTTPS.

```powershell
python -m scripts.avaliar_motor # precisão/revocação do motor contra pares rotulados
```

## Mock x dados reais

| `DW_SCHEMA` no `.env` | De onde vem |
|---|---|
| `suprimentos_mock` | `scripts/seed_mock.py`: insumos, obras, fornecedores, datas e quantidades **reais** (CSVs em `data/input/painel_compras`), **preços sintéticos** |
| `suprimentos` | Dados reais da DAG `etl_pedidos_compra` |

O layout das tabelas é o mesmo nos dois (`app/models/dw.py` espelha `repo/sql/suprimentos.sql`). Para trocar, basta mudar o `.env` e reiniciar. Quando está no mock, a tela mostra o selo **DADOS MOCKUP**.

## Estrutura

```
app/
  config.py                 .env → Settings
  db.py                     engine + schema_translate_map (suprimentos → DW_SCHEMA)
  models/dw.py              tabelas do DW (só leitura; espelho do DDL do ETL)
  models/painel.py          tabelas do app (Alembic)
  repositories/             consultas SQLAlchemy
  services/similaridade.py  busca por similaridade POR CATEGORIA
  services/saving.py        KPIs e agrupamentos (pandas puro, testável)
  components/               UI e gráficos reutilizáveis
  pages/possivel_saving.py  busca por similaridade (/busca)
  pages/curva_abc.py        Curva ABC - Insumo (/curva-abc)
  pages/adiantamento.py     Adiantamento (/adiantamento)
  pages/avaliacao_fornecedor.py  Avaliação fornecedor (/avaliacao-fornecedor)
  pages/estoque.py          Estoque (/estoque)
  relatorios/               botão 'Gerar relatório' (PowerPoint, python-pptx)
  components/detalhe.py     janela de decomposição dos cards (PDF/CSV)
  exportacao.py             geração de PDF (reportlab) e CSV
alembic/                    migrações do schema `painel`
scripts/seed_mock.py        gera o mock
tests/
```

## Possível saving: como funciona

1. **Categoria** = grupo de insumo. Se você não souber a categoria, digite o item e clique em Buscar sem escolher categoria: a tela sugere itens de todas as categorias, e clicar num deles define a categoria.
2. **Similaridade**: só roda dentro da categoria (índice TF-IDF em memória por categoria, criado sob demanda). O score combina:
   - 50% TF-IDF por palavras;
   - 30% TF-IDF por trechos de caracteres (tolera erro de digitação e abreviação);
   - 20% rapidfuzz `token_set_ratio`;
   - penalidade quando uma medida digitada (2,5 mm, 50 kg…) não aparece no item.
3. Os itens similares **na mesma unidade** do mais parecido já vêm marcados. A comparação usa uma única unidade, porque não faz sentido comparar R$/kg com R$/saco.
4. Indicadores:
   - **Total gasto**, **preço médio ponderado** (Σ valor / Σ quantidade), **menor** e **maior** preço, número de fornecedores, obras e pedidos;
   - **Possível saving (menor preço do mês)** = Σ (preço − menor preço praticado no mesmo mês) × quantidade. É a referência principal porque respeita a variação de preço ao longo do ano;
   - **Saving teórico** (menor preço do período) e **valor pago acima da média**.
5. Tabelas por compra, obra, fornecedor, mês e insumo, com menor preço por obra, por fornecedor e no mês. Cada aba pode ser exportada em CSV.

## Limitações conhecidas (fonte)

Os endpoints `purchase-orders` e `items` **não trazem número da solicitação nem nota fiscal**. Para essas colunas, o ETL precisará depois dos endpoints `purchase-requests` e `purchase-invoices`.

## Inteligência de Compras (menu lateral)

| Tela | Rota | Para quê |
|---|---|---|
| Oportunidades | `/` | ranking explicável, economia potencial **estimada** sem dupla contagem, evidências (pedido de referência) |
| Comparativo de fornecedores | `/comparativo?grupo=` | todas as compras do material + equivalentes, referência, diferenças, o que não é comparável |
| Histórico de preços | `/historico?grupo=` | evolução por fornecedor/obra, mediana/mínimo/média, atípicos (mediana/MAD) |
| Correspondências | `/correspondencias` | fila de revisão, aprovar/rejeitar, histórico, comparação manual, conflitos técnicos, vocabulário |
| Busca por similaridade | `/busca` | busca livre com checagem técnica do motor |

Detalhes das regras, da validação e das limitações: [`docs/inteligencia_compras.md`](docs/inteligencia_compras.md).
Visual: `app/assets/01_construview_base.css` (identidade fornecida) + `10_inteligencia.css`.

## Painéis a partir dos relatórios do RPA (Curva ABC, Adiantamento, Avaliação de fornecedores e Estoque)

O projeto legado `etl_sienge` continua só com o **extract** (RPA/Selenium). A transformação e a carga
foram migradas para o `airflow_api_sienge` (DAG `etl_suprimentos_rpa`, ou `python main.py --etapa adiantamento`
/ `--etapa curva_abc` / `--etapa avaliacao_fornecedor` / `--etapa estoque`), que grava no schema `suprimentos`:

| Tabela | Grão | Conferência |
|---|---|---|
| `fato_adiantamento` (+ `dim_empresa`) | 1 movimentação | Σ saldo = "Total de adiantamentos" de cada relatório |
| `fato_curva_abc_insumo` | ano × tabela × insumo/detalhe | Σ preço total = "Total geral" de cada ano |
| `fato_estoque_posicao` | centro de custo × insumo × detalhe × marca | Σ custo de cada página = linha de total da página |
| `fato_avaliacao_fornecedor` | fornecedor × mês | Σ avaliações e média = totais de cada mês |
| `ctl_arquivo_adiantamento`, `ctl_arquivo_curva_abc`, `ctl_arquivo_avaliacao` | 1 arquivo | resultado da conferência (aparece no topo da tela) |

Se a soma não bater, a carga é abortada e o banco mantém a anterior.

Telas:

* **Curva ABC - Insumo** (`/curva-abc`): KPIs do ano, curva ABC do recorte, valor por grupo, ranking (clique abre o
  insumo) e a análise do insumo como no relatório (preço médio, quantidade, variação anual, tabela por ano e detalhes).
  A variação de preço compara **o mesmo detalhe na mesma unidade** nos dois anos (sem efeito de mix); a do preço médio
  "como no relatório" também aparece na tabela.
* **Adiantamento** (`/adiantamento`): adiantado, abatido, saldo a abater (posição na data final), credores com saldo,
  saldo há mais de 1 ano, contrato × pedido, por empresa, evolução mensal, exposição por credor, idade do saldo,
  documentos com saldo (clique = movimentações) e todas as movimentações.

**Cards clicáveis**: em Oportunidades, Curva ABC e Adiantamento, clicar num card abre a decomposição (tabela com total)
com **Exportar PDF** e **Exportar CSV** (o CSV abre direto no Excel: `;` e vírgula decimal).
* **Avaliação fornecedor** (`/avaliacao-fornecedor`): escala 0 a 4 — **A até 2,0 (crítico)**, B de 2,1 a 3,4,
  C de 3,5 a 4,0 (nota arredondada a 1 casa). "Classificar pela": pior mês no período (padrão = critério do Power BI),
  média ponderada, última avaliação ou nota acumulada do Sienge. KPIs clicáveis, avaliações e nota por mês, fornecedores
  por classe, nota × valor comprado (pedidos da API) e a grade fornecedor × mês com avaliações, média e delta (vs mês
  avaliado anterior). Clique num fornecedor = histórico completo.
* **Estoque** (`/estoque`): valor em estoque, insumos com saldo, concentração, abaixo do mínimo, inativos, por segmento,
  centro de custo e grupo (clique no grupo = itens), itens com saldo. O relatório do Sienge vem por apropriação: o valor
  soma as apropriações, a quantidade é o saldo físico (o legado somava e inflava ~1,8x). Página vazia do RPA = aviso
  vermelho de carga incompleta.

**Gerar relatório** (todas as abas): baixa um PowerPoint com capa, KPIs, gráficos nativos (editáveis) e tabelas dos
principais itens, com os filtros da tela no momento do clique.

* **Contratos** (`/contratos`): contratos em que a empresa é contratante — valor, medido, saldo a medir, vencidos com
  saldo, vencem em breve, aguardando autorização e valor não executado (encerrados); saldo por mês de término,
  contratado por mês, medido × saldo por segmento, maiores saldos por fornecedor e obra, valor por tipo. Cards
  clicáveis e clique no contrato = ficha completa. Fonte: `fato_contrato` (etapa `contrato` do ETL, conferida com a
  linha de total de cada arquivo).

## Processamento pesado no ETL (a tela só lê)

| O quê | Onde roda agora | Tabela que a tela lê |
|---|---|---|
| Catálogo de equivalências (perfis, candidatos, pontuação, grupos) | `airflow_api_sienge/repo/stage/transform/inteligencia/catalogo.py` | `painel.material_grupo`, `equivalencia_par`, `insumo_perfil` |
| Unidade-base, conversões, atípicos (mediana/MAD), referência de cada compra, excesso no mês | `.../inteligencia/analise.py` | `suprimentos.fato_compra_analise` |
| Oportunidades (5 tipos) para os níveis de confiança 85/90/95/100, com prioridade | `.../inteligencia/analise.py` | `suprimentos.fato_oportunidade_compra` |
| Contratos (transformação + conciliação + derivados) | `.../contrato_transformer(_2).py` | `suprimentos.fato_contrato` |

A tela aplica só os filtros e os limites escolhidos (diferença %, impacto, confiança) e refaz o “entra no total”
(sem dupla contagem) nas linhas filtradas. A janela de referência (180 dias) e as regras de atípico/aumento ficam em
`InteligenciaComprasConfig` (settings.py do ETL). Os filtros de período/obra/fornecedor escolhem oportunidades pela
**compra atual**; a referência pode ser de outra obra ou de fora do período (dentro da janela).
Decisões em Correspondências são gravadas na hora e entram nas comparações na próxima execução do ETL (de hora em hora).
`app/matching` continua no painel só para o uso interativo (comparar dois insumos); se mudar regras, mude os dois e
suba `VERSAO_REGRAS` — o menu avisa se a versão do ETL for diferente.

## Login, usuários e perfis

* `/login` (sessão em cookie assinado, HttpOnly, SameSite=Lax), `/logout`, `/trocar-senha`. Senha só como hash
  (werkzeug); senha provisória obriga a troca no 1º acesso; 5 erros bloqueiam por 15 min; tudo vai para
  `painel.auditoria_acesso`.
* **Perfil** = telas que abre + ações que pode executar + escopo de dados padrão. **Usuário** = perfil + escopo
  próprio opcional (cada dimensão preenchida substitui a do perfil). Tela `/admin` (ação `administrar_usuarios`).
* **Escopo de dados**: segmento/vertical, obra/centro de custo e empresa, aplicado no servidor em todas as leituras
  (pedidos, oportunidades, estoque, contratos, adiantamentos, busca). Dados sem a dimensão restrita (Curva ABC,
  Avaliação, catálogo) só aparecem com “dados sem a dimensão” = Sim.
* **Ações** hoje: exportar, gerar relatório, decidir/criar equivalência, editar vocabulário, administrar usuários.
  Ação nova (ex.: um POST para o Sienge): registre em `app/seguranca/catalogo.py` e chame
  `sessao.exigir("<acao>")` no callback.
* O guarda recusa (403) qualquer callback de tela não liberada, mesmo chamado direto, e (401) qualquer requisição sem
  sessão. Perfis-modelo da migração 0003: Administrador, Gestor de suprimentos, Consulta.

## SLA de insumos, Serviços e Configurações

* **SLA - Insumos** (`/sla-insumos`): fonte = painel de compras do Sienge (RPA, páginas de 5.000 linhas), etapa
  `sla_insumo` do ETL → `fato_sla_item` (item × pedido; 1ª e última entrega consolidadas) e `ref_sla_grupo_insumo`
  (prazos da planilha de grupos de insumo). Fase 1 = autorização da solicitação → 1º pedido do item; fase 2 =
  pedido → ÚLTIMA entrega (parcial = em aberto). KPIs por fase (mensuráveis, atendidos, não atendidos, vencidos em
  aberto, em risco, mediana real × prazo), entregas depois da data pedida pela obra, pontualidade do fornecedor vs
  previsão, gargalo por etapa (mediana e P80), % no prazo por mês, tabela por grupo/tipo/analista/comprador/
  fornecedor/obra/segmento e lista do backlog vencido. Diferenças para o Power BI: 1 contagem por item (o Power BI
  contava por nota fiscal) e o backlog vencido entra no % (parâmetro em Configurações).
* **Serviços** (`/servicos`): fonte = relatório de solicitações de serviço (etapa `servico`) → `fato_servico`.
  KPIs do Power BI + aguardando autorização há mais de N dias, em aberto com término previsto vencido, idade das
  pendências, pendências por obra/solicitante/autorizador, lista com alertas.
* **Configurações** (`/configuracoes`, ação `editar_configuracoes`): prazos de SLA por grupo (editáveis na grade;
  valem na hora — a comparação dias × prazo é feita na tela; a planilha continua sendo a referência), parâmetros
  das abas (alerta de risco do SLA, contar backlog vencido, alertas de serviços) e histórico de alterações.
  Parâmetro novo = nova entrada em `PARAMETROS` (`app/services/configuracoes.py`).

## Visão geral (início do menu)

`/visao-geral` resume todas as abas com os mesmos números delas (mesmas funções, mesmo escopo de acesso):

- **8 cards**, um por área: compras e oportunidades, estoque, contratos, SLA, serviços, adiantamentos, avaliação de fornecedores e curva ABC. Clicar num card abre a aba correspondente.
- **Pontos de atenção** em ordem de prioridade (alta, média, baixa), cada um com o link para a aba de origem.
- **Atualização das fontes**: data de posição e situação de cada carga. Fica marcada como desatualizada depois de 3 dias, e cargas incompletas ou divergentes também aparecem.
- **Panorama por vertical e por obra**: compras, economia potencial, estoque, contratos a medir e vencidos, SLA das fases 1 e 2, itens vencidos e serviços em aberto. Verticais e obras sem nenhum movimento ficam de fora.

Filtros:

- Vertical e obra filtram compras, oportunidades, estoque, contratos, SLA e serviços.
- Adiantamentos, avaliação e curva ABC não têm obra no Sienge, por isso aparecem sempre no total.
- O período vale só para fluxos (compras, SLA, serviços). Estoque e saldos mostram a posição da última carga.
- Se uma fonte falha, só a área dela aparece como indisponível; o resto da tela continua.

**Gerar relatório** monta o panorama completo em PPTX: sumário, pontos de atenção, fontes, panorama por vertical e, para cada vertical, KPIs e as obras com maiores compras. Depois vêm os destaques de cada área: oportunidades, contratos vencidos, SLA por tipo, serviços, estoque, adiantamentos, fornecedores críticos e curva ABC.

A primeira carga leva cerca de 20 s, porque lê todas as fontes. Depois disso fica em cache (cerca de 2 s).


## Desempenho

- **Bases em cache com recarga em segundo plano** (`app/cache.py`). Quando o servidor sobe, `run.py` lê todas as bases numa thread (cerca de 20 s), antes do primeiro acesso. Depois de vencer o prazo (`CACHE_MINUTOS`), o painel continua servindo o dado anterior enquanto recarrega em segundo plano. Cada tabela tem trava própria: carregar uma não bloqueia as outras. Para desligar o aquecimento: `PAINEL_AQUECER=false`.
- **Compressão gzip** das respostas, sem dependência nova (`app/desempenho.py`). O JSON dos callbacks fica 8–15x menor. Para desligar: `PAINEL_GZIP=false`.
- **Janela dos cards** (`app/components/detalhe.py`):
  - as linhas ficam no servidor e o navegador guarda só um token; a exportação CSV/PDF lê do servidor e traz todas as linhas;
  - a tela usa AG Grid, que desenha só as linhas visíveis (até 3.000; o total no rodapé considera todas).
  - Antes iam 3–14 MB por clique.
- **Indicador global** (`assets/20_carregando.js`): enquanto o servidor processa, a tela mostra o que está carregando e bloqueia cliques e teclado, para evitar pedidos repetidos e troca de tela no meio do carregamento.
- **SLA e avaliação**: os cálculos por grupo foram vetorizados, com o mesmo resultado; por fornecedor, 15 s viraram 0,07 s.
- Use `DASH_DEBUG=false` fora do desenvolvimento. O modo debug carrega os scripts sem minificar e as ferramentas de desenvolvimento.
