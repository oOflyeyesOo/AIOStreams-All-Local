const providers = [
  ['PREMIUMIZE_API_KEY','Premiumize','P'],['REALDEBRID_API_KEY','Real-Debrid','R'],
  ['TORBOX_API_KEY','TorBox','T'],['ALLDEBRID_API_KEY','AllDebrid','A'],
  ['DEBRIDLINK_API_KEY','Debrid-Link','D'],['EASYDEBRID_API_KEY','EasyDebrid','E']
];
const metadata = [['TMDB_API_KEY','TMDB','T'],['TVDB_API_KEY','TVDB','TV'],['FANART_API_KEY','Fanart.tv','F'],['MDBLIST_API_KEY','MDBList','M']];
const extras = [['RPDB_API_KEY','Rating posters','RP'],['TRAKT_CLIENT_ID','Trakt client ID','TR'],['TRAKT_CLIENT_SECRET','Trakt client secret','TR'],['SIMKL_CLIENT_ID','Simkl client ID','SK'],['SIMKL_CLIENT_SECRET','Simkl client secret','SK'],['ANILIST_CLIENT_ID','AniList client ID','AL'],['ANILIST_CLIENT_SECRET','AniList client secret','AL'],['SUBDL_API_KEY','SubDL','S'],['SUBSOURCE_API_KEY','SubSource','SS'],['WYZIE_API_KEY','Wyzie','W'],['GEMINI_API_KEY','Gemini','G'],['OFFCLOUD_API_KEY','Offcloud','O'],['SEEDR_API_KEY','Seedr','S']];
const fields = [...providers,...metadata,...extras];
const optionalSecrets=[['MEDIAFUSION_MANIFEST_URL','Configured MediaFusion manifest (optional)','MF'],['NZB_INDEXER_API_KEY','NZB indexer API key','NZB']];
fields.push(...optionalSecrets);
let usenetPasswordSaved=false;
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
      input.value = ''; input.placeholder = key.endsWith('_URL') ? 'Paste configured manifest URL' : 'Paste API key';
    });
    title.append(remove);
    const input = document.createElement('input');
    input.id = key; input.name = key; input.type = 'password';
    input.placeholder = key.endsWith('_URL') ? 'Paste configured manifest URL' : 'Paste API key'; input.autocomplete = 'off'; input.spellcheck = false;
    wrapper.append(title,input); target.append(wrapper);
  }
}
renderFields('provider-fields',providers);
renderFields('metadata-fields',metadata);
renderFields('extra-fields',extras);
renderFields('mediafusion-manifest-fields',[optionalSecrets[0]]);
renderFields('usenet-indexer-key-fields',[optionalSecrets[1]]);

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
  document.getElementById('enable-mediafusion').checked = env.MEDIAFUSION_REPLICAS === '1';
  document.getElementById('enable-anime-sources').checked=env.ENABLE_ANIME_SOURCES==='true';
  document.getElementById('enable-usenet').checked = env.USENET_ENABLED === 'true';
  for(const [id,key] of [['usenet-host','USENET_HOST'],['usenet-port','USENET_PORT'],['usenet-user','USENET_USER'],['usenet-connections','USENET_CONNECTIONS'],['nzb-indexer-url','NZB_INDEXER_URL']])document.getElementById(id).value=env[key]||'';
  document.getElementById('usenet-tls').checked=env.USENET_SSL!=='false';
  usenetPasswordSaved=!!env.USENET_PASSWORD_SAVED;
  document.getElementById('usenet-pass').value='';
  document.getElementById('usenet-pass').placeholder=usenetPasswordSaved?'Saved · enter to replace':'Usenet password';
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
    input.placeholder = saved ? 'Saved · enter to replace' : key.endsWith('_URL') ? 'Paste configured manifest URL' : 'Paste API key';
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
    const tracking = document.getElementById('connect-tracking');
    const configuration = new URL(currentAiometaManifest);
    const profile = configuration.pathname.match(/^\/stremio\/([^/]+)\//);
    if (tracking && profile) {
      configuration.pathname = `/stremio/${profile[1]}/configure`;
      configuration.search = ''; configuration.hash = '';
      tracking.href = configuration.toString(); tracking.classList.remove('disabled');
    }
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
    const status = document.createElement('span'); status.className = `service-state${service.enabled===false?' optional':service.reachable?'':' offline'}`;
    status.textContent=service.enabled===false?'Off':'';
    status.title = service.enabled === false ? 'Optional off' : service.reachable ? 'Accepting connections' : 'Not reachable yet';
    status.setAttribute('aria-label',status.title);
    content.append(name,group); card.append(icon,content,status); grid.append(card);
  }
  const active=result.integrations.filter(item=>item.enabled!==false);
  document.getElementById('services-summary').textContent = `${active.filter(item=>item.reachable).length} of ${active.length} enabled services reachable · ${result.integrations.length-active.length} optional off`;
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
    if (job.status !== 'idle') setProgress(job.status === 'complete' ? 'Manifest configuration saved' : job.step, running ? 'Services are being configured. You can leave this page open.' : job.status === 'complete' ? 'Manifest configuration saved. Check readiness below before testing playback.' : 'Review setup details below, check your keys, then try again.',running);
    document.getElementById('step-2').classList.toggle('active',running);
    document.getElementById('step-3').classList.toggle('active',job.status === 'complete');
    if (job.status === 'complete' && lastJobStatus !== 'complete') {
      await loadManifest(); await refreshServices();
      notify('Manifest configuration saved.');
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
    MEDIAFUSION_REPLICAS: document.getElementById('enable-mediafusion').checked ? '1' : '0',
    ENABLE_ANIME_SOURCES:document.getElementById('enable-anime-sources').checked?'true':'false',
    USENET_ENABLED: document.getElementById('enable-usenet').checked ? 'true' : 'false',
    USENET_HOST: document.getElementById('usenet-host').value.trim(),
    USENET_PORT: document.getElementById('usenet-port').value,
    USENET_USER: document.getElementById('usenet-user').value,
    USENET_CONNECTIONS: document.getElementById('usenet-connections').value,
    USENET_SSL: document.getElementById('usenet-tls').checked ? 'true' : 'false',
    NZB_INDEXER_URL: document.getElementById('nzb-indexer-url').value.trim(),
    BASE_URL: document.getElementById('base-url').value.trim(),
    AIOMETADATA_HOST: document.getElementById('aiometadata-host')?.value.trim() || ''
  };
  const usenetPassword=document.getElementById('usenet-pass').value;
  if(usenetPassword||!usenetPasswordSaved)payload.USENET_PASS=usenetPassword;
  for (const [key] of fields) {
    const value = document.getElementById(key).value.trim();
    if (value || !savedKeys.has(key)) payload[key] = value;
  }
  if (!providers.some(([key])=>payload[key] || savedKeys.has(key))&&payload.USENET_ENABLED!=='true'&&!usenetPasswordSaved&&payload.MEDIAFUSION_REPLICAS!=='1') { notify('Add a provider key, enable Usenet or configure MediaFusion.'); return; }
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

