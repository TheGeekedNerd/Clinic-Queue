// Minimal service worker. It lets the ticket page show notifications (Android Chrome requires one)
// and brings the ticket page to the front when a notification is tapped.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const path = event.notification.data && event.notification.data.path;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const open = windows.find((w) => new URL(w.url).pathname === path);
    if (open) return open.focus();
    if (path) return self.clients.openWindow(path);
  })());
});
