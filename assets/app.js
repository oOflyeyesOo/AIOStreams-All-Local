const providers = [
  ['PREMIUMIZE_API_KEY','Premiumize','P'],['REALDEBRID_API_KEY','Real-Debrid','R'],
  ['TORBOX_API_KEY','TorBox','T'],['ALLDEBRID_API_KEY','AllDebrid','A'],
  ['DEBRIDLINK_API_KEY','Debrid-Link','D'],['EASYDEBRID_API_KEY','EasyDebrid','E']
];
const metadata = [['TMDB_API_KEY','TMDB','T'],['TVDB_API_KEY','TVDB','TV'],['FANART_API_KEY','Fanart.tv','F'],['MDBLIST_API_KEY','MDBList','M']];
const extras = [['RPDB_API_KEY','Rating posters','RP'],['SUBDL_API_KEY','SubDL','S'],['SUBSOURCE_API_KEY','SubSource','SS'],['WYZIE_API_KEY','Wyzie','W'],['GEMINI_API_KEY','Gemini','G'],['OFFCLOUD_API_KEY','Offcloud','O'],['SEEDR_API_KEY','Seedr','S']];
const fields = [...providers,...metadata,...extras];
let currentManifest = '';
let currentAiometaManifest = '';
let pollTimer;
let lastJobStatus = 'idle';
let reconnectAttempts = 0;
const savedKeys = new Set();

function deriveAiometaHost(baseUrl) {
  if (!baseUrl) return '';
  try {
    const u = new URL(baseUrl);
    const h = u.hostname;
    if (!h || h === 'localhost' || h === '127.0.0.1' || h.startsWith('192.168.') || h.startsWith('10.')) {
      return `${u.protocol}//${h || 'localhost'}:4005`;
    }
    const parts = h.split('.');
    if (['aio', 'aiostreams', 'stremio'].includes(parts[0])) {
      parts[0] = 'aiometa';
      return `${u.protocol}//${parts.join('.')}`;
    }
    return `${u.protocol}//aiometa.${h}`;
  } catch {
    return '';
  }
}

function renderFields(id, values) {
  const target = document.getElementById(id);
  for (const [key,label,icon] of values) {
    const wrapper = document.createElement('label');
    wrapper.htmlFor = key;
    const title = document.createElement('span');
    title.className = 'field-label';
    const name = document.createElement('span');
    name.className = 'field-title';
    const mark = document.createElement('span');
    mark.className = 'provider-icon'; mark.textContent = icon;
    name.append(mark, document.createTextNode(label));
    const saved = document.createElement('small');
    saved.id = `${key}-saved`; saved.className = 'saved-indicator';
    title.append(name,saved);
    const remove = document.createElement('button');
    remove.type = 'button'; remove.id = `${key}-remove`; remove.className = 'clear-key';
    remove.textContent = '×'; remove.hidden = true;
    remove.setAttribute('aria-label',`Remove saved ${label} key`);
    remove.addEventListener('click',event=>{
      event.preventDefault();
      savedKeys.delete(key); saved.textContent = ''; remove.hidden = true;
      input.value = ''; input.placeholder = 'Paste API key';
    });
    title.append(remove);
    const input = document.createElement('input');
    input.id = key; input.name = key; input.type = 'password';
    input.placeholder = 'Paste API key'; input.autocomplete = 'off'; input.spellcheck = false;
    wrapper.append(title,input); target.append(wrapper);
  }
}
renderFields('provider-fields',providers);
renderFields('metadata-fields',metadata);
renderFields('extra-fields',extras);

