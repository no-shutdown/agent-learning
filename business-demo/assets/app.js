// getRandomValues also works on local-network HTTP, unlike randomUUID.
function operationKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}
function askConfirmation(form) {
  const dialog = document.getElementById('confirm-dialog');
  const address = form.querySelector('select[name=address_id]');
  document.getElementById('confirm-text').textContent = form.dataset.confirm + (address ? '\n目标地址：' + address.selectedOptions[0].textContent : '');
  return new Promise(resolve => {
    const accept = document.getElementById('confirm-accept');
    const cancel = document.getElementById('confirm-cancel');
    const finish = value => {dialog.close(); accept.onclick=null; cancel.onclick=null; dialog.oncancel=null; resolve(value);};
    accept.onclick=()=>finish(true); cancel.onclick=()=>finish(false);
    dialog.oncancel=e=>{e.preventDefault();finish(false);};
    dialog.showModal();
  });
}
const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]').value;
function toast(message) { const el = document.getElementById('toast'); el.textContent = message; el.classList.add('visible'); setTimeout(() => el.classList.remove('visible'), 6000); }
document.querySelectorAll('nav a').forEach(a => { if(a.pathname === location.pathname) a.classList.add('active'); });
document.querySelectorAll('form[data-api]').forEach(form => {
  let key = operationKey(), lastPayload = null;
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if(form.dataset.confirm && !(await askConfirmation(form))) return;
    let data = Object.fromEntries(new FormData(form));
    if(form.dataset.kind === 'order') data = {address_id: data.address_id, items:[{product_id:data.product_id, quantity:data.quantity}]};
    if(form.dataset.kind === 'product') data.active = form.elements.active.checked;
    const payload = JSON.stringify(data);
    if(lastPayload !== null && lastPayload !== payload) key = operationKey();
    lastPayload = payload;
    const button = form.querySelector('button'); button.disabled = true;
    try {
      const response = await fetch(form.dataset.api, {method:form.dataset.method || 'POST', headers:{'Content-Type':'application/json','X-CSRFToken':csrf(),'Idempotency-Key':key}, body:payload});
      const result = await response.json();
      if(!response.ok) throw new Error(result.error?.message || '操作失败');
      if(form.dataset.redirect === 'order') location.href = '/orders/' + result.data.id + '/';
      else if(form.dataset.redirect === 'reload') location.reload();
      else toast('操作已完成');
    } catch(error) { toast(error.message + '。如连接中断，请保持输入不变重试，或查看操作记录。'); button.disabled = false; }
  });
});
const chatForm = document.getElementById('chat-form');
if(chatForm) chatForm.addEventListener('submit', async e => {
  e.preventDefault(); const input = document.getElementById('chat-input'); const message = input.value.trim(); if(!message) return;
  const add = (text,role) => {const el = document.createElement('div'); el.className = 'bubble ' + role; el.textContent = text; document.getElementById('chat-log').appendChild(el); el.scrollIntoView({block:'nearest'});};
  add(message,'user'); input.value=''; const button = chatForm.querySelector('button'); button.disabled=true;
  try {const response = await fetch('/api/v1/assistant/chat', {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf()},body:JSON.stringify({message})}); const data=await response.json(); add(response.ok?data.reply:data.error.message,'assistant');}
  catch {add('连接失败，请检查网站与 Agent 服务。','assistant');}
  finally {button.disabled=false;input.focus();}
});
