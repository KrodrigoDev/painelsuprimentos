// Indicador global de carregamento + bloqueio de novas ações enquanto o painel processa.
//
// Todo pedido ao servidor do Dash passa por fetch("_dash-update-component"). Enquanto houver algum
// pendente:
//   - imediatamente: uma camada transparente bloqueia cliques e teclado (evita pedidos repetidos
//     ou trocar de tela no meio de um carregamento);
//   - após 250 ms: mostra a camada esmaecida, a barra no topo e uma mensagem do que está acontecendo
//     (só aparece em operações que demoram, para não piscar a cada clique rápido).
(function () {
  if (window.__painelCarregando) return;
  window.__painelCarregando = true;

  var pendentes = 0, timerMostrar = null, timerEsconder = null, timerDemora = null, inicio = 0;
  var camada, msg, sub;

  function montar() {
    if (camada) return;
    camada = document.createElement("div");
    camada.id = "carregando-global";
    camada.setAttribute("role", "status");
    camada.setAttribute("aria-live", "polite");
    camada.innerHTML =
      '<div class="cg-barra"><span></span></div>' +
      '<div class="cg-caixa"><div class="cg-spinner"></div>' +
      '<div><div class="cg-msg">Carregando…</div><div class="cg-sub"></div></div></div>';
    document.body.appendChild(camada);
    msg = camada.querySelector(".cg-msg");
    sub = camada.querySelector(".cg-sub");
  }

  function mensagem(corpo) {
    var s = String(corpo || "");
    if (s.indexOf("rel-down") >= 0) return ["Gerando relatório…", "Pode levar até um minuto."];
    if (s.indexOf("-down.data") >= 0) return ["Preparando arquivo…", ""];
    if (s.indexOf("_pages_content") >= 0) return ["Abrindo a tela…", ""];
    if (s.indexOf("-dm-") >= 0) return ["Abrindo o detalhamento…", ""];
    if (s.indexOf("gaveta") >= 0) return ["Abrindo os detalhes…", ""];
    return ["Atualizando os dados…", ""];
  }

  function iniciar(corpo) {
    montar();
    pendentes += 1;
    clearTimeout(timerEsconder);
    if (pendentes === 1) {
      inicio = Date.now();
      var m = mensagem(corpo);
      msg.textContent = m[0];
      sub.textContent = m[1];
      document.body.classList.add("cg-bloqueado");
      camada.className = "ativo";                       // bloqueia já (invisível)
      timerMostrar = setTimeout(function () {
        if (pendentes > 0) camada.className = "ativo visivel";
      }, 250);
      timerDemora = setTimeout(function () {
        if (pendentes > 0 && !sub.textContent) sub.textContent = "Ainda processando, aguarde…";
      }, 6000);
    } else if (mensagem(corpo)[0] === "Gerando relatório…") {
      var r = mensagem(corpo); msg.textContent = r[0]; sub.textContent = r[1];
    }
  }

  function terminar() {
    pendentes = Math.max(0, pendentes - 1);
    if (pendentes > 0) return;
    // pequena folga: callbacks encadeados disparam logo em seguida — evita piscar entre eles
    timerEsconder = setTimeout(function () {
      if (pendentes > 0) return;
      clearTimeout(timerMostrar); clearTimeout(timerDemora);
      document.body.classList.remove("cg-bloqueado");
      if (camada) camada.className = "";
    }, 120);
  }

  var fetchOriginal = window.fetch.bind(window);
  window.fetch = function (recurso, opcoes) {
    var url = typeof recurso === "string" ? recurso : (recurso && recurso.url) || "";
    if (url.indexOf("_dash-update-component") < 0) return fetchOriginal(recurso, opcoes);
    iniciar(opcoes && opcoes.body);
    var p;
    try {
      p = fetchOriginal(recurso, opcoes);
    } catch (e) {
      terminar();
      throw e;
    }
    // segurança: nunca deixar a tela travada se uma resposta não voltar
    var guarda = setTimeout(terminar, 300000);
    return p.then(function (r) { clearTimeout(guarda); terminar(); return r; },
                  function (e) { clearTimeout(guarda); terminar(); throw e; });
  };

  // teclado também fica bloqueado durante o carregamento (Enter/Espaço disparariam botões e cards)
  document.addEventListener("keydown", function (e) {
    if (pendentes > 0 && document.body.classList.contains("cg-bloqueado")) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);
})();