async function api(path, options, attempt=0) {
  try {
    const response = await fetch(new URL(path,location.origin).href, options);
    if (!response.ok) {
      const error = new Error(response.status === 401 ? 'Sign in with your portal password, then retry.' : `The server returned ${response.status}. Check setup details and retry.`);
      error.status = response.status;
      throw error;
    }
    return await response.json();
  } catch(error) {
    const readOnly = !options?.method || options.method === 'GET';
    if (readOnly && attempt < 2 && (!error.status || error.status >= 500)) {
      await new Promise(resolve=>setTimeout(resolve,500*(attempt+1)));
      return api(path,options,attempt+1);
    }
    throw error;
  }
}
function notify(message) {
  const toast = document.getElementById('toast');
  toast.textContent = message; toast.hidden = false;
  clearTimeout(notify.timer); notify.timer = setTimeout(() => toast.hidden = true, 5000);
}
function setProgress(title,message,running=false) {
  document.getElementById('progress-title').textContent = title;
  document.getElementById('progress-description').textContent = message;
  document.getElementById('progress-panel').classList.toggle('running',running);
}
async function loadSettings() {
  const env = await api('/api/env');
  savedKeys.clear();
  for (const key of env.configuredKeys || []) savedKeys.add(key);
  const detectedServer = new URL(location.origin);
  detectedServer.port = '3001';
  const defaultBase = detectedServer.origin;
  const baseUrl = !env.BASE_URL || env.BASE_URL.includes('yourdomain.com') ? defaultBase : env.BASE_URL;
  document.getElementById('base-url').value = baseUrl;

  const aiomInput = document.getElementById('aiometadata-host');
  if (aiomInput) {
    if (env.AIOMETADATA_HOST && !env.AIOMETADATA_HOST.includes('yourdomain.com')) {
      aiomInput.value = env.AIOMETADATA_HOST;
    } else {
      aiomInput.value = deriveAiometaHost(baseUrl);
    }
  }

  for (const [key] of fields) {
    const saved = savedKeys.has(key);
    const input = document.getElementById(key);
    input.value = '';
    input.placeholder = saved ? 'Saved · enter to replace' : 'Paste API key';
    document.getElementById(`${key}-saved`).textContent = saved ? 'SAVED' : '';
    document.getElementById(`${key}-remove`).hidden = !saved;
  }
  document.getElementById('player-link').href = `${location.protocol}//${location.hostname}:8082`;
}

async function loadManifest() {
  const info = await api('/api/manifest-info');
  if (info.directManifest) {
    currentManifest = info.aliasManifest || info.directManifest;
    document.getElementById('manifest-url').textContent = currentManifest;
    document.getElementById('copy-manifest').disabled = false;
    const install = document.getElementById('install-stremio');
    install.href = currentManifest.replace(/^https?:/, 'stremio:');
    install.classList.remove('disabled');
  }
  if (info.aiometadataManifest) {
    currentAiometaManifest = info.aiometadataManifest;
    const aiomCode = document.getElementById('aiometa-manifest-url');
    if (aiomCode) aiomCode.textContent = currentAiometaManifest;
    const copyAiom = document.getElementById('copy-aiometa-manifest');
    if (copyAiom) copyAiom.disabled = false;
    const installAiom = document.getElementById('install-aiometa-stremio');
    if (installAiom) {
      installAiom.href = currentAiometaManifest.replace(/^https?:/, 'stremio:');
      installAiom.classList.remove('disabled');
    }
  }
}

async function refreshServices() {
  const result = await api('/api/integrations');
  const grid = document.getElementById('service-grid'); grid.replaceChildren();
  for (const service of result.integrations) {
    const card = document.createElement('div'); card.className = 'service-card';
    const icon = document.createElement('span'); icon.className = 'service-icon';
    icon.textContent = service.name.replace(/[^A-Z0-9]/g,'').slice(0,2) || service.name.slice(0,2);
    const content = document.createElement('div');
    const name = document.createElement('strong'); name.textContent = service.name;
    const group = document.createElement('small'); group.textContent = service.group;
    const status = document.createElement('span'); status.className = `service-state${service.reachable?'':' offline'}`;
    status.title = service.reachable ? 'Accepting connections' : 'Not reachable yet';
    status.setAttribute('aria-label',status.title);
    content.append(name,group); card.append(icon,content,status); grid.append(card);
  }
  document.getElementById('services-summary').textContent = `${result.integrations.filter(item=>item.reachable).length} of ${result.integrations.length} services reachable`;
}

