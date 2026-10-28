// O nome do cache muda junto com a lista: um service worker antigo em campo continua servindo o
// cache velho ate ativar, e "copyecola-v4" guardava o brasao e o laranja que nao existem mais.
// "-v2" porque `marca.png` deixou de existir: `addAll` e tudo ou nada, entao um endereco que da 404
// nao deixa NADA ser guardado e o app inteiro fica sem cache offline, em silencio.
const CACHE = "subidocla-v2";
const ESTATICOS = [
  "/static/style.css",
  "/static/kanban.js",
  // As duas marcas, e nao so a do tema atual: quem instalou o app no claro pode trocar para o
  // escuro sem rede, e ai a outra precisa ja estar guardada.
  "/static/marca-no-claro.png",
  "/static/marca-no-escuro.png",
  "/static/icone-192.png",
  "/static/icone-512.png",
];

// Esta pagina nasce aqui dentro, sem Jinja e sem CSS do app: ela e justamente o que aparece quando
// nada carrega. Por isso as cores estao escritas na mao, e sao as do tema claro, que e o padrao.
const SEM_REDE =
  '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width, initial-scale=1">' +
  "<title>Sem conexão</title><style>body{margin:0;min-height:100vh;display:flex;" +
  "align-items:center;justify-content:center;background:#f4f6fb;color:#131722;" +
  "font-family:system-ui,sans-serif;text-align:center;padding:24px}b{color:#013cda}" +
  "</style></head><body><div><h1>Sem conexão</h1><p>O <b>Subido Clã</b> precisa de internet " +
  "para mostrar os pontos do clã. Tente de novo em instantes.</p></div></body></html>";

self.addEventListener("install", function (ev) {
  ev.waitUntil(
    caches
      .open(CACHE)
      .then(function (cache) {
        return cache.addAll(ESTATICOS);
      })
      .then(function () {
        return self.skipWaiting();
      })
  );
});

self.addEventListener("activate", function (ev) {
  ev.waitUntil(
    caches
      .keys()
      .then(function (nomes) {
        return Promise.all(
          nomes
            .filter(function (nome) {
              return nome !== CACHE;
            })
            .map(function (nome) {
              return caches.delete(nome);
            })
        );
      })
      .then(function () {
        return self.clients.claim();
      })
  );
});

self.addEventListener("fetch", function (ev) {
  const pedido = ev.request;
  if (pedido.method !== "GET") return;
  const url = new URL(pedido.url);
  if (url.origin !== self.location.origin) return;

  // O video sai daqui ANTES da regra de /static/, e sai sem respondWith: quem trata e o navegador,
  // direto, como se este service worker nao existisse.
  //
  // Sao dois problemas, e cada um sozinho ja bastaria. O primeiro e tamanho: a regra abaixo guarda
  // toda resposta ok de /static/, e o tutorial tem 21 MB. Cada pessoa que assistisse ficaria com a
  // gravacao inteira no armazenamento do navegador, para um video que se ve uma vez.
  //
  // O segundo e mais silencioso. Player de video nao baixa o arquivo de uma vez: ele pede pedaco
  // por pedaco, com Range, e cada pedaco volta 206. `cache.put` RECUSA 206, e a recusa e uma
  // promessa rejeitada que ninguem esta esperando ali em cima, entao ela vira erro nao tratado no
  // console a cada pedaco, sem nada quebrar de forma visivel. Tirar o video da frente resolve os
  // dois de uma vez, e de quebra devolve ao navegador o controle do Range, que e o que faz o
  // arrastar da barra do player pular direto para o minuto pedido em vez de baixar ate la.
  if (url.pathname.endsWith(".mp4")) return;

  // Rede primeiro mesmo no estatico: cache primeiro deixaria o CSS velho de pe apos um deploy.
  if (url.pathname.startsWith("/static/")) {
    ev.respondWith(
      fetch(pedido)
        .then(function (resposta) {
          if (resposta.ok) {
            const copia = resposta.clone();
            caches.open(CACHE).then(function (cache) {
              cache.put(pedido, copia);
            });
          }
          return resposta;
        })
        .catch(function () {
          // ignoreSearch: a pagina pede style.css?v=123 e no cache ele esta sem o ?v=.
          // Sem isso o app ficaria sem css quando estivesse offline.
          return caches.match(pedido, { ignoreSearch: true });
        })
    );
    return;
  }

  // Pagina nunca vai para o cache: ela carrega dado de quem esta logado.
  ev.respondWith(
    fetch(pedido).catch(function () {
      return new Response(SEM_REDE, {
        status: 503,
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    })
  );
});
