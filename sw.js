/* Service worker — Mon trajet
 *
 * Le push arrive SANS charge utile. Le worker va lire message.json, affiche la
 * notification et pose la pastille. Conséquence utile : le texte affiché est
 * toujours le dernier publié, même si le push a traîné.
 *
 * iOS impose d'afficher une notification à chaque push reçu (userVisibleOnly) :
 * en cas d'échec de lecture, on affiche quand même un message de repli.
 */

const VERSION = "v4";
// Seuls les fichiers qui ne changent jamais sont mis en cache d'avance.
// index.html en était, et c'était une erreur : la page restait figée sur
// l'ancienne version après chaque publication.
const COQUE = ["./manifest.webmanifest", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(COQUE))
              .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

/* Réseau d'abord pour la page et les données, cache seulement en secours.
 * L'inverse — le cache d'abord — fige l'app sur l'ancienne version après
 * chaque publication, et c'est très déroutant : on voit le dépôt à jour et
 * l'écran inchangé. Les icônes, elles, ne bougent jamais : cache d'abord. */
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const u = new URL(e.request.url);
  const fige = /\.(png|webmanifest)$/.test(u.pathname);

  if (fige){
    e.respondWith(caches.match(e.request, {ignoreSearch:true})
      .then(r => r || fetch(e.request)));
    return;
  }
  e.respondWith((async () => {
    try{
      const r = await fetch(e.request, {cache:"no-store"});
      if (r && r.ok && u.origin === self.location.origin){
        const c = await caches.open(VERSION);
        c.put(e.request, r.clone());        // copie de secours, hors ligne
      }
      return r;
    }catch(err){
      const c = await caches.match(e.request, {ignoreSearch:true});
      if (c) return c;
      throw err;
    }
  })());
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
      const d = new Date(b.genere);
      const h = d.toLocaleTimeString("fr-FR", {hour:"2-digit", minute:"2-digit"});
      // Un bulletin « trafic normal » ne produit aucune ligne : iOS exige
      // malgré tout un corps, sans quoi la notification passe inaperçue.
      if (!corps.trim()) corps = `Rien à signaler sur votre trajet. Relevé de ${h}.`;
      // Notification retardée (téléphone éteint, réseau faible) : on date le
      // relevé plutôt que de le faire passer pour l'instant présent.
      else if (Date.now() - d.getTime() > 20*60*1000) corps += `\n(relevé de ${h})`;
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
