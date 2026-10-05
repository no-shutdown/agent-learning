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
if (chatForm) {
  const conversationId = operationKey();
  const input = document.getElementById('chat-input');
  const sendButton = chatForm.querySelector('button');
  let pending = false;
  const add = (text, role) => {
    const el = document.createElement('div');
    el.className = 'bubble ' + role;
    el.textContent = text;
    document.getElementById('chat-log').appendChild(el);
    el.scrollIntoView({block: 'nearest'});
    return el;
  };
  async function send(route, payload) {
    const response = await fetch('/api/v1/assistant/' + route, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
      body: JSON.stringify({conversation_id: conversationId, ...payload})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || '请求失败');
    return data;
  }
  function show(data) {
    add(data.reply, 'assistant');
    pending = data.status === 'confirmation_required';
    if (!pending) return;
    const box = add('', 'assistant');
    const details = document.createElement('pre');
    details.style.whiteSpace = 'pre-wrap';
    details.style.overflowWrap = 'anywhere';
    details.textContent = data.confirmation.description + '\n' + JSON.stringify(data.confirmation.arguments, null, 2) + '\n请在约 ' + Math.ceil(data.confirmation.expires_in_seconds) + ' 秒内确认，过期请取消后重新查询。';
    box.appendChild(details);
    const buttons = [true, false].map(accept => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = accept ? '确认执行' : '取消操作';
      const requestId = operationKey(); // 网络异常后保持编号，避免重复执行。
      button.onclick = async () => {
        buttons.forEach(b => b.disabled = true);
        try {
          const reply = await send('confirm', {request_id: requestId, confirmation_id: data.confirmation_id, accept});
          show(reply);
          box.remove();
        } catch (error) {
          add(error.message + '。可用原按钮重试；不要另开对话重复写入。', 'assistant');
          buttons.forEach(b => b.disabled = false);
        } finally {
          sendButton.disabled = pending;
          input.disabled = pending;
        }
      };
      box.appendChild(button);
      return button;
    });
  }
  chatForm.addEventListener('submit', async e => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message || pending) return;
    add(message, 'user'); input.value = '';
    sendButton.disabled = true; input.disabled = true;
    const payload = {message, request_id: operationKey()};
    try { show(await send('chat', payload)); }
    catch (error) {
      const box = add(error.message, 'assistant');
      const retry = document.createElement('button');
      retry.type = 'button'; retry.textContent = '重试原请求';
      retry.onclick = async () => {
        retry.disabled = true; sendButton.disabled = true; input.disabled = true;
        try { show(await send('chat', payload)); box.remove(); }
        catch (err) { add(err.message, 'assistant'); retry.disabled = false; }
        finally { sendButton.disabled = pending; input.disabled = pending; }
      };
      box.appendChild(retry);
    } finally { sendButton.disabled = pending; input.disabled = pending; if (!pending) input.focus(); }
  });
}