async function pollSetup() {
  clearTimeout(pollTimer);
  try {
    const job = await api('/api/setup-status');
    reconnectAttempts = 0;
    document.getElementById('setup-logs').textContent = job.logs.join('\n');
    document.getElementById('setup-details').hidden = job.status === 'idle';
    const running = job.status === 'running';
    document.getElementById('setup-button').disabled = running;
    document.getElementById('setup-button').firstElementChild.textContent = running ? 'Connecting your stack…' : 'Connect my stack';
    if (job.status !== 'idle') setProgress(job.step, running ? 'Services are being configured. You can leave this page open.' : job.status === 'complete' ? 'Your local configuration is ready. Copy the manifests into your player.' : 'Review setup details below, check your keys, then try again.',running);
    document.getElementById('step-2').classList.toggle('active',running);
    document.getElementById('step-3').classList.toggle('active',job.status === 'complete');
    if (job.status === 'complete' && lastJobStatus !== 'complete') {
      await loadManifest(); await refreshServices();
      notify('Your manifests are ready to copy.');
    }
    lastJobStatus = job.status;
    if (running) pollTimer = setTimeout(pollSetup,1600);
  } catch(error) {
    if (lastJobStatus === 'running' && ++reconnectAttempts < 90) {
      setProgress('Services are restarting','Reconnecting to the setup controller…',true);
      pollTimer = setTimeout(pollSetup,2000);
      return;
    }
    setProgress('Connection interrupted',error.message);
    document.getElementById('setup-button').disabled = false;
  }
}

const baseUrlInput = document.getElementById('base-url');
const aiomInput = document.getElementById('aiometadata-host');
if (baseUrlInput && aiomInput) {
  let prevBase = baseUrlInput.value.trim();
  baseUrlInput.addEventListener('input', () => {
    const currentBase = baseUrlInput.value.trim();
    const prevDerived = deriveAiometaHost(prevBase);
    if (!aiomInput.value || aiomInput.value === prevDerived || aiomInput.value.includes('yourdomain.com')) {
      aiomInput.value = deriveAiometaHost(currentBase);
    }
    prevBase = currentBase;
  });
}

document.getElementById('setup-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const payload = {
    BASE_URL: document.getElementById('base-url').value.trim(),
    AIOMETADATA_HOST: document.getElementById('aiometadata-host')?.value.trim() || ''
  };
  for (const [key] of fields) {
    const value = document.getElementById(key).value.trim();
    if (value || !savedKeys.has(key)) payload[key] = value;
  }
  if (!providers.some(([key])=>payload[key] || savedKeys.has(key))) { notify('Add at least one streaming provider key.'); return; }
  const button = document.getElementById('setup-button'); button.disabled = true;
  setProgress('Saving your configuration','Connecting local services and checking your keys.',true);
  try {
    await api('/api/save-env',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    await loadSettings();
    await api('/api/setup',{method:'POST'});
    lastJobStatus = 'running';
    await pollSetup();
  } catch(error) { setProgress('Setup needs attention',error.message); button.disabled=false; notify(error.message); }
});

document.getElementById('refresh-services').addEventListener('click',()=>refreshServices().catch(error=>notify(error.message)));

async function copyToClipboard(text, successMsg) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    notify(successMsg);
  } catch {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
    document.body.append(textarea);
    textarea.select();
    let copied = false;
    try { copied = document.execCommand('copy'); } finally { textarea.remove(); }
    notify(copied ? successMsg : 'Select the URL above and copy it.');
  }
}

document.getElementById('copy-manifest').addEventListener('click', () => {
  copyToClipboard(currentManifest, 'AIOStreams manifest URL copied. Paste it into your player.');
});

const copyAiomBtn = document.getElementById('copy-aiometa-manifest');
if (copyAiomBtn) {
  copyAiomBtn.addEventListener('click', () => {
    copyToClipboard(currentAiometaManifest, 'AIOMetadata manifest URL copied. Paste it into your player.');
  });
}

Promise.allSettled([loadSettings(),loadManifest(),refreshServices(),pollSetup()]).then(results=>{
  const failed = results.find(result=>result.status==='rejected');
  if (failed) setProgress('Could not load this instance',failed.reason.message);
});
