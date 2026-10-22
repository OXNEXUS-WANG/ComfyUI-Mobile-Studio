/* CometInk 彗墨 service worker —— 只为让浏览器允许"添加到主屏"，不做离线缓存 */
self.addEventListener("install", function (e) { self.skipWaiting(); });
self.addEventListener("activate", function (e) { self.clients.claim(); });
self.addEventListener("fetch", function (e) { /* 直通网络 */ });
