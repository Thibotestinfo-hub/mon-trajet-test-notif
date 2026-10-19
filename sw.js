/* Service worker — Mon trajet
 *
 * Le push arrive SANS charge utile. Le worker va lire message.json, affiche la
 * notification et pose la pastille. Conséquence utile : le texte affiché est
 * toujours le dernier publié, même si le push a traîné.
 *
 * iOS impose d'afficher une notification à chaque push reçu (userVisibleOnly) :
 * en cas d'échec de lecture, on affiche quand même un message de repli.
 */

const VERSION = "v1";
const COQUE = ["./", "./index.html", "./manifest.webmanifest",
               "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(COQUE))
              .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

/* La coque en cache, le bulletin toujours sur le réseau. */
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (u.pathname.endsWith("message.json")) return;         // réseau direct
  if (e.request.method !== "GET") return;
  e.respondWith(
    caches.match(e.request, {ignoreSearch:true})
      .then(r => r || fetch(e.request))
  );
});

self.addEventListener("push", e => {
  e.waitUntil((async () => {
    let titre = "Mon trajet", corps = "Ouvrez pour voir le bulletin.";
    try{
      const r = await fetch("message.json?t=" + Date.now(), {cache:"no-store"});
      const b = await r.json();
      titre = b.titre;
      const l = (b.message || "").split("\n").filter(Boolean);
      corps = l.slice(0, 3).join("\n");
      if (b.arrivee) corps += `\nArrivée ${b.arrivee} au lieu de ${b.arrivee_nominale}.`;
    }catch(err){ /* repli ci-dessus */ }

    await self.registration.showNotification(titre, {
      body: corps,
      icon: "icon-192.png",
      badge: "icon-192.png",
      tag: "bulletin-matin",            // remplace, n'empile pas
      renotify: true,
      data: {url: "./"}
    });
    try{ await self.navigator.setAppBadge(1); }catch(err){}
  })());
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil((async () => {
    const cls = await self.clients.matchAll({type:"window", includeUncontrolled:true});
    for (const c of cls){ if ("focus" in c) return c.focus(); }
    return self.clients.openWindow("./");
  })());
});
