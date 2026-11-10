const providers = [
  ['PREMIUMIZE_API_KEY','Premiumize','P'],['REALDEBRID_API_KEY','Real-Debrid','R'],
  ['TORBOX_API_KEY','TorBox','T'],['ALLDEBRID_API_KEY','AllDebrid','A'],
  ['DEBRIDLINK_API_KEY','Debrid-Link','D'],['EASYDEBRID_API_KEY','EasyDebrid','E']
];
const metadata = [
  ['TMDB_API_KEY','TMDB','T'],
  ['TVDB_API_KEY','TVDB','TV'],
  ['FANART_API_KEY','Fanart.tv (ClearLogos)','F'],
  ['MDBLIST_API_KEY','MDBList','M'],
  ['GEMINI_API_KEY','Gemini AI search','G']
];
const trackingKeys = [
  ['TRAKT_CLIENT_ID','Trakt client ID','TR'],
  ['TRAKT_CLIENT_SECRET','Trakt client secret','TR'],
  ['SIMKL_CLIENT_ID','Simkl client ID','SK'],
  ['SIMKL_CLIENT_SECRET','Simkl client secret','SK'],
  ['ANILIST_CLIENT_ID','AniList client ID','AL'],
  ['ANILIST_CLIENT_SECRET','AniList client secret','AL']
];
const extras = [
  ['RPDB_API_KEY','Rating posters (RPDB)','RP'],
  ['SUBDL_API_KEY','SubDL subtitles','S'],
  ['SUBSOURCE_API_KEY','SubSource subtitles','SS'],
  ['WYZIE_API_KEY','Wyzie subtitles','W'],
  ['OFFCLOUD_API_KEY','Offcloud','O'],
  ['SEEDR_API_KEY','Seedr','S']
];
const fields = [...providers,...metadata,...trackingKeys,...extras];
const optionalSecrets=[['MEDIAFUSION_MANIFEST_URL','Configured MediaFusion manifest (optional)','MF'],['NZB_INDEXER_API_KEY','AltHUB / AnimeTosho / NZB API key','NZB']];
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
renderFields('tracking-fields',trackingKeys);
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
  const schedSelect = document.getElementById('backup-schedule-select');
  if (schedSelect && env.BACKUP_SCHEDULE) schedSelect.value = env.BACKUP_SCHEDULE;
  const torrentioToggle = document.getElementById('enable-torrentio');
  if (torrentioToggle) torrentioToggle.checked = env.ENABLE_TORRENTIO !== 'false';
  const torrentioUrlInput = document.getElementById('torrentio-url');
  if (torrentioUrlInput) torrentioUrlInput.value = env.TORRENTIO_URL || '';
  const dmmToggle = document.getElementById('enable-dmm');
  if (dmmToggle) dmmToggle.checked = env.ENABLE_DMM !== 'false';
  const remuxdbToggle = document.getElementById('enable-remuxdb');
  if (remuxdbToggle) remuxdbToggle.checked = env.ENABLE_REMUXDB !== 'false';
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
  const modeVal = env.STREAMING_MODE || (env.USENET_ENABLED === 'true' && !providers.some(([k]) => savedKeys.has(k) || env[k]) ? 'usenet' : (env.USENET_ENABLED === 'true' ? 'hybrid' : 'debrid'));
  if (typeof setStreamingMode === 'function') setStreamingMode(modeVal);
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

  const templateSelect = document.getElementById('aiometadata-template');
  if (templateSelect && env.AIOMETADATA_TEMPLATE) {
    templateSelect.value = env.AIOMETADATA_TEMPLATE;
  }
  const webhookInput = document.getElementById('discord-webhook-url');
  if (webhookInput && env.DISCORD_WEBHOOK_URL) {
    webhookInput.value = env.DISCORD_WEBHOOK_URL;
  }
  if (typeof updateTemplateDisplay === 'function') updateTemplateDisplay();

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
    const installBtn = document.getElementById('btn-install-stremio');
    if (installBtn) installBtn.disabled = false;
    const install = document.getElementById('install-stremio');
    install.href = currentManifest.replace(/^https?:/, 'stremio:');
    install.classList.remove('disabled');
  }
  if (info.aiometadataManifest) {
    currentAiometaManifest = info.aiometadataManifest;
    const tracking = document.getElementById('connect-tracking');
    const setupTracking = document.getElementById('setup-connect-tracking');
    const configuration = new URL(currentAiometaManifest);
    const profile = configuration.pathname.match(/^\/stremio\/([^/]+)\//);
    if (profile) {
      configuration.pathname = `/stremio/${profile[1]}/configure`;
      configuration.search = ''; configuration.hash = '';
      const configureUrl = configuration.toString();
      if (tracking) {
        tracking.href = configureUrl;
        tracking.classList.remove('disabled');
      }
      if (setupTracking) {
        setupTracking.href = configureUrl;
        setupTracking.classList.remove('disabled');
      }
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
    ENABLE_TORRENTIO: document.getElementById('enable-torrentio')?.checked ? 'true' : 'false',
    TORRENTIO_URL: document.getElementById('torrentio-url')?.value.trim() || '',
    ENABLE_DMM: document.getElementById('enable-dmm')?.checked ? 'true' : 'false',
    ENABLE_REMUXDB: document.getElementById('enable-remuxdb')?.checked ? 'true' : 'false',
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
    STREAMING_MODE: document.getElementById('streaming-mode')?.value || 'debrid',
    AIOMETADATA_HOST: document.getElementById('aiometadata-host')?.value.trim() || '',
    AIOMETADATA_TEMPLATE: document.getElementById('aiometadata-template')?.value || 'tamtaro-aiometadata-with-anime.json',
    DISCORD_WEBHOOK_URL: document.getElementById('discord-webhook-url')?.value.trim() || ''
  };
  const usenetPassword=document.getElementById('usenet-pass').value;
  if(usenetPassword||!usenetPasswordSaved)payload.USENET_PASS=usenetPassword;
  for (const [key] of fields) {
    const value = document.getElementById(key).value.trim();
    if (value || !savedKeys.has(key)) payload[key] = value;
  }
  const mode = payload.STREAMING_MODE;
  if (mode === 'usenet') {
    payload.USENET_ENABLED = 'true';
    if (!payload.USENET_HOST || !payload.USENET_USER || (!payload.USENET_PASS && !usenetPasswordSaved)) {
      notify('Enter your Usenet server hostname, username, and password.');
      return;
    }
  } else if (!providers.some(([key])=>payload[key] || savedKeys.has(key))&&payload.USENET_ENABLED!=='true'&&!usenetPasswordSaved&&payload.MEDIAFUSION_REPLICAS!=='1') {
    notify('Add a provider key, enable Usenet or configure MediaFusion.');
    return;
  }
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

const btnInstallStremio = document.getElementById('btn-install-stremio');
if (btnInstallStremio) {
  btnInstallStremio.addEventListener('click', () => {
    if (!currentManifest) return;
    const stremioUrl = currentManifest.replace(/^https?:/, 'stremio:');
    copyToClipboard(currentManifest, 'Launching Stremio... (Manifest URL copied to clipboard as fallback)');
    window.location.href = stremioUrl;
  });
}

const backupSched = document.getElementById('backup-schedule-select');
if (backupSched) {
  backupSched.addEventListener('change', async () => {
    const val = backupSched.value;
    try {
      const res = await api('/api/save-env', { method: 'POST', body: JSON.stringify({ BACKUP_SCHEDULE: val }) });
      if (res && res.success) {
        showToast(`Automated backup schedule set to: ${val}`);
      }
    } catch (e) {
      showToast('Failed to update backup schedule');
    }
  });
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

function updateTemplateDisplay() {
  const select = document.getElementById('aiometadata-template');
  if (!select) return;
  const val = select.value || 'tamtaro-aiometadata-with-anime.json';
  const isAnime = val.includes('with-anime');
  const href = `/templates/aiometadata-configs/${val}`;
  const downloadLink = document.getElementById('download-template-json');
  if (downloadLink) {
    downloadLink.href = href;
    downloadLink.download = val;
  }
  const manifestLink = document.getElementById('download-aiometa-json');
  if (manifestLink) {
    manifestLink.href = href;
    manifestLink.download = val;
    manifestLink.textContent = isAnime
      ? 'Download AIOMetadata anime config JSON ↓'
      : 'Download AIOMetadata config JSON ↓';
  }
  const desc = document.getElementById('template-description');
  if (desc) {
    desc.textContent = isAnime
      ? 'Includes 20+ Anime catalogs (Jikan MAL airing schedule, upcoming, seasons, studios, top rankings) mapped to TVDB/IMDb with Posters+ rating badges.'
      : val.includes('grabberhawk')
      ? 'Grabberhawk curated metadata configuration for movies and series.'
      : 'Standard Tamtaro configuration with TMDB & TVDB catalogs without anime collections.';
  }
}

function setStreamingMode(mode) {
  const hiddenInput = document.getElementById('streaming-mode');
  if (hiddenInput) hiddenInput.value = mode;

  const modePills = document.querySelectorAll('.mode-pill');
  modePills.forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-mode') === mode);
  });

  const debridContainer = document.getElementById('debrid-provider-container');
  const usenetContainer = document.getElementById('usenet-primary-container');
  const enableUsenet = document.getElementById('enable-usenet');

  if (mode === 'usenet') {
    if (debridContainer) debridContainer.style.display = 'none';
    if (usenetContainer) usenetContainer.style.display = 'block';
    if (enableUsenet) enableUsenet.checked = true;
  } else if (mode === 'hybrid') {
    if (debridContainer) debridContainer.style.display = 'block';
    if (usenetContainer) usenetContainer.style.display = 'block';
    if (enableUsenet) enableUsenet.checked = true;
  } else {
    // debrid
    if (debridContainer) debridContainer.style.display = 'block';
    if (usenetContainer) usenetContainer.style.display = 'none';
  }
}

document.querySelectorAll('.mode-pill').forEach(btn => {
  btn.addEventListener('click', () => {
    const mode = btn.getAttribute('data-mode');
    setStreamingMode(mode);
  });
});

const templateSelectEl = document.getElementById('aiometadata-template');
if (templateSelectEl) {
  templateSelectEl.addEventListener('change', updateTemplateDisplay);
}

document.getElementById('copy-template-json')?.addEventListener('click', async () => {
  const select = document.getElementById('aiometadata-template');
  const val = select ? select.value : 'tamtaro-aiometadata-with-anime.json';
  try {
    const res = await fetch(`/templates/aiometadata-configs/${val}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    await copyToClipboard(text, `Copied ${val} to clipboard!`);
  } catch (err) {
    notify(`Failed to copy JSON: ${err.message}`);
  }
});

document.getElementById('test-webhook-btn')?.addEventListener('click', async () => {
  const input = document.getElementById('discord-webhook-url');
  const url = input?.value.trim();
  if (!url) {
    notify('Enter a Discord or Apprise webhook URL first.');
    return;
  }
  notify('Dispatching test alert...');
  try {
    const res = await api('/api/webhook-test', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url })
    });
    notify(res.message || 'Webhook alert delivered! 🎉');
  } catch (err) {
    notify(`Webhook test failed: ${err.message}`);
  }
});

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
  document.getElementById('export-aiometa-profile')?.addEventListener('click', async () => {
    try {
      const response = await fetch('/api/export-aiometadata');
      if (!response.ok) throw new Error(`Server returned ${response.status}`);
      const blob = await response.blob();
      const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'aio-local-aiometadata-profile.json'; link.click(); URL.revokeObjectURL(link.href);
      output('config-output').textContent = 'AIOMetadata profile downloaded.';
    } catch (error) { output('config-output').textContent = error.message; }
  });
  document.getElementById('import-config')?.addEventListener('change', async event => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const values = data.values && typeof data.values === 'object' ? data.values : data;
      for (const key of [
        'BASE_URL','AIOMETADATA_HOST','AIOMETADATA_TEMPLATE','COMPOSE_PROFILES',
        'TMDB_API_KEY','TVDB_API_KEY','FANART_API_KEY','MDBLIST_API_KEY','GEMINI_API_KEY','RPDB_API_KEY',
        'REALDEBRID_API_KEY','TORBOX_API_KEY','PREMIUMIZE_API_KEY','ALLDEBRID_API_KEY','DEBRIDLINK_API_KEY','EASYDEBRID_API_KEY',
        'TRAKT_CLIENT_ID','TRAKT_CLIENT_SECRET','SIMKL_CLIENT_ID','SIMKL_CLIENT_SECRET','ANILIST_CLIENT_ID','ANILIST_CLIENT_SECRET',
        'SUBDL_API_KEY','SUBSOURCE_API_KEY','WYZIE_API_KEY','NZB_INDEXER_API_KEY','NZB_INDEXER_URL'
      ]) {
        if (typeof data[key] === 'string') values[key] = data[key];
      }
      const result = await api('/api/config-import', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({format:'aio-local-config-v1', values})});
      output('config-output').textContent = `Imported ${result.updated.length} supported settings.`;
      await loadSettings();
    } catch (error) { output('config-output').textContent = error.message; }
  });
}

let healthInterval = null;

async function refreshHealthTelemetry() {
  try {
    const data = await api('/api/health-stats');
    if (!data || !data.success) return;

    const res = data.resources || {};
    const wd = data.watchdog || {};
    const bk = data.backup || {};

    const countEl = document.getElementById('health-fleet-count');
    if (countEl) countEl.textContent = `${res.container_count || 0} Containers`;

    const memEl = document.getElementById('health-mem-used');
    if (memEl) memEl.textContent = `${res.total_mem_gb || 0} GB`;

    const memSubEl = document.getElementById('health-mem-host');
    if (memSubEl) memSubEl.textContent = `of ${res.host_limit_gb || 0} GB Host (${res.host_mem_percent || 0}%)`;

    const memFill = document.getElementById('health-mem-fill');
    if (memFill) memFill.style.width = `${Math.min(res.host_mem_percent || 0, 100)}%`;

    const cpuEl = document.getElementById('health-cpu-load');
    if (cpuEl) cpuEl.textContent = `${res.total_cpu_percent || 0}%`;

        const zil = data.zilean || {};
    const idx = data.indexer_health || {};

    const wdEl = document.getElementById('health-watchdog-state');
    if (wdEl) {
      const idxText = idx.total_indexers ? ` (${idx.healthy_indexers}/${idx.total_indexers} Indexers)` : '';
      wdEl.textContent = `${wd.healthy_count || 0} / ${wd.total_services || 0} Online${idxText}`;
      wdEl.className = wd.overall === 'healthy' ? 'stat-val text-green' : 'stat-val text-amber';
    }

    const bkEl = document.getElementById('health-backup-summary');
    if (bkEl) {
      const zilText = zil.healthy ? ' • Zilean DMM Active' : '';
      bkEl.textContent = `${bk.count || 0} Backups (${bk.total_size_mb || 0} MB) • Retaining 5${zilText}`;
    }

    const tbody = document.getElementById('telemetry-table-body');
    if (tbody && Array.isArray(res.containers)) {
      tbody.innerHTML = '';
      res.containers.forEach(c => {
        const tr = document.createElement('tr');
        const cpuClass = c.cpu_percent > 60 ? 'text-red' : (c.cpu_percent > 20 ? 'text-amber' : 'text-green');
        tr.innerHTML = `
          <td><strong>${c.name}</strong></td>
          <td class="${cpuClass}"><strong>${c.cpu_percent}%</strong></td>
          <td>${c.mem_used_mb} MB <span class="muted">/ ${c.mem_limit_mb} MB</span></td>
          <td>${c.mem_percent}%</td>
          <td class="muted">${c.net_io}</td>
          <td><span class="badge-healthy">● RUNNING</span></td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error('Failed to refresh health telemetry:', err);
  }
}

function initHealthTelemetry() {
  document.getElementById('refresh-health')?.addEventListener('click', () => {
    refreshHealthTelemetry().then(() => notify('Stack health updated ↻'));
  });

  document.getElementById('run-watchdog-probe')?.addEventListener('click', async () => {
    try {
      notify('Running watchdog probe across 14 service endpoints…');
      const probeRes = await api('/api/watchdog', { method: 'POST' });
      notify(`Watchdog probe complete: ${probeRes.healthy_count || 0}/${probeRes.total_services || 0} services healthy!`);
      await refreshHealthTelemetry();
    } catch (e) {
      notify(`Watchdog probe failed: ${e.message}`);
    }
  });

  document.getElementById('btn-prune-backups')?.addEventListener('click', async () => {
    try {
      const res = await api('/api/backups/prune', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keep_last: 5 })
      });
      const prunedCount = res.pruned ? res.pruned.length : 0;
      notify(`Backup retention: kept ${res.retained?.length || 0}, deleted ${prunedCount} old archive(s).`);
      await refreshHealthTelemetry();
    } catch (e) {
      notify(`Prune failed: ${e.message}`);
    }
  });

  const select = document.getElementById('auto-refresh-select');
  if (select) {
    const updateInterval = () => {
      if (healthInterval) clearInterval(healthInterval);
      const val = parseInt(select.value, 10);
      if (val > 0) {
        healthInterval = setInterval(refreshHealthTelemetry, val);
      }
    };
    select.addEventListener('change', updateInterval);
    updateInterval();
  }
}

runOperations();
initHealthTelemetry();
Promise.allSettled([loadSettings(),loadManifest(),refreshServices(),pollSetup(),refreshMaintenance(),refreshHealthTelemetry()]).then(results=>{
  const failed = results.find(result=>result.status==='rejected');
  if (failed) setProgress('Could not load this instance',failed.reason.message);
});
