self.addEventListener('push', event => {
  let value;
  try { value = event.data.json(); } catch (_) { value = {title:'X3 Monitor',body:'关注客户端开始活跃'}; }
  event.waitUntil(self.registration.showNotification(value.title || 'X3 Monitor', {
    body:value.body || '',tag:value.tag || 'activity',data:{url:'/'}
  }));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(windows=>{
    const existing=windows.find(w=>new URL(w.url).origin===self.location.origin);
    return existing?existing.focus():clients.openWindow('/');
  }));
});