async function refreshMaintenance() {
  const state = await api('/api/maintenance');
  document.getElementById('readiness-output').textContent = [
    `Provider keys: ${state.readiness.providerConfigured ? 'configured' : 'missing'}`,
    `Metadata key: ${state.readiness.metadataConfigured ? 'configured' : 'missing'}`,
    'Authorization: run a provider check to test access',
    'Playback: not verified by configuration alone',
    state.security.defaultPassword ? 'Portal password: replace the default before remote access' : 'Portal password: configured'
  ].join('\n');
  const backup = state.backup;
  document.getElementById('maintenance-output').textContent = [
    `Release: ${state.release.release || 'not pinned'} (${state.release.status})`,
    `Backup: ${backup.status}`,
    backup.createdAt ? `Created: ${new Date(backup.createdAt).toLocaleString()}` : 'Make a backup before an upgrade.',
    `PostgreSQL included: ${backup.postgresIncluded ? 'yes' : 'not confirmed'}`
  ].join('\n');
}

async function runOperations() {
  document.getElementById('refresh-maintenance')?.addEventListener('click', () => refreshMaintenance().catch(error=>notify(error.message)));
  document.getElementById('refresh-resources')?.addEventListener('click', async () => {
    try {
      const result = await api('/api/resources');
      document.getElementById('resources-output').textContent = result.success ? `${result.container_count} containers\n${result.total_mem_gb} GB memory\n${result.total_cpu_percent}% CPU` : result.error;
    } catch (error) { document.getElementById('resources-output').textContent = error.message; }
  });
  document.getElementById('refresh-search-status')?.addEventListener('click', async () => {
    try { document.getElementById('search-status-output').textContent = JSON.stringify(await api('/api/search-status'), null, 2); }
    catch (error) { document.getElementById('search-status-output').textContent = error.message; }
  });
  document.getElementById('clean-cache')?.addEventListener('click', async event => {
    const button=event.currentTarget;
    if (!confirm('Clear temporary cache? Stored profiles and databases will be kept.')) return;
    button.disabled=true;
    try {
      const result=await api('/api/clean-cache',{method:'POST'});
      document.getElementById('cache-output').textContent = result.success ? `Cleared ${result.freed_mb} MB.` : `Cleanup incomplete: ${(result.errors || []).join('; ')}`;
    } catch(error) { document.getElementById('cache-output').textContent=error.message; }
    finally { button.disabled=false; }
  });
  const output = id => document.getElementById(id);
  document.getElementById('run-diagnostics')?.addEventListener('click', async () => {
    try {
      const result = await api('/api/diagnostics');
      output('diagnostics-output').textContent = result.checks.map(item => `${item.status.toUpperCase()}: ${item.name} — ${item.detail}`).join('\n');
    } catch (error) { output('diagnostics-output').textContent = error.message; }
  });
  document.getElementById('run-smoke-test')?.addEventListener('click', async () => {
    try {
      const result = await api('/api/smoke-test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({kind:document.getElementById('smoke-kind').value, id:document.getElementById('smoke-id').value})});
      output('smoke-output').textContent = JSON.stringify(result, null, 2);
    } catch (error) { output('smoke-output').textContent = error.message; }
  });
  document.getElementById('validate-provider')?.addEventListener('click', async () => {
    try {
      const result = await api('/api/validate-provider', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({provider:document.getElementById('provider-check').value, key:document.getElementById('provider-key').value})});
      output('provider-output').textContent = `${result.status.toUpperCase()}: ${result.detail}`;
      document.getElementById('provider-key').value = '';
    } catch (error) { output('provider-output').textContent = error.message; }
  });
  document.getElementById('recommend-profile')?.addEventListener('click', async () => {
    try { output('profile-output').textContent = JSON.stringify(await api('/api/profile-recommendation'), null, 2); }
    catch (error) { output('profile-output').textContent = error.message; }
  });
  document.getElementById('generate-proxy')?.addEventListener('click', async () => {
    try {
      const format = document.getElementById('proxy-format').value;
      const response = await fetch(`/api/proxy-config?format=${encodeURIComponent(format)}&base_url=${encodeURIComponent(document.getElementById('base-url').value)}`);
      output('proxy-output').textContent = response.ok ? await response.text() : `Server returned ${response.status}`;
    } catch (error) { output('proxy-output').textContent = error.message; }
  });
  document.getElementById('show-update-plan')?.addEventListener('click', async () => {
    try { output('update-output').textContent = JSON.stringify(await api('/api/update-plan'), null, 2); }
    catch (error) { output('update-output').textContent = error.message; }
  });
  document.getElementById('export-config')?.addEventListener('click', async () => {
    try {
      const response = await api('/api/config-export');
      const blob = new Blob([JSON.stringify(response, null, 2)], {type:'application/json'});
      const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'aio-local-config-redacted.json'; link.click(); URL.revokeObjectURL(link.href);
      output('config-output').textContent = 'Redacted configuration downloaded.';
    } catch (error) { output('config-output').textContent = error.message; }
  });
  document.getElementById('export-profile')?.addEventListener('click', async () => {
    try {
      const response = await fetch('/api/export-profile');
      if (!response.ok) throw new Error(`Server returned ${response.status}`);
      const blob = await response.blob();
      const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'aio-local-optimized-profile.json'; link.click(); URL.revokeObjectURL(link.href);
      output('config-output').textContent = 'Optimized profile downloaded.';
    } catch (error) { output('config-output').textContent = error.message; }
  });
  document.getElementById('import-config')?.addEventListener('change', async event => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const values = data.values && typeof data.values === 'object' ? data.values : data;
      for (const key of ['BASE_URL','AIOMETADATA_HOST','COMPOSE_PROFILES','TMDB_API_KEY','REALDEBRID_API_KEY','TORBOX_API_KEY','PREMIUMIZE_API_KEY','ALLDEBRID_API_KEY']) {
        if (typeof data[key] === 'string') values[key] = data[key];
      }
      const result = await api('/api/config-import', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({format:'aio-local-config-v1', values})});
      output('config-output').textContent = `Imported ${result.updated.length} supported settings.`;
      await loadSettings();
    } catch (error) { output('config-output').textContent = error.message; }
  });
}

runOperations();
Promise.allSettled([loadSettings(),loadManifest(),refreshServices(),pollSetup(),refreshMaintenance()]).then(results=>{
  const failed = results.find(result=>result.status==='rejected');
  if (failed) setProgress('Could not load this instance',failed.reason.message);
});
