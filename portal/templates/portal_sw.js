// Service worker do app do Portal -- ver pwa_service_worker() em
// portal/app.py. Regra: só guarda o que é igual para todo mundo (logo,
// ícones, tela "sem conexão"). Página, dado e documento de cliente vão
// sempre direto à rede e nunca ficam no celular.
const VERSAO = {{ versao|tojson }};
const ARQUIVOS = {{ arquivos|tojson }};
const OFFLINE = {{ offline|tojson }};
const ESTATICOS = {{ estaticos|tojson }};

self.addEventListener("install", (evento) => {
  evento.waitUntil(caches.open(VERSAO).then((cache) => cache.addAll(ARQUIVOS)));
  self.skipWaiting();
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== VERSAO).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (evento) => {
  const pedido = evento.request;
  if (pedido.method !== "GET") return;

  // Abrir uma tela: sempre da rede. Sem internet, a tela "sem conexão".
  if (pedido.mode === "navigate") {
    evento.respondWith(fetch(pedido).catch(() => caches.match(OFFLINE)));
    return;
  }

  // Logo e ícones: do celular primeiro (não mudam e são iguais para todos).
  const url = new URL(pedido.url);
  if (url.origin === self.location.origin && url.pathname.startsWith(ESTATICOS)) {
    evento.respondWith(caches.match(pedido).then((guardado) => guardado || fetch(pedido)));
  }
  // Todo o resto (documentos, fotos de anúncio, consultas) segue o
  // caminho normal do navegador, sem passar por cache nenhum daqui.
});
