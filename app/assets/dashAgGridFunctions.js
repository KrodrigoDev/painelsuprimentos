// Funções usadas pelas grades (dash-ag-grid): {"function": "dataBR(params.value)"}
var dagfuncs = (window.dashAgGridFunctions = window.dashAgGridFunctions || {});

dagfuncs.dataBR = function (v) {
  if (!v) return "";
  var p = String(v).slice(0, 10).split("-");
  return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : String(v);
};

// Delta de nota com seta: ↑ 0,20 / ↓ -1,30 / 0,00
dagfuncs.deltaNota = function (v) {
  if (v === null || v === undefined || v === "") return "";
  var n = Number(v), t = n.toLocaleString("pt-BR", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  if (n > 0.0001) return "↑ " + t;
  if (n < -0.0001) return "↓ " + t;
  return t;
};

// Mesmo formato do Python (app/exportacao.formatar) para a janela de decomposição
function _brNum(v, casas) {
  return Number(v).toLocaleString("pt-BR", {minimumFractionDigits: casas, maximumFractionDigits: casas});
}
dagfuncs.fmtDm = function (v, fmt) {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "string" && isNaN(Number(v))) return v;          // ex.: "Total"
  var n = Number(v);
  if (fmt === "brl") return "R$ " + _brNum(n, 2);
  if (fmt === "brl4") return "R$ " + _brNum(n, Math.abs(n) < 10 && n !== 0 ? 4 : 2);
  if (fmt === "num" || fmt === "int") return _brNum(n, 0);
  if (fmt === "num2") return _brNum(n, 2);
  if (fmt === "pct") return _brNum(n, 2) + "%";
  return String(v);
};
