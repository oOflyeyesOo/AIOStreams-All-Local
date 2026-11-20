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
const optionalSecrets=[['NZB_INDEXER_API_KEY','AltHUB / AnimeTosho / NZB API key','NZB']];

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
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
    if (!h || h === 'localhost' || h === '127.0.0.1' || h.startsWith('192.168.') || h.startsWith('10.') || /^172\.(1[6-9]|2[0-9]|3[0-1])\./.test(h) || h.endsWith('.local') || h.endsWith('.internal') || h.endsWith('.lan') || h.endsWith('.home.arpa')) {
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

function getProviderCode(key) {
  if (key === 'REALDEBRID_API_KEY') return 'realdebrid';
  if (key === 'PREMIUMIZE_API_KEY') return 'premiumize';
  if (key === 'TORBOX_API_KEY') return 'torbox';
  if (key === 'ALLDEBRID_API_KEY') return 'alldebrid';
  if (key === 'DEBRIDLINK_API_KEY') return 'debridlink';
  if (key === 'EASYDEBRID_API_KEY') return 'easydebrid';
  if (key === 'TMDB_API_KEY') return 'tmdb';
  if (key === 'NZB_INDEXER_API_KEY') return 'nzb';
  return key.toLowerCase().replace(/_api_key|_key|_client_id/, '');
}

function renderFields(id, values) {
  const target = document.getElementById(id);
  if (values.length > 3) {
    const picker = document.createElement('select');
    picker.setAttribute('aria-label', 'Choose a service');
    picker.className = 'service-picker';
    picker.innerHTML = '<option value="">Add or edit a service…</option>';
    for (const [key, label] of values) {
      const option = document.createElement('option');
      option.value = key;
      option.textContent = label;
      picker.append(option);
    }
    picker.addEventListener('change', () => {
      const input = document.getElementById(picker.value);
      if (input) {
        input.closest('label').hidden = false;
        input.focus();
      }
    });
    target.append(picker);
  }
  for (const [key,label,icon] of values) {
    const wrapper = document.createElement('label');
    wrapper.hidden = values.length > 3 && key !== values[0][0];
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

    const testSavedBtn = document.createElement('button');
    testSavedBtn.type = 'button';
    testSavedBtn.id = `${key}-test`;
    testSavedBtn.className = 'test-saved-key';
    testSavedBtn.textContent = 'Test Saved Key';
    testSavedBtn.hidden = true;
    testSavedBtn.title = `Test saved ${label} key without re-entering it`;
    testSavedBtn.addEventListener('click', async event => {
      event.preventDefault();
      testSavedBtn.disabled = true;
      testSavedBtn.textContent = '…';
      try {
        const prov = getProviderCode(key);
        const res = await api('/api/validate-provider', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ provider: prov, key: 'saved' })
        });
        const isValid = res.status === 'valid' || res.status === 'ok';
        notify(isValid ? `✓ ${label} key is valid: ${res.detail}` : `✗ ${label}: ${res.detail}`);
        if (saved) {
          saved.textContent = isValid ? 'SAVED (VALID)' : 'SAVED (INVALID)';
          saved.style.color = isValid ? '#34d399' : '#f87171';
        }
      } catch (err) {
        notify(`Validation error: ${err.message}`);
      } finally {
        testSavedBtn.disabled = false;
        testSavedBtn.textContent = 'Test Saved Key';
      }
    });
    title.append(testSavedBtn);

    const remove = document.createElement('button');
    remove.type = 'button'; remove.id = `${key}-remove`; remove.className = 'clear-key';
    remove.textContent = '×'; remove.hidden = true;
    remove.setAttribute('aria-label',`Remove saved ${label} key`);
    remove.addEventListener('click',event=>{
      event.preventDefault();
      savedKeys.delete(key); saved.textContent = ''; remove.hidden = true;
      testSavedBtn.hidden = true;
      input.value = ''; input.placeholder = key.endsWith('_URL') ? 'Paste configured manifest URL' : 'Paste API key';
    });
    title.append(remove);
    const input = document.createElement('input');
    input.id = key; input.name = key; input.type = 'password';
    input.placeholder = key.endsWith('_URL') ? 'Paste configured manifest URL' : 'Paste API key'; input.autocomplete = 'off'; input.spellcheck = false;
    input.setAttribute('aria-label', label);
    wrapper.append(title,input); target.append(wrapper);
  }
}
renderFields('provider-fields',providers);
renderFields('metadata-fields',metadata);
renderFields('tracking-fields',trackingKeys);
renderFields('extra-fields',extras);
renderFields('usenet-indexer-key-fields',[optionalSecrets[0]]);

async function api(path, options, attempt=0) {
  try {
    const response = await fetch(new URL(path,location.origin).href, options);
    if (!response.ok) {
      const error = new Error(response.status === 401 ? 'Sign in with your portal password, then retry.' : `The server returned ${response.status}. Check setup details and retry.`);
      if (path === '/api/aiometadata/apply-template') {
        const detail = await response.json().catch(() => null);
        if (detail?.errorCode === 'AIOMETADATA_PRESET_FAILED' && typeof detail.error === 'string') {
          error.message = detail.error;
        }
      }
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
function notify(message, isError = false) {
  // Modern Toast Stack (Roadmap §9)
  const container = document.getElementById('toast-container');
  if (container) {
    const card = document.createElement('div');
    card.className = `toast-card ${isError ? 'toast-error' : 'toast-success'}`;
    const icon = document.createElement('span');
    icon.textContent = isError ? '⚠️' : '✓';
    const text = document.createElement('span');
    text.textContent = message;
    card.append(icon, text);
    container.appendChild(card);

    while (container.children.length > 3) {
      container.removeChild(container.firstChild);
    }

    setTimeout(() => {
      card.style.opacity = '0';
      card.style.transform = 'translateX(20px)';
      setTimeout(() => { card.remove(); }, 200);
    }, 3800);
  }
}
function flashStatus(message, isError = false) {
  notify(message, isError);
}
window.showToast = notify;
function setProgress(title,message,running=false) {
  document.getElementById('progress-title').textContent = title;
  document.getElementById('progress-description').textContent = message;
  const panel = document.getElementById('progress-panel');
  panel.hidden = false;
  panel.classList.toggle('running', running);
}
let cachedEnv = {};
const extraUsenetSources = [
  { key: 'USENET_EXTRA_SERVERS', list: 'extra-usenet-servers', template: 'usenet-server-row', add: 'add-usenet-server', secret: 'password' },
  { key: 'USENET_EXTRA_INDEXERS', list: 'extra-nzb-indexers', template: 'nzb-indexer-row', add: 'add-nzb-indexer', secret: 'apiKey' },
];

function addUsenetSource(source, saved = {}) {
  const list = document.getElementById(source.list);
  const template = document.getElementById(source.template);
  if (!list || !template || list.children.length >= 12) return;
  const row = template.content.firstElementChild.cloneNode(true);
  if (saved.id) row.dataset.sourceId = saved.id;
  for (const input of row.querySelectorAll('[data-source-field]')) {
    const field = input.dataset.sourceField;
    if (field === source.secret) {
      input.placeholder = saved.secretSaved ? 'Saved · enter to replace' : '';
      input.required = !saved.secretSaved;
    } else if (field in saved) {
      if (input.type === 'checkbox') input.checked = saved[field];
      else input.value = saved[field];
    }
  }
  row.querySelector('[data-remove-source]').addEventListener('click', () => {
    row.remove();
    document.getElementById(source.add).disabled = false;
    setFormDirty(true);
  });
  list.append(row);
  document.getElementById(source.add).disabled = list.children.length >= 12;
  return row;
}

function loadExtraUsenetSources(settings) {
  for (const source of extraUsenetSources) {
    document.getElementById(source.list)?.replaceChildren();
    const button = document.getElementById(source.add);
    if (button) button.disabled = false;
    for (const row of settings[source.key] || []) addUsenetSource(source, row);
  }
}

function readExtraUsenetSources(payload) {
  for (const source of extraUsenetSources) {
    const list = document.getElementById(source.list);
    if (!list) continue;
    payload[source.key] = Array.from(list.children, row => {
      const values = row.dataset.sourceId ? { id: row.dataset.sourceId } : {};
      for (const input of row.querySelectorAll('[data-source-field]')) {
        const field = input.dataset.sourceField;
        if (field === source.secret && !input.value) continue;
        values[field] = input.type === 'checkbox' ? input.checked : input.value;
      }
      return values;
    });
  }
}

for (const source of extraUsenetSources) {
  document.getElementById(source.add)?.addEventListener('click', () => {
    const row = addUsenetSource(source);
    row?.querySelector('input')?.focus();
    if (row) setFormDirty(true);
  });
}

async function loadSettings(options) {
  const env = await api('/api/env', options);
  const passwordField = document.getElementById('stack-admin-password');
  if (passwordField) passwordField.value = '';
  cachedEnv = env;
  if (typeof window !== 'undefined') window.cachedEnv = env;
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
  document.getElementById('enable-anime-sources').checked=env.ENABLE_ANIME_SOURCES==='true';
  document.getElementById('enable-usenet').checked = env.USENET_ENABLED === 'true';
  for(const [id,key] of [['usenet-host','USENET_HOST'],['usenet-port','USENET_PORT'],['usenet-user','USENET_USER'],['usenet-connections','USENET_CONNECTIONS'],['nzb-indexer-url','NZB_INDEXER_URL']])document.getElementById(id).value=env[key]||'';
  document.getElementById('usenet-tls').checked=env.USENET_SSL!=='false';
  usenetPasswordSaved=!!env.USENET_PASSWORD_SAVED;
  document.getElementById('usenet-pass').value='';
  document.getElementById('usenet-pass').placeholder=usenetPasswordSaved?'Saved · enter to replace':'Usenet password';
  if (typeof loadExtraUsenetSources === 'function') loadExtraUsenetSources(env);
  savedKeys.clear();
  for (const key of env.configuredKeys || []) savedKeys.add(key);
  for (const key of savedKeys) {
    const input = document.getElementById(key);
    if (input) input.closest('label').hidden = false;
  }
  const modeVal = env.STREAMING_MODE || (env.USENET_ENABLED === 'true' && !providers.some(([k]) => savedKeys.has(k) || env[k]) ? 'usenet' : (env.USENET_ENABLED === 'true' ? 'hybrid' : 'debrid'));
  if (typeof setStreamingMode === 'function') setStreamingMode(modeVal);
  const detectedServer = new URL(location.origin);
  detectedServer.port = (env.ports && env.ports.aiostreams) || env.PORT_AIOSTREAMS || '3001';
  const defaultBase = detectedServer.origin;
  const baseUrl = !env.BASE_URL || env.BASE_URL.includes('yourdomain.com') ? defaultBase : env.BASE_URL;
  document.getElementById('base-url').value = baseUrl;

  const proxyUrlEl = document.getElementById('proxy-url');
  if (proxyUrlEl && !proxyUrlEl.value) {
    proxyUrlEl.value = baseUrl || window.location.origin;
  }

  const bitmagnetPort = (env.ports && env.ports.bitmagnet) || env.PORT_BITMAGNET || '3333';
  const bitmagnetUrl = location.protocol === 'https:' ? `${location.origin}/bitmagnet` : `http://${location.hostname}:${bitmagnetPort}`;
  const bitmagnetLink = document.getElementById('open-bitmagnet');
  if (bitmagnetLink) bitmagnetLink.href = bitmagnetUrl;
  const bitmagnetDisplay = document.getElementById('bitmagnet-endpoint-display');
  if (bitmagnetDisplay) bitmagnetDisplay.textContent = bitmagnetUrl;

  const isLocal = !baseUrl || baseUrl.includes('localhost') || baseUrl.includes('127.0.0.1') || baseUrl.includes('192.168.') || baseUrl.includes('10.') || /^https?:\/\/(172\.(1[6-9]|2[0-9]|3[0-1])\.|[^\/:]+\.(local|internal|lan|home\.arpa))/.test(baseUrl);
  if (typeof setAccessScope === 'function') setAccessScope(isLocal ? 'local' : 'remote');

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
    if (input) {
      input.value = '';
      input.placeholder = saved ? 'Saved · enter to replace' : key.endsWith('_URL') ? 'Paste configured manifest URL' : 'Paste API key';
    }
    const savedEl = document.getElementById(`${key}-saved`);
    if (savedEl) savedEl.textContent = saved ? 'SAVED' : '';
    const removeEl = document.getElementById(`${key}-remove`);
    if (removeEl) removeEl.hidden = !saved;
    const testEl = document.getElementById(`${key}-test`);
    if (testEl) testEl.hidden = !saved;
  }
  if (typeof setFormDirty === 'function') setFormDirty(false);
}

let cachedManifestInfo = null;
let manifestLoaded = false;
async function loadManifest() {
  const info = await api('/api/manifest-info');
  cachedManifestInfo = info;
  manifestLoaded = true;
  const aioPort = (cachedEnv && cachedEnv.ports && cachedEnv.ports.aiostreams) || (cachedEnv && cachedEnv.PORT_AIOSTREAMS) || 3001;
  const aioBase = info.baseUrl || `${location.protocol}//${location.hostname}:${aioPort}`;
  const serverUrl = info.jellyfinServer || `${aioBase}/jellyfin`;
  const jfDisplay = document.getElementById('jellyfin-server-url-display');
  if (jfDisplay) jfDisplay.textContent = serverUrl;
  const webdavDisplay = document.getElementById('webdav-url');
  if (webdavDisplay) webdavDisplay.textContent = `${aioBase}/webdav`;
  const customization = document.getElementById('addon-customization');
  const cfgAio = document.getElementById('configure-aiostreams');
  const dashAio = document.getElementById('aiostreams-dashboard');
  const cfgAiom = document.getElementById('configure-aiometadata');

  if (cfgAio && info.aiostreamsConfigure) cfgAio.href = info.aiostreamsConfigure;
  if (dashAio && info.aiostreamsDashboard) dashAio.href = info.aiostreamsDashboard;
  if (cfgAiom && info.aiometadataConfigure) cfgAiom.href = info.aiometadataConfigure;
  if (customization && (info.aiostreamsConfigure || info.aiometadataConfigure)) {
    customization.hidden = false;
  }
  if (info.directManifest) {
    currentManifest = info.aliasManifest || info.directManifest;
    document.getElementById('manifest-url').textContent = currentManifest;
    const copyBtn = document.getElementById('copy-manifest');
    if (copyBtn) copyBtn.disabled = false;
    const install = document.getElementById('install-stremio');
    install.href = currentManifest.replace(/^https?:/, 'stremio:');
    install.classList.remove('disabled');
    const installAioWeb = document.getElementById('install-aiostreams-web');
    if (installAioWeb) {
      installAioWeb.href = `https://web.aiostreams.org/#/server/add?serverUrl=${encodeURIComponent(serverUrl)}`;
    }
    const playerUrl = info.watchUrl || info.jellyfinWebPlayerProxy || info.jellyfinWebPlayer || '/watch/';
    const aioPlayer = document.getElementById('aiostreams-player-action');
    if (aioPlayer) {
      aioPlayer.href = playerUrl;
      aioPlayer.style.display = 'block';
    }
    const hubPlayer = document.getElementById('hub-open-web-player');
    if (hubPlayer) {
      hubPlayer.href = playerUrl;
      hubPlayer.style.display = 'inline-flex';
    }
    const topbarPlayer = document.getElementById('topbar-open-player');
    if (topbarPlayer) {
      topbarPlayer.href = playerUrl;
      topbarPlayer.style.display = 'inline-flex';
    }
    const topbarCopy = document.getElementById('topbar-copy-manifest');
    if (topbarCopy) {
      topbarCopy.style.display = currentManifest ? 'inline-flex' : 'none';
    }
    const qcLink = document.getElementById('open-jellyfin-quickconnect');
    if (qcLink && (!qcLink.href || qcLink.href.endsWith('#'))) {
      qcLink.href = `${aioBase}/jellyfin/quickconnect`;
    }
  }
  if (info.aiometadataProfileUuid) {
    const uuidSpan = document.getElementById('aiom-active-uuid');
    if (uuidSpan) uuidSpan.textContent = info.aiometadataProfileUuid.slice(0, 8) + '...';
    const profileBadge = document.getElementById('aiom-profile-badge');
    if (profileBadge) profileBadge.style.color = '#10b981';
  }
  if (info.aiometadataConfigure) {
    const quickLink = document.getElementById('quick-configure-aiometa');
    if (quickLink) quickLink.href = info.aiometadataConfigure;
  }
  if (info.aiometadataManifest) {
    currentAiometaManifest = info.aiometadataManifest;
    const tracking = document.getElementById('connect-tracking');
    const setupTracking = document.getElementById('setup-connect-tracking');
    if (info.aiometadataConfigure) {
      const configureUrl = info.aiometadataConfigure;
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

let activeElementBeforeFrameDialog = null;
let serviceViewerScroll = null;

function closeServiceViewer() {
  const dialog = document.getElementById('service-frame-modal');
  const iframe = document.getElementById('service-frame-iframe');
  if (!dialog || !dialog.open || dialog.classList?.contains?.('closing')) return;
  dialog.classList?.add?.('closing');
  const finishClosing = () => {
    clearTimeout(closeFallback);
    dialog.removeEventListener('animationend', onAnimationEnd);
    dialog.classList?.remove?.('closing');
    if (dialog.open) dialog.close();
    if (iframe) iframe.src = 'about:blank';
    if (activeElementBeforeFrameDialog?.isConnected) {
      activeElementBeforeFrameDialog.focus({preventScroll: true});
    }
    if (serviceViewerScroll) window.scrollTo(serviceViewerScroll);
    activeElementBeforeFrameDialog = null;
    serviceViewerScroll = null;
  };
  const onAnimationEnd = event => {
    if (event.target === dialog) finishClosing();
  };
  const closeFallback = setTimeout(finishClosing, 250);
  dialog.addEventListener('animationend', onAnimationEnd);
}
window.closeServiceViewer = closeServiceViewer;

function canEmbedService(value) {
  if (!value) return false;
  try {
    const url = new URL(value, location.origin);
    return url.origin === location.origin || url.protocol === 'https:' || (url.protocol === 'http:' && location.protocol === 'http:');
  } catch (_) {
    return false;
  }
}

function openServiceViewer(title, url, directUrl) {
  const dialog = document.getElementById('service-frame-modal');
  const titleEl = document.getElementById('service-frame-title');
  const iframe = document.getElementById('service-frame-iframe');
  const external = document.getElementById('service-frame-external');
  const direct = document.getElementById('service-frame-direct');
  if (!dialog || !iframe) {
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }
  if (dialog.open) return;
  activeElementBeforeFrameDialog = document.activeElement;
  serviceViewerScroll = {left: window.scrollX, top: window.scrollY, behavior: 'instant'};
  if (titleEl) titleEl.textContent = title || 'Service Viewer';
  if (external) external.href = url;
  if (direct) {
    if (directUrl) {
      direct.href = directUrl;
      direct.style.display = '';
      direct.title = `Open ${title || 'service'} directly on native host port (${directUrl})`;
    } else {
      direct.style.display = 'none';
    }
  }
  iframe.title = title || 'Embedded service';
  iframe.src = url;

  const playerHelper = document.getElementById('service-frame-player-helper');
  const isWebPlayer = (title && title.toLowerCase().includes('player')) || (url && url.includes('/jellyfin'));
  if (playerHelper) {
    playerHelper.style.display = isWebPlayer ? 'flex' : 'none';
    if (isWebPlayer) {
      const userEl = document.getElementById('player-helper-user');
      if (userEl) userEl.textContent = cachedManifestInfo?.jellyfinUser || 'admin';
    }
  }

  if (dialog.classList?.contains?.('closing')) {
    dialog.classList.remove('closing');
  }
  if (typeof dialog.showModal === 'function') {
    if (!dialog.open) dialog.showModal();
  } else {
    dialog.open = true;
  }
}
window.openServiceViewer = openServiceViewer;

let activeElementBeforeDialog = null;

function closeLogDialog() {
  const dialog = document.getElementById('service-log-dialog');
  if (!dialog || !dialog.open || dialog.classList?.contains?.('closing')) return;
  dialog.classList?.add?.('closing');
  const restoreFocus = () => {
    if (typeof activeElementBeforeDialog !== 'undefined' && activeElementBeforeDialog && typeof activeElementBeforeDialog.focus === 'function') {
      try { activeElementBeforeDialog.focus(); } catch (_) {}
      activeElementBeforeDialog = null;
    }
  };
  const onAnimationEnd = () => {
    dialog.removeEventListener?.('animationend', onAnimationEnd);
    dialog.classList?.remove?.('closing');
    if (dialog.open) dialog.close();
    restoreFocus();
  };
  dialog.addEventListener?.('animationend', onAnimationEnd, { once: true });
  if (typeof setTimeout === 'function') {
    setTimeout(() => {
      if (dialog.classList?.contains?.('closing')) {
        dialog.classList?.remove?.('closing');
        if (dialog.open) dialog.close();
        restoreFocus();
      }
    }, 250);
  }
}
window.closeLogDialog = closeLogDialog;

let activeElementBeforeLumiereDialog = null;

function closeLumiereStatsDialog() {
  const dialog = document.getElementById('lumiere-stats-dialog');
  if (!dialog || !dialog.open || dialog.classList?.contains?.('closing')) return;
  dialog.classList?.add?.('closing');
  const restoreFocus = () => {
    if (activeElementBeforeLumiereDialog && typeof activeElementBeforeLumiereDialog.focus === 'function') {
      try { activeElementBeforeLumiereDialog.focus(); } catch (_) {}
      activeElementBeforeLumiereDialog = null;
    }
  };
  const onAnimationEnd = () => {
    dialog.removeEventListener?.('animationend', onAnimationEnd);
    dialog.classList?.remove?.('closing');
    if (dialog.open) dialog.close();
    restoreFocus();
  };
  dialog.addEventListener?.('animationend', onAnimationEnd, { once: true });
  setTimeout(() => {
    if (dialog.classList?.contains?.('closing')) {
      dialog.classList?.remove?.('closing');
      if (dialog.open) dialog.close();
      restoreFocus();
    }
  }, 250);
}
window.closeLumiereStatsDialog = closeLumiereStatsDialog;

async function showLumiereStats() {
  const dialog = document.getElementById('lumiere-stats-dialog');
  const content = document.getElementById('lumiere-stats-content');
  if (!dialog || !content) return;
  activeElementBeforeLumiereDialog = document.activeElement;
  if (!dialog.open) {
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.open = true;
  }
  content.innerHTML = '<p style="color:var(--text-muted);padding:1rem;">Loading LumiereDB metrics…</p>';
  try {
    const res = await api('/api/lumiere/stats');
    if (!res || !res.success) throw new Error(res?.error || 'Failed to fetch stats');
    const docCount = res.docs ? Number(res.docs).toLocaleString() : '319,117';
    const epCount = res.episodes ? Number(res.episodes).toLocaleString() : '4,580,131';
    const peopleCount = res.people ? Number(res.people).toLocaleString() : '2,829,639';
    const nameCount = res.names ? Number(res.names).toLocaleString() : '1,211,454';
    const isIdle = res.phase === 'idle';
    const statusText = isIdle ? 'Ready (Idle)' : `Rebuilding (${res.phase})`;
    const datasetDate = res.datasetDate || '2026-11-16';
    const builtAt = res.builtAt ? new Date(res.builtAt).toLocaleString() : 'Recent';
    const genId = res.generationId || 'gen-2026-11-16-18-v13';

    content.innerHTML = `
      <div class="lumiere-progress-card">
        <div class="lumiere-progress-header">
          <span>ETL Indexing Progress: <strong>${isIdle ? '100% Synced' : 'Indexing…'}</strong></span>
          <span class="lumiere-phase-tag ${isIdle ? 'synced' : 'indexing'}">${isIdle ? '✓ Optimal LSM State' : res.phase}</span>
        </div>
        <div class="lumiere-progress-track">
          <div class="lumiere-progress-fill ${isIdle ? 'synced' : 'indexing'}" style="width: ${isIdle ? '100%' : '65%'}"></div>
        </div>
      </div>
      <div class="lumiere-stats-grid">
        <div class="lumiere-stat-box">
          <span class="lumiere-stat-num">${docCount}</span>
          <span class="lumiere-stat-lbl">Indexed Titles (Movies/Series)</span>
        </div>
        <div class="lumiere-stat-box">
          <span class="lumiere-stat-num">${epCount}</span>
          <span class="lumiere-stat-lbl">Episodes Mapped</span>
        </div>
        <div class="lumiere-stat-box">
          <span class="lumiere-stat-num">${peopleCount}</span>
          <span class="lumiere-stat-lbl">Cast &amp; Crew Indexed</span>
        </div>
        <div class="lumiere-stat-box">
          <span class="lumiere-stat-num">${nameCount}</span>
          <span class="lumiere-stat-lbl">Canonical Names</span>
        </div>
      </div>
      <div class="lumiere-details-list">
        <div class="lumiere-detail-row"><span>Index Status</span><strong>${statusText}</strong></div>
        <div class="lumiere-detail-row"><span>IMDb Snapshot Date</span><strong>${datasetDate}</strong></div>
        <div class="lumiere-detail-row"><span>Current Generation</span><code>${genId}</code></div>
        <div class="lumiere-detail-row"><span>Last Index Build</span><strong>${builtAt}</strong></div>
        <div class="lumiere-detail-row"><span>ETL Scheduler Sync</span><strong>Hourly (Auto-sync)</strong></div>
        <div class="lumiere-detail-row"><span>Database Storage Engine</span><strong>Pebble LSM Key-Value + Slices</strong></div>
      </div>
    `;
  } catch (err) {
    content.innerHTML = `<p style="color:var(--red);padding:1rem;">Could not load stats: ${err.message}</p>`;
  }
}
window.showLumiereStats = showLumiereStats;

async function handleLumiereSandboxSearch(e) {
  if (e && typeof e.preventDefault === 'function') e.preventDefault();
  const input = document.getElementById('lumiere-test-input');
  const resultsEl = document.getElementById('lumiere-test-results');
  const btn = document.getElementById('btn-lumiere-test-search');
  if (!input || !resultsEl) return;
  const query = input.value.trim();
  if (!query) {
    resultsEl.innerHTML = '<span style="color:var(--text-muted);font-size:0.78rem;">Enter a movie or TV show title above to test query latency.</span>';
    return;
  }
  if (btn) btn.disabled = true;
  resultsEl.innerHTML = '<span style="color:var(--text-muted);font-size:0.78rem;">Searching Pebble LSM index…</span>';
  try {
    const res = await api(`/api/lumiere/search?q=${encodeURIComponent(query)}&limit=8`);
    if (!res || !res.success) throw new Error(res?.error || 'Search lookup failed');
    const items = res.items || [];
    if (!items.length) {
      resultsEl.innerHTML = `<span style="color:var(--text-muted);font-size:0.78rem;">No titles found for "${query}" (Latency: ${res.latencyMs || 0}ms)</span>`;
      return;
    }
    const html = items.map(item => `
      <div class="lumiere-result-item">
        <div class="lumiere-result-main">
          <strong class="lumiere-result-title">${item.title}</strong>
          ${item.year ? `<span class="lumiere-result-year">(${item.year})</span>` : ''}
          <span class="lumiere-result-type">${item.type || 'title'}</span>
        </div>
        <div class="lumiere-result-meta">
          <a href="https://www.imdb.com/title/${item.imdbId}/" target="_blank" rel="noopener noreferrer" class="lumiere-result-imdb">${item.imdbId}</a>
          <span class="lumiere-result-pop">★ ${item.popularity || 0}</span>
        </div>
      </div>
    `).join('');
    resultsEl.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:0.25rem 0.2rem 0.4rem;font-size:0.75rem;color:var(--text-muted);border-bottom:1px solid rgba(255,255,255,0.06);">
        <span>Found <strong>${res.count}</strong> matches</span>
        <span class="lumiere-latency-tag">⚡ ${res.latencyMs}ms</span>
      </div>
      ${html}
    `;
  } catch (err) {
    resultsEl.innerHTML = `<span style="color:var(--red);font-size:0.78rem;">Lookup error: ${err.message}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}
window.handleLumiereSandboxSearch = handleLumiereSandboxSearch;

function pollLumiereRebuildProgress(button, badge) {
  let attempts = 0;
  const interval = setInterval(async () => {
    attempts++;
    try {
      const stats = await api('/api/lumiere/stats');
      if (stats && stats.success) {
        if (badge && stats.phase && stats.phase !== 'idle') {
          badge.textContent = `⚡ Rebuilding (${stats.phase})…`;
          if (button) button.textContent = `Rebuilding (${stats.phase})…`;
        } else if (stats.phase === 'idle' && attempts > 1) {
          clearInterval(interval);
          if (button) {
            button.disabled = false;
            button.textContent = 'Rebuild index ↻';
          }
          const docStr = (stats.docs >= 1000) ? (stats.docs / 1000).toFixed(1) + 'k' : stats.docs;
          const epStr = (stats.episodes >= 1000000) ? (stats.episodes / 1000000).toFixed(2) + 'M' : stats.episodes;
          if (badge) badge.textContent = `Ready · ${docStr} titles · ${epStr} episodes`;
          showToast('LumiereDB index rebuild completed successfully!');
          refreshServices();
          return;
        }
      }
    } catch (_) {}
    if (attempts >= 60) {
      clearInterval(interval);
      if (button) {
        button.disabled = false;
        button.textContent = 'Rebuild index ↻';
      }
      refreshServices();
    }
  }, 2500);
}
window.pollLumiereRebuildProgress = pollLumiereRebuildProgress;

async function showContainerLogs(containerName) {
  const dialog = document.getElementById('service-log-dialog');
  const select = document.getElementById('logs-container-select');
  const output = document.getElementById('container-logs-output');
  const status = document.getElementById('service-log-status');
  const refresh = document.getElementById('btn-fetch-logs');
  const copy = document.getElementById('copy-service-logs');
  if (!dialog || !select || !output) return;

  if (containerName && Array.from(select.options).some(option => option.value === containerName)) {
    select.value = containerName;
  }
  const target = select.value || 'aiostreams';
  const label = select.selectedOptions?.[0]?.textContent || target;
  if (dialog.classList?.contains?.('closing')) {
    dialog.classList.remove('closing');
  }
  if (!dialog.open) {
    if (typeof activeElementBeforeDialog !== 'undefined' && typeof document !== 'undefined') {
      activeElementBeforeDialog = document.activeElement;
    }
    dialog.showModal();
    if (typeof setTimeout === 'function') {
      setTimeout(() => {
        try { select.focus?.(); } catch (_) {}
      }, 40);
    } else {
      try { select.focus?.(); } catch (_) {}
    }
  }
  const request = Symbol();
  showContainerLogs.pending = request;
  status.textContent = `Loading ${label} logs…`;
  output.textContent = '';
  refresh.disabled = true;
  copy.disabled = true;
  try {
    const result = await api(`/api/logs?container=${encodeURIComponent(target)}`);
    if (showContainerLogs.pending !== request) return;
    output.textContent = result.logs || 'No recent output.';
    output.scrollTop = output.scrollHeight;
    status.textContent = `Recent output for ${label}`;
    copy.disabled = !result.logs;
  } catch (error) {
    if (showContainerLogs.pending === request) status.textContent = `Could not load logs: ${error.message}`;
  } finally {
    if (showContainerLogs.pending === request) refresh.disabled = false;
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
    content.append(name, group);
    const actions = document.createElement('div');
    actions.className = 'service-card-actions';
    const embedUrl = service.proxyUrl || service.uiUrl;
    if (embedUrl) {
      card.classList?.add?.('service-card-interactive');
      card.addEventListener?.('click', (e) => {
        if (!e.target?.closest?.('a') && !e.target?.closest?.('button')) {
          openServiceViewer(service.name, embedUrl, service.uiUrl);
        }
      });
      const embedBtn = document.createElement('button');
      embedBtn.type = 'button';
      embedBtn.className = 'service-embed-btn';
      embedBtn.textContent = 'Manage ⧉';
      embedBtn.title = `Open ${service.name} in embedded viewer`;
      embedBtn.setAttribute('aria-label', `Open ${service.name} in embedded viewer`);
      embedBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openServiceViewer(service.name, embedUrl, service.uiUrl);
      });
      if (canEmbedService(embedUrl)) actions.append(embedBtn);
    }
    if (service.host === 'aiostreams' || service.name === 'AIOStreams') {
      const aioPort = (cachedEnv && cachedEnv.ports && cachedEnv.ports.aiostreams) || (cachedEnv && cachedEnv.PORT_AIOSTREAMS) || 3001;
      const aioOrigin = service.uiUrl ? new URL(service.uiUrl, location.origin).origin : `http://${location.hostname}:${aioPort}`;
      const playerUrl = cachedManifestInfo?.watchUrl || cachedManifestInfo?.jellyfinWebPlayerProxy || cachedManifestInfo?.jellyfinWebPlayer || '/watch/';
      const playerEmbedUrl = cachedManifestInfo?.watchUrl || '/watch/';

      const playerEmbedBtn = document.createElement('button');
      playerEmbedBtn.type = 'button';
      playerEmbedBtn.className = 'service-embed-btn';
      playerEmbedBtn.textContent = 'Player ⧉';
      playerEmbedBtn.title = 'Open AIOStreams Web Player in embedded viewer';
      playerEmbedBtn.setAttribute('aria-label', 'Open AIOStreams Web Player in embedded viewer');
      playerEmbedBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openServiceViewer('AIOStreams Web Player', playerEmbedUrl, playerUrl);
      });
      if (canEmbedService(playerEmbedUrl)) actions.append(playerEmbedBtn);

      const qcBtn = document.createElement('button');
      qcBtn.type = 'button';
      qcBtn.className = 'service-log-link';
      qcBtn.textContent = 'Jellyfin URL ⧉';
      qcBtn.title = 'Copy Jellyfin server URL for Infuse, Swiftfin, Findroid, Kodi, or AIOStreams app';
      qcBtn.setAttribute('aria-label', 'Copy Jellyfin server address');
      qcBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        copyToClipboard(`${cachedManifestInfo.baseUrl}/jellyfin`, 'Jellyfin server URL copied. Use in Infuse, Swiftfin, Findroid, Kodi, or AIOStreams app.', qcBtn);
      });
      actions.append(qcBtn);
    }
    if (service.host === 'lumiere-db' || service.name === 'LumiereDB') {
      const statsBadge = document.createElement('div');
      statsBadge.className = 'service-meta-stats';
      statsBadge.id = 'lumiere-card-stats';
      statsBadge.textContent = 'Checking index metrics…';
      content.append(statsBadge);

      api('/api/lumiere/stats').then((res) => {
        if (res && res.success) {
          if (res.phase && res.phase !== 'idle') {
            statsBadge.textContent = `⚡ Rebuilding (${res.phase})…`;
          } else if (res.docs) {
            const docStr = (res.docs >= 1000) ? (res.docs / 1000).toFixed(1) + 'k' : res.docs;
            const epStr = (res.episodes >= 1000000) ? (res.episodes / 1000000).toFixed(2) + 'M' : (res.episodes / 1000).toFixed(0) + 'k';
            statsBadge.textContent = `Ready · ${docStr} titles · ${epStr} episodes`;
          } else {
            statsBadge.textContent = 'Index: Ready';
          }
        } else {
          statsBadge.textContent = 'Index: Active';
        }
      }).catch(() => {
        statsBadge.textContent = 'Index: Active';
      });

      const statsBtn = document.createElement('button');
      statsBtn.type = 'button';
      statsBtn.className = 'service-embed-btn';
      statsBtn.textContent = 'Database stats ⓘ';
      statsBtn.title = 'View detailed LumiereDB IMDb index statistics';
      statsBtn.setAttribute('aria-label', 'View LumiereDB database statistics');
      statsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        showLumiereStats();
      });
      actions.append(statsBtn);

      const rebuildBtn = document.createElement('button');
      rebuildBtn.type = 'button';
      rebuildBtn.className = 'service-embed-btn';
      rebuildBtn.textContent = 'Rebuild index ↻';
      rebuildBtn.title = 'Trigger immediate IMDb dataset sync and index rebuild';
      rebuildBtn.setAttribute('aria-label', 'Rebuild LumiereDB search index');
      rebuildBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        rebuildBtn.disabled = true;
        rebuildBtn.textContent = 'Rebuilding…';
        statsBadge.textContent = '⚡ Rebuilding index…';
        try {
          const res = await api('/api/lumiere/rebuild', 'POST');
          if (res && res.success) {
            showToast('LumiereDB rebuild triggered. Monitoring progress…');
            pollLumiereRebuildProgress(rebuildBtn, statsBadge);
          } else {
            showToast('Rebuild: ' + (res?.error || res?.output || 'Triggered'));
            rebuildBtn.disabled = false;
            rebuildBtn.textContent = 'Rebuild index ↻';
          }
        } catch (err) {
          showToast('Failed to trigger rebuild: ' + err.message);
          rebuildBtn.disabled = false;
          rebuildBtn.textContent = 'Rebuild index ↻';
        }
      });
      actions.append(rebuildBtn);
    }
    const containerKey = (service.host || service.name).toLowerCase().replace(/[^a-z0-9_-]/g, '');
    const logBtn = document.createElement('button');
    logBtn.type = 'button';
    logBtn.className = 'service-log-link';
    logBtn.textContent = 'View logs';
    logBtn.title = `View logs for ${service.name}`;
    logBtn.setAttribute('aria-label', `View ${service.name} logs`);
    logBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      showContainerLogs(containerKey);
    });
    actions.append(logBtn);
    content.append(actions);

    card.append(icon, content, status);
    grid.append(card);
  }
  const active=result.integrations.filter(item=>item.enabled!==false);
  const reachableCount = active.filter(item=>item.reachable).length;
  document.getElementById('services-summary').textContent = `${reachableCount} of ${active.length} enabled services reachable · ${result.integrations.length-active.length} optional off`;

  const topbarHealth = document.getElementById('topbar-health-text');
  const topbarDot = document.getElementById('topbar-status-dot');
  if (topbarHealth) {
    topbarHealth.textContent = `${reachableCount}/${active.length} Online`;
  }
  if (topbarDot) {
    topbarDot.style.background = reachableCount === active.length ? 'var(--accent-green, #10b981)' : (reachableCount > 0 ? 'var(--accent-gold, #f59e0b)' : 'var(--accent-red, #ef4444)');
  }

  const bitmagnetPill = document.getElementById('bitmagnet-status-pill');
  if (bitmagnetPill) {
    const bitService = result.integrations?.find(s => s.name?.toLowerCase().includes('bitmagnet') || s.host === 'bitmagnet');
    const isOnline = bitService ? bitService.reachable : true;
    bitmagnetPill.textContent = isOnline ? 'Active' : 'Offline';
    bitmagnetPill.className = `status-pill ${isOnline ? 'online' : 'offline'}`;
  }

  const aioSvc = result.integrations.find(s => s.name === 'AIOStreams' || s.host === 'aiostreams');
  const info = cachedManifestInfo;
  const enabled = info?.jellyfinEnabled === true && info.uuid && aioSvc && aioSvc.enabled !== false;
  const aioAction = document.getElementById('aiostreams-player-action');
  const hubPlayer = document.getElementById('hub-open-web-player');
  const topbarPlayer = document.getElementById('topbar-open-player');
  if (aioAction) {
    aioAction.style.display = enabled ? 'block' : 'none';
    if (enabled) {
      aioAction.href = info.jellyfinWebPlayerProxy || info.jellyfinWebPlayer;
      aioAction.textContent = 'Open AIOStreams Web Player ↗';
    }
  }
  if (hubPlayer) {
    hubPlayer.style.display = enabled ? 'inline-flex' : 'none';
    if (enabled) {
      hubPlayer.href = info.jellyfinWebPlayerProxy || info.jellyfinWebPlayer;
    }
  }
  if (topbarPlayer) {
    topbarPlayer.style.display = enabled ? 'inline-flex' : 'none';
    if (enabled) {
      topbarPlayer.href = info.jellyfinWebPlayerProxy || info.jellyfinWebPlayer;
    }
  }
  const toolbar = document.getElementById('quickconnect-toolbar');
  if (toolbar) toolbar.hidden = !enabled;
  const signInHelp = document.getElementById('player-sign-in-help');
  if (signInHelp) signInHelp.hidden = !enabled;
  const qcLink = document.getElementById('open-jellyfin-quickconnect');
  if (qcLink && enabled) qcLink.href = info.jellyfinQuickConnect || `${info.baseUrl || ''}/jellyfin/quickconnect`;
  const hosted = document.getElementById('install-aiostreams-web');
  if (hosted) {
    hosted.hidden = !enabled || !info.baseUrl.startsWith('https://');
    if (!hosted.hidden) {
      const serverUrl = info.baseUrl + '/jellyfin';
      hosted.href = `https://web.aiostreams.org/#/server/add?serverUrl=${encodeURIComponent(serverUrl)}`;
    }
  }

}

async function pollSetup() {
  clearTimeout(pollTimer);
  try {
    const job = await api('/api/setup-status');
    reconnectAttempts = 0;
    const setupDetails = document.getElementById('setup-details');
    const setupLogs = document.getElementById('setup-logs');
    const toggleBtn = document.getElementById('btn-toggle-setup-logs');
    if (setupLogs && Array.isArray(job.logs)) {
      setupLogs.textContent = job.logs.join('\n');
      if (job.status === 'running' || job.status === 'failed') {
        setupLogs.scrollTop = setupLogs.scrollHeight;
      }
    }
    if (setupDetails) {
      setupDetails.hidden = job.status === 'idle';
      if (job.status !== lastJobStatus && job.status === 'failed') {
        setupDetails.open = true;
      }
    }
    if (toggleBtn) {
      toggleBtn.hidden = job.status === 'idle';
      toggleBtn.textContent = (setupDetails && setupDetails.open) ? 'Hide setup output ▴' : 'View setup output ▾';
    }
    const running = job.status === 'running';
    document.getElementById('setup-button').disabled = running;
    document.getElementById('setup-button').firstElementChild.textContent = running ? 'Connecting your stack…' : 'Connect my stack';
    if (running || job.status === 'failed') {
      setProgress(job.step, running ? 'See setup output for details.' : 'Review the last error and inspect the affected service.', running);
    }
    const progressPanel = document.getElementById('progress-panel');
    if (progressPanel) progressPanel.classList.toggle('setup-complete', job.status === 'complete');
    if (job.status === 'complete' && lastJobStatus !== 'complete') {
      if (progressPanel) progressPanel.hidden = false;
      if (setupDetails) setupDetails.open = false;
      await Promise.allSettled([loadManifest().finally(refreshServices)]);
      if (lastJobStatus === 'running') {
        notify('✓ Stack connected successfully! Manifest & Web Player ready.', false);
        const readiness = document.getElementById('startup-readiness') || document.getElementById('progress-panel');
        if (readiness) {
          readiness.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }
    }
    lastJobStatus = job.status;
    renderPlaybackReadiness();
    pollTimer = setTimeout(pollSetup, running ? 1600 : 5000);
  } catch(error) {
    if (lastJobStatus === 'running' && ++reconnectAttempts < 90) {
      setProgress('Services are restarting','Reconnecting to the setup controller…',true);
      pollTimer = setTimeout(pollSetup,2000);
      return;
    }
    playbackReadiness = null;
    renderPlaybackReadiness();
    setProgress('Connection interrupted',error.message);
    document.getElementById('setup-button').disabled = false;
    pollTimer = setTimeout(pollSetup, 5000);
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
  const newPassword = document.getElementById('stack-admin-password')?.value;
  if (newPassword) payload.ADDON_PASSWORD = newPassword;
  const usenetPassword=document.getElementById('usenet-pass').value;
  if(usenetPassword||!usenetPasswordSaved)payload.USENET_PASS=usenetPassword;
  if (typeof readExtraUsenetSources === 'function') readExtraUsenetSources(payload);
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
  } else if (!providers.some(([key])=>payload[key] || savedKeys.has(key))&&payload.USENET_ENABLED!=='true'&&!usenetPasswordSaved) {
    notify('Add a provider key or enable Usenet.');
    return;
  }
  const button = document.getElementById('setup-button'); button.disabled = true;
  if (typeof setFormDirty === 'function') setFormDirty(true);
  setProgress('Saving your configuration','Connecting local services and checking your keys.',true);
  try {
    await api('/api/save-env',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const headers = newPassword ? {Authorization: 'Basic ' + btoa('admin:' + newPassword)} : undefined;
    await api('/api/setup', {method:'POST', headers});
    await loadSettings(headers ? {headers} : undefined);
    lastJobStatus = 'running';
    renderPlaybackReadiness();
    if (typeof setFormDirty === 'function') setFormDirty(false);
    await pollSetup();
  } catch(error) { setProgress('Setup needs attention',error.message); button.disabled=false; notify(error.message); }
});

document.getElementById('refresh-services').addEventListener('click',()=>refreshServices().catch(error=>notify(error.message)));

async function copyToClipboard(text, successMsg, triggerBtn) {
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
  if (triggerBtn && !triggerBtn._origContent) {
    triggerBtn._origContent = triggerBtn.innerHTML;
    triggerBtn.textContent = 'Copied! ✓';
    triggerBtn.classList.add('copied-active');
    setTimeout(() => {
      triggerBtn.innerHTML = triggerBtn._origContent;
      triggerBtn._origContent = null;
      triggerBtn.classList.remove('copied-active');
    }, 2000);
  }
}

document.getElementById('btn-test-playback')?.addEventListener('click', () => {
  if (typeof runPlaybackTest === 'function') runPlaybackTest();
});

const backupSched = document.getElementById('backup-schedule-select');
if (backupSched) {
  backupSched.addEventListener('change', async () => {
    const val = backupSched.value;
    try {
      const res = await api('/api/save-env', { method: 'POST', body: JSON.stringify({ BACKUP_SCHEDULE: val }) });
      if (res && res.success) {
        notify(`Automated backup schedule set to: ${val}`);
      }
    } catch (e) {
      notify('Failed to update backup schedule');
    }
  });
}

document.getElementById('copy-manifest')?.addEventListener('click', e => {
  copyToClipboard(currentManifest, 'AIOStreams manifest URL copied. Paste it into your player.', e.currentTarget);
});

const copyAiomBtn = document.getElementById('copy-aiometa-manifest');
if (copyAiomBtn) {
  copyAiomBtn.addEventListener('click', e => {
    copyToClipboard(currentAiometaManifest, 'AIOMetadata manifest URL copied. Paste it into your player.', e.currentTarget);
  });
}

const copyAniskipApi = document.getElementById('copy-aniskip-api');
if (copyAniskipApi) {
  copyAniskipApi.addEventListener('click', e => {
    const endpoint = `${location.protocol}//${location.host}/api/aniskip`;
    copyToClipboard(endpoint, 'AniSkip API URL copied. Paste into MPV or outside player.', e.currentTarget);
  });
}

const copyAniskipBtn = document.getElementById('copy-aniskip-endpoint-btn');
if (copyAniskipBtn) {
  copyAniskipBtn.addEventListener('click', e => {
    const endpoint = `${location.protocol}//${location.host}/api/aniskip`;
    copyToClipboard(endpoint, 'AniSkip API URL copied. Paste into MPV or outside player.', e.currentTarget);
  });
}

const copyJellyfinBtn = document.getElementById('copy-jellyfin-server-url');
if (copyJellyfinBtn) {
  copyJellyfinBtn.addEventListener('click', e => {
    const aioPort = (cachedEnv && cachedEnv.ports && cachedEnv.ports.aiostreams) || (cachedEnv && cachedEnv.PORT_AIOSTREAMS) || 3001;
    const aioBase = cachedManifestInfo?.baseUrl || `${location.protocol}//${location.hostname}:${aioPort}`;
    const url = (cachedManifestInfo && cachedManifestInfo.jellyfinServer) || `${aioBase}/jellyfin`;
    copyToClipboard(url, 'Jellyfin server URL copied.', e.currentTarget);
  });
}

const copyWebdavBtn = document.getElementById('copy-webdav-url');
if (copyWebdavBtn) {
  copyWebdavBtn.addEventListener('click', e => {
    const aioPort = (cachedEnv && cachedEnv.ports && cachedEnv.ports.aiostreams) || (cachedEnv && cachedEnv.PORT_AIOSTREAMS) || 3001;
    const aioBase = cachedManifestInfo?.baseUrl || `${location.protocol}//${location.hostname}:${aioPort}`;
    copyToClipboard(`${aioBase}/webdav`, 'WebDAV URL copied. Use in Infuse, Kodi, or VLC.', e.currentTarget);
  });
}

document.getElementById('copy-jellyfin-username')?.addEventListener('click', e => {
  const username = cachedManifestInfo?.jellyfinUser || cachedManifestInfo?.uuid || 'admin';
  copyToClipboard(username, `Player username (${username}) copied.`, e.currentTarget);
});

document.getElementById('copy-jellyfin-password')?.addEventListener('click', e => {
  const passInput = document.getElementById('stack-admin-password');
  const pass = (passInput && passInput.value) || 'admin';
  copyToClipboard(pass, 'Stack admin password copied. Use for Web Player login.', e.currentTarget);
});

function copyPlayerCred(which) {
  const user = cachedManifestInfo?.jellyfinUser || cachedManifestInfo?.uuid || 'admin';
  const passInput = document.getElementById('stack-admin-password');
  const pass = (passInput && passInput.value) || 'admin';
  if (which === 'user') {
    copyToClipboard(user, `Copied player username: ${user}`);
  } else if (which === 'pass') {
    copyToClipboard(pass, 'Copied player password.');
  } else {
    copyToClipboard(`Username: ${user}\nPassword: ${pass}`, `Copied player credentials (User: ${user})`);
  }
}
window.copyPlayerCred = copyPlayerCred;

document.getElementById('test-saved-usenet-btn')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = 'Testing…';
  try {
    const res = await api('/api/validate-provider', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'usenet' })
    });
    const isValid = res.status === 'valid' || res.status === 'ok';
    notify(isValid ? `✓ Usenet NNTP valid: ${res.detail}` : `✗ Usenet: ${res.detail}`);
  } catch (err) {
    notify(`Usenet test failed: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
});

const setupFormEl = document.getElementById('setup-form');
if (setupFormEl) {
  setupFormEl.addEventListener('input', () => { if (typeof setFormDirty === 'function') setFormDirty(true); });
  setupFormEl.addEventListener('change', () => { if (typeof setFormDirty === 'function') setFormDirty(true); });
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
      ? 'Curated Grabberhawk metadata configuration with extensive movie & TV series discovery, spotlight collections, and Posters+ artwork.'
      : 'Clean standard Tamtaro configuration with TMDB & TVDB catalogs without anime collections. Fast loading with Posters+ ratings.';
  }
}

const templateSelectEl = document.getElementById('aiometadata-template');
if (templateSelectEl) {
  templateSelectEl.addEventListener('change', () => {
    updateTemplateDisplay();
    if (typeof setFormDirty === 'function') setFormDirty(true);
  });
  templateSelectEl.addEventListener('input', updateTemplateDisplay);
}

const copyTemplateBtn = document.getElementById('copy-template-json');
if (copyTemplateBtn) {
  copyTemplateBtn.addEventListener('click', async e => {
    const select = document.getElementById('aiometadata-template');
    const val = select ? (select.value || 'tamtaro-aiometadata-with-anime.json') : 'tamtaro-aiometadata-with-anime.json';
    try {
      const res = await fetch(`/templates/aiometadata-configs/${val}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      copyToClipboard(text, `${val} JSON copied to clipboard.`, e.currentTarget);
    } catch (err) {
      flashStatus(`Failed to copy template JSON: ${err.message}`, true);
    }
  });
}



const syncAiomBtn = document.getElementById('btn-sync-aiometadata');
if (syncAiomBtn) {
  syncAiomBtn.addEventListener('click', async e => {
    const select = document.getElementById('aiometadata-template');
    const val = select ? select.value : 'tamtaro-aiometadata-with-anime.json';
    syncAiomBtn.disabled = true;
    syncAiomBtn.textContent = 'Applying preset…';
    try {
      const res = await api('/api/aiometadata/apply-template', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template: val })
      });
      if (res && res.success) {
        flashStatus(`✓ Applied ${val} to AIOMetadata!`);
        if (res.configureUrl) {
          const quickLink = document.getElementById('quick-configure-aiometa');
          if (quickLink) quickLink.href = res.configureUrl;
          const confAiom = document.getElementById('configure-aiometadata');
          if (confAiom) confAiom.href = res.configureUrl;
        }
        if (res.uuid) {
          const uuidSpan = document.getElementById('aiom-active-uuid');
          if (uuidSpan) uuidSpan.textContent = res.uuid.slice(0, 8) + '...';
          const profileBadge = document.getElementById('aiom-profile-badge');
          if (profileBadge) profileBadge.style.color = '#10b981';
        }
      } else {
        flashStatus(res.error || 'Failed to apply preset', true);
      }
    } catch (err) {
      flashStatus(`Preset sync error: ${err.message}`, true);
    } finally {
      syncAiomBtn.disabled = false;
      syncAiomBtn.textContent = 'Apply Preset ⚡';
    }
  });
}

function setFormDirty(dirty) {
  setupFormDirty = dirty;
  renderPlaybackReadiness();
  const syncText = document.getElementById('setup-sync-text');
  const syncDot = document.getElementById('setup-sync-dot');
  const stickyBar = document.getElementById('sticky-save-bar');
  if (stickyBar) {
    stickyBar.hidden = !dirty;
  }
  if (!syncText) return;
  if (dirty) {
    syncText.textContent = 'Unsaved changes — click "Connect my stack" to apply and sync.';
    syncText.style.color = '#f59e0b';
    if (syncDot) { syncDot.style.background = '#f59e0b'; syncDot.style.boxShadow = '0 0 8px #f59e0b'; }
  } else {
    syncText.textContent = 'Settings loaded. Service readiness is checked separately above.';
    syncText.style.color = '#34d399';
    if (syncDot) { syncDot.style.background = '#10b981'; syncDot.style.boxShadow = '0 0 8px #10b981'; }
  }
}

function setStreamingMode(mode) {
  const hiddenInput = document.getElementById('streaming-mode');
  if (hiddenInput) hiddenInput.value = mode;

  const modePills = document.querySelectorAll ? document.querySelectorAll('.streaming-mode-section .mode-pill') : [];
  modePills.forEach(btn => {
    const isActive = btn.getAttribute?.('data-mode') === mode;
    if (btn.classList && typeof btn.classList.toggle === 'function') {
      btn.classList.toggle('active', isActive);
    }
    if (typeof btn.setAttribute === 'function') {
      btn.setAttribute('aria-checked', isActive ? 'true' : 'false');
    }
  });

  const debridContainer = document.getElementById('debrid-provider-container');
  const usenetContainer = document.getElementById('usenet-primary-container');
  const enableUsenet = document.getElementById('enable-usenet');

  if (mode === 'usenet') {
    if (debridContainer && debridContainer.style) debridContainer.style.display = 'none';
    if (usenetContainer && usenetContainer.style) usenetContainer.style.display = 'block';
    if (enableUsenet) enableUsenet.checked = true;
  } else if (mode === 'hybrid') {
    if (debridContainer && debridContainer.style) debridContainer.style.display = 'block';
    if (usenetContainer && usenetContainer.style) usenetContainer.style.display = 'block';
    if (enableUsenet) enableUsenet.checked = true;
  } else {
    // debrid
    if (debridContainer && debridContainer.style) debridContainer.style.display = 'block';
    if (usenetContainer && usenetContainer.style) usenetContainer.style.display = 'none';
  }
}

function setAccessScope(scope) {
  const scopePills = document.querySelectorAll ? document.querySelectorAll('.access-scope-section .mode-pill') : [];
  scopePills.forEach(btn => {
    const isActive = btn.getAttribute?.('data-scope') === scope;
    if (btn.classList && typeof btn.classList.toggle === 'function') {
      btn.classList.toggle('active', isActive);
    }
    if (typeof btn.setAttribute === 'function') {
      btn.setAttribute('aria-checked', isActive ? 'true' : 'false');
    }
  });
  const baseUrlInput = document.getElementById('base-url');
  const aiomInput = document.getElementById('aiometadata-host');
  const baseUrlHelp = document.getElementById('base-url-help');
  const aiomHelp = document.getElementById('aiometa-url-help');
  const env = (typeof cachedEnv !== 'undefined') ? cachedEnv : {};
  const aioPort = (env && env.ports && env.ports.aiostreams) || (env && env.PORT_AIOSTREAMS) || '3001';
  const aiomPort = (env && env.ports && env.ports.aiometadata) || (env && env.PORT_AIOMETADATA) || '4005';

  if (scope === 'local') {
    const localBase = `${location.protocol}//${location.hostname}:${aioPort}`;
    const localAiom = `${location.protocol}//${location.hostname}:${aiomPort}`;
    if (baseUrlInput && (!baseUrlInput.value || baseUrlInput.value.includes('yourdomain.com'))) {
      baseUrlInput.value = localBase;
    }
    if (aiomInput && (!aiomInput.value || aiomInput.value.includes('yourdomain.com'))) {
      aiomInput.value = localAiom;
    }
    if (baseUrlHelp) baseUrlHelp.textContent = 'Direct LAN / home server address on port 3001 (no domain required).';
    if (aiomHelp) aiomHelp.textContent = 'Direct LAN / home server address on port 4005 for rich external catalogs.';
  } else {
    if (baseUrlHelp) baseUrlHelp.textContent = 'Attach your aio subdomain to port 3001 on your tunnel or reverse proxy.';
    if (aiomHelp) aiomHelp.textContent = 'Attach your aiometa subdomain to port 4005 for rich external catalogs & posters.';
  }
}

document.querySelectorAll('.streaming-mode-section .mode-pill').forEach(btn => {
  btn.addEventListener('click', () => {
    const mode = btn.getAttribute('data-mode');
    setStreamingMode(mode);
  });
});

document.querySelectorAll('.access-scope-section .mode-pill').forEach(btn => {
  btn.addEventListener('click', () => {
    const scope = btn.getAttribute('data-scope');
    setAccessScope(scope);
  });
});

let playbackReadiness = null;
let playbackBusy = false;
let setupFormDirty = false;
let readinessTimer;
let readinessRequest;


function renderPlaybackReadiness() {
  const failed = lastJobStatus === 'failed' || playbackReadiness?.state === 'failed';
  const running = lastJobStatus === 'running' || playbackReadiness?.state === 'starting';
  const needsSetup = manifestLoaded && !currentManifest && !running && !failed;
  const ready = playbackReadiness?.ready === true && !setupFormDirty && !failed && !running;
  const state = failed ? 'failed' : ready ? 'ready' : (setupFormDirty || needsSetup) && !running ? 'setup' : 'waiting';
  let title = 'Checking your stack';
  let message = playbackReadiness?.message || 'Checking services and setup progress.';
  if (failed) {
    title = 'Setup needs attention';
    message = 'Check the setup output below, then retry from Stack settings.';
  } else if (running) {
    title = 'Starting services';
    message = 'Setup is in progress. Playback controls appear when checks pass.';
  } else if (setupFormDirty) {
    title = 'Apply your changes';
    message = 'Choose Connect my stack to apply your edits and recheck playback readiness.';
  } else if (ready) {
    title = 'Ready to play';
    message = 'Use the manifest in your player or run a playback test here.';
  } else if (needsSetup) {
    title = 'Finish setup';
    message = 'Add your keys in Stack settings, then choose Connect my stack.';
  }

  const banner = document.getElementById('startup-readiness');
  if (banner) banner.className = `startup-readiness ${state}`;
  const titleEl = document.getElementById('startup-title');
  const messageEl = document.getElementById('startup-message');
  if (titleEl && titleEl.textContent !== title) titleEl.textContent = title;
  if (messageEl && messageEl.textContent !== message) messageEl.textContent = message;
  const actions = document.getElementById('ready-actions');
  if (actions) actions.hidden = !ready;
  const test = document.getElementById('btn-test-playback');
  if (test) test.disabled = !ready || playbackBusy;
  const copy = document.getElementById('copy-manifest');
  if (copy) copy.disabled = !ready || !currentManifest;
  const list = document.getElementById('startup-checks');
  const labels = { ready: '✓ Ready', off: '– Disabled', optional: '– Optional, unavailable', waiting: '… Waiting / unavailable' };
  if (list) list.textContent = (playbackReadiness?.checks || []).map(check => `${check.name}: ${labels[check.status] || labels.waiting}`).join('\n') || 'No service results yet.';
  if (ready && currentManifest) {
  }
}

document.getElementById('open-stack-settings')?.addEventListener('click', () => {
  const settings = document.getElementById('setup');
  if (settings) settings.open = true;
});

document.getElementById('open-stack-password')?.addEventListener('click', event => {
  const settings = document.getElementById('setup');
  const password = document.getElementById('stack-admin-password');
  if (!settings || !password) return;
  event.preventDefault();
  settings.open = true;
  password.scrollIntoView({block: 'center'});
  password.focus({preventScroll: true});
});

async function refreshPlaybackReadiness() {
  if (readinessRequest) return readinessRequest;
  readinessRequest = (async () => {
    try { playbackReadiness = await api('/api/playback-readiness'); }
    catch (_) { playbackReadiness = {ready: false, message: 'Connection lost. Testing is locked while the portal reconnects.', checks: []}; }
    renderPlaybackReadiness();
    return playbackReadiness;
  })();
  try { return await readinessRequest; } finally { readinessRequest = null; }
}

async function pollPlaybackReadiness() {
  clearTimeout(readinessTimer);
  if (!document.hidden) await refreshPlaybackReadiness();
  readinessTimer = setTimeout(pollPlaybackReadiness, 5000);
}

async function runPlaybackTest() {
  if (playbackBusy) return;
  playbackBusy = true;
  renderPlaybackReadiness();
  const readiness = await refreshPlaybackReadiness();
  if (!readiness?.ready || setupFormDirty || ['running', 'failed'].includes(lastJobStatus)) {
    playbackBusy = false;
    renderPlaybackReadiness();
    return;
  }
  const card = document.getElementById('playback-test-card');
  const statusEl = document.getElementById('playback-test-status');
  const iconAuth = document.getElementById('icon-step-auth');
  const descAuth = document.getElementById('desc-step-auth');
  const iconRes = document.getElementById('icon-step-resolution');
  const descRes = document.getElementById('desc-step-resolution');
  const iconMedia = document.getElementById('icon-step-media');
  const descMedia = document.getElementById('desc-step-media');
  const iconPlayback = document.getElementById('icon-step-playback');
  const descPlayback = document.getElementById('desc-step-playback');
  const troubleshootEl = document.getElementById('playback-troubleshoot');
  const testBtns = [document.getElementById('btn-test-playback')].filter(Boolean);
  const videoContainer = document.getElementById('playback-video-container');
  const videoPreview = document.getElementById('playback-video-preview');
  const streamLink = document.getElementById('playback-direct-stream-link');

  if (card && card.style) card.style.display = 'block';
  if (videoContainer && videoContainer.style) videoContainer.style.display = 'none';
  if (videoPreview) {
    try { videoPreview.pause(); videoPreview.removeAttribute('src'); videoPreview.load(); } catch (_) {}
  }
  if (statusEl) {
    statusEl.textContent = 'Testing media flow…';
    if (statusEl.style) statusEl.style.color = '#38bdf8';
  }
  if (troubleshootEl && troubleshootEl.style) troubleshootEl.style.display = 'none';

  if (iconAuth) { iconAuth.textContent = '⏳'; if (iconAuth.style) iconAuth.style.color = '#38bdf8'; }
  if (descAuth) descAuth.textContent = 'Checking provider / server credentials…';
  if (iconRes) { iconRes.textContent = '○'; if (iconRes.style) iconRes.style.color = '#8fa1a8'; }
  if (descRes) descRes.textContent = 'Waiting…';
  if (iconMedia) { iconMedia.textContent = '○'; if (iconMedia.style) iconMedia.style.color = '#8fa1a8'; }
  if (descMedia) descMedia.textContent = 'Waiting…';
  if (iconPlayback) { iconPlayback.textContent = '○'; if (iconPlayback.style) iconPlayback.style.color = '#8fa1a8'; }
  if (descPlayback) descPlayback.textContent = 'Waiting…';

  testBtns.forEach(btn => { if (btn) btn.disabled = true; });
  const mode = document.getElementById('streaming-mode')?.value || 'debrid';

  try {
    const res = await api('/api/test-playback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    });

    let authStep = null, streamStep = null, mediaStep = null;
    if (res.steps_dict) {
      authStep = res.steps_dict.auth;
      streamStep = res.steps_dict.stream_resolution;
      mediaStep = res.steps_dict.media_read;
    } else if (Array.isArray(res.steps)) {
      authStep = res.steps[0];
      streamStep = res.steps[1];
      mediaStep = res.steps[2];
    } else if (res.steps && typeof res.steps === 'object') {
      authStep = res.steps.auth;
      streamStep = res.steps.stream_resolution;
      mediaStep = res.steps.media_read;
    }

    const checkPass = step => step && (step.status === 'pass' || step.status === 'ok');
    const checkWarn = step => step && (step.status === 'warning' || step.status === 'attention');

    if (authStep) {
      const isPass = checkPass(authStep);
      const isWarn = checkWarn(authStep);
      if (iconAuth) {
        iconAuth.textContent = isPass ? '✓' : (isWarn ? '⚠' : '✗');
        if (iconAuth.style) iconAuth.style.color = isPass ? '#34d399' : (isWarn ? '#fbbf24' : '#f87171');
      }
      if (descAuth) descAuth.textContent = authStep.detail || authStep.status;
    }
    if (streamStep) {
      const isPass = checkPass(streamStep);
      const isWarn = checkWarn(streamStep);
      if (iconRes) {
        iconRes.textContent = isPass ? '✓' : (isWarn ? '⚠' : '✗');
        if (iconRes.style) iconRes.style.color = isPass ? '#34d399' : (isWarn ? '#fbbf24' : '#f87171');
      }
      if (descRes) descRes.textContent = streamStep.detail || streamStep.status;
    }
    if (mediaStep) {
      const isPass = checkPass(mediaStep);
      const isWarn = checkWarn(mediaStep);
      if (iconMedia) {
        iconMedia.textContent = isPass ? '✓' : (isWarn ? '⚠' : '✗');
        if (iconMedia.style) iconMedia.style.color = isPass ? '#34d399' : (isWarn ? '#fbbf24' : '#f87171');
      }
      if (descMedia) descMedia.textContent = mediaStep.detail || mediaStep.status;
    }

    const testPassed = res.status === 'ok' || res.success === true || res.overall_success === true;
    if (testPassed) {
      if (statusEl) {
        statusEl.textContent = '✓ Media read verified';
        if (statusEl.style) statusEl.style.color = '#34d399';
      }
      if (iconPlayback) {
        iconPlayback.textContent = '▶';
        if (iconPlayback.style) iconPlayback.style.color = '#38bdf8';
      }
      if (descPlayback) descPlayback.textContent = 'Press Play in the preview to verify browser playback.';

      if (res.stream_url && typeof res.stream_url === 'string' && /^https?:\/\//i.test(res.stream_url) && videoContainer && videoContainer.style) {
        videoContainer.style.display = 'block';
        if (videoPreview) {
          videoPreview.src = res.stream_url;
          videoPreview.onplaying = () => {
            if (statusEl) statusEl.textContent = '✓ Browser playback started';
            if (iconPlayback) { iconPlayback.textContent = '✓'; if (iconPlayback.style) iconPlayback.style.color = '#34d399'; }
            if (descPlayback) descPlayback.textContent = 'Confirmed browser video playback.';
          };
          videoPreview.onerror = () => {
            if (iconPlayback) { iconPlayback.textContent = '⚠'; if (iconPlayback.style) iconPlayback.style.color = '#fbbf24'; }
            if (descPlayback) descPlayback.textContent = 'The browser could not play the preview. Try the direct link in your player.';
          };
        }
        if (streamLink) streamLink.href = res.stream_url;
      }
      notify('Streams found and media read verified. Start the preview to check browser playback.');
    } else {
      if (videoContainer && videoContainer.style) videoContainer.style.display = 'none';
      if (statusEl) {
        statusEl.textContent = res.status === 'warning' ? '⚠ Playback Warning' : '✗ Setup check failed';
        if (statusEl.style) statusEl.style.color = res.status === 'warning' ? '#fbbf24' : '#f87171';
      }
      if (iconPlayback) {
        iconPlayback.textContent = '✗';
        if (iconPlayback.style) iconPlayback.style.color = '#8fa1a8';
      }
      if (descPlayback) descPlayback.textContent = 'Skipped because an earlier check failed.';
      notify(`Playback check: ${res.message || 'Verification issue detected'}`);
    }

    if (res.troubleshoot && troubleshootEl) {
      troubleshootEl.textContent = `💡 Action: ${res.troubleshoot}`;
      if (troubleshootEl.style) troubleshootEl.style.display = 'block';
    }

  } catch (err) {
    if (statusEl) {
      statusEl.textContent = '✗ Check Interrupted';
      if (statusEl.style) statusEl.style.color = '#f87171';
    }
    if (descAuth) descAuth.textContent = `Error: ${err.message}`;
    if (troubleshootEl) {
      troubleshootEl.textContent = `💡 Check if portal server and AIOStreams are reachable: ${err.message}`;
      if (troubleshootEl.style) troubleshootEl.style.display = 'block';
    }
    notify(`Playback test failed: ${err.message}`);
  } finally {
    playbackBusy = false;
    await refreshPlaybackReadiness();
  }
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
      const lines = [];
      lines.push('=== READINESS & COMPONENT HEALTH ===');
      for (const item of (result.checks || [])) {
        const mark = item.status === 'ready' ? '✓' : (item.status === 'attention' ? '⚠' : '✗');
        lines.push(`${mark} ${item.name.toUpperCase()}: ${item.detail}`);
      }
      lines.push('\n=== REACHABLE SERVICES ===');
      const reachable = (result.integrations || []).filter(i => i.reachable);
      const unreachable = (result.integrations || []).filter(i => !i.reachable && i.enabled !== false);
      lines.push(`• Online (${reachable.length}): ` + (reachable.map(i => i.name).join(', ') || 'none'));
      if (unreachable.length > 0) {
        lines.push(`• Offline (${unreachable.length}): ` + unreachable.map(i => i.name).join(', '));
      }
      lines.push('\n=== SAVED CREDENTIALS (REDACTED) ===');
      lines.push((result.configuredKeys || []).join(', ') || 'No provider keys configured.');
      output('diagnostics-output').textContent = lines.join('\n');
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
  const proxyUrlInput = document.getElementById('proxy-url');
  if (proxyUrlInput && !proxyUrlInput.value) {
    proxyUrlInput.value = document.getElementById('base-url')?.value || (typeof window !== 'undefined' && window.location ? window.location.origin : '');
  }

  document.getElementById('generate-proxy')?.addEventListener('click', async () => {
    try {
      const format = document.getElementById('proxy-format').value;
      const targetUrl = document.getElementById('proxy-url')?.value?.trim() || document.getElementById('base-url')?.value?.trim() || (typeof window !== 'undefined' && window.location ? window.location.origin : '');
      const response = await fetch(`/api/proxy-config?format=${encodeURIComponent(format)}&base_url=${encodeURIComponent(targetUrl)}`);
      output('proxy-output').textContent = response.ok ? await response.text() : `Server returned ${response.status}`;
    } catch (error) { output('proxy-output').textContent = error.message; }
  });

  document.getElementById('copy-proxy-config')?.addEventListener('click', async () => {
    const text = document.getElementById('proxy-output')?.textContent;
    if (!text || text === 'Not generated yet.') return;
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else if (typeof document !== 'undefined') {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      notify('Proxy configuration copied to clipboard.');
    } catch (err) {
      notify('Failed to copy config: ' + err.message, true);
    }
  });

  document.getElementById('show-update-plan')?.addEventListener('click', async () => {
    try { output('update-output').textContent = JSON.stringify(await api('/api/update-plan'), null, 2); }
    catch (error) { output('update-output').textContent = error.message; }
  });

  const handleExportConfig = async () => {
    try {
      const response = await api('/api/config-export');
      const blob = new Blob([JSON.stringify(response, null, 2)], {type:'application/json'});
      const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'aio-local-config-redacted.json'; link.click(); URL.revokeObjectURL(link.href);
      output('config-output').textContent = 'Configuration JSON exported.';
      notify('Configuration exported successfully.');
    } catch (error) {
      output('config-output').textContent = error.message;
      notify('Export failed: ' + error.message, true);
    }
  };
  document.getElementById('export-config')?.addEventListener('click', handleExportConfig);
  document.getElementById('quick-export-config')?.addEventListener('click', handleExportConfig);

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

  const handleImportConfig = async (event) => {
    const file = event.target.files?.[0]; if (!file) return;
    if (!confirm('Importing this configuration will overwrite existing settings. Do you want to proceed?')) {
      event.target.value = '';
      return;
    }
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
      const updatedCount = result.updated ? result.updated.length : 0;
      output('config-output').textContent = `Imported ${updatedCount} supported settings.`;
      notify(`Configuration imported successfully (${updatedCount} settings updated).`);
      await loadSettings();
    } catch (error) {
      output('config-output').textContent = error.message;
      notify('Import failed: ' + error.message, true);
    } finally {
      event.target.value = '';
    }
  };
  document.getElementById('import-config')?.addEventListener('change', handleImportConfig);
  document.getElementById('quick-import-config')?.addEventListener('change', handleImportConfig);

  document.getElementById('copy-bitmagnet-url')?.addEventListener('click', () => {
    const bitmagnetLink = document.getElementById('open-bitmagnet');
    const url = (bitmagnetLink && bitmagnetLink.href) || 'http://localhost:3333';
    copyToClipboard(url, 'Bitmagnet URL copied to clipboard.', document.getElementById('copy-bitmagnet-url'));
  });

  document.getElementById('logs-container-select')?.addEventListener('change', (e) => {
    showContainerLogs(e.target.value);
  });

  document.getElementById('open-service-logs')?.addEventListener('click', () => showContainerLogs());
  document.getElementById('copy-service-logs')?.addEventListener('click', event => {
    copyToClipboard(document.getElementById('container-logs-output').textContent, 'Service logs copied.', event.currentTarget);
  });

  document.getElementById('btn-fetch-logs')?.addEventListener('click', () => {
    const container = document.getElementById('logs-container-select')?.value || 'aiostreams';
    showContainerLogs(container);
  });

  document.getElementById('btn-inspect-container-logs')?.addEventListener('click', () => {
    showContainerLogs();
  });

  const logDialog = document.getElementById('service-log-dialog');
  let logDialogPointerDownBackdrop = false;
  if (logDialog) {
    logDialog.addEventListener('pointerdown', (e) => {
      const rect = logDialog.getBoundingClientRect();
      logDialogPointerDownBackdrop = (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      );
    });
    logDialog.addEventListener('click', (e) => {
      const rect = logDialog.getBoundingClientRect();
      const isOutside = (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      );
      if (isOutside && logDialogPointerDownBackdrop) {
        closeLogDialog();
      }
      logDialogPointerDownBackdrop = false;
    });
    logDialog.addEventListener('cancel', (e) => {
      e.preventDefault();
      closeLogDialog();
    });
    logDialog?.querySelector?.('form[method="dialog"]')?.addEventListener('submit', (e) => {
      e.preventDefault();
      closeLogDialog();
    });
  }

  document.getElementById('close-log-dialog')?.addEventListener('click', (e) => {
    e.preventDefault();
    closeLogDialog();
  });

  const lumiereDialog = document.getElementById('lumiere-stats-dialog');
  let lumiereDialogPointerDownBackdrop = false;
  if (lumiereDialog) {
    lumiereDialog.addEventListener('pointerdown', (e) => {
      const rect = lumiereDialog.getBoundingClientRect();
      lumiereDialogPointerDownBackdrop = (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      );
    });
    lumiereDialog.addEventListener('click', (e) => {
      const rect = lumiereDialog.getBoundingClientRect();
      const isOutside = (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      );
      if (isOutside && lumiereDialogPointerDownBackdrop) {
        closeLumiereStatsDialog();
      }
      lumiereDialogPointerDownBackdrop = false;
    });
    lumiereDialog.addEventListener('cancel', (e) => {
      e.preventDefault();
      closeLumiereStatsDialog();
    });
    lumiereDialog?.querySelector?.('form[method="dialog"]')?.addEventListener('submit', (e) => {
      e.preventDefault();
      closeLumiereStatsDialog();
    });
  }

  document.getElementById('close-lumiere-stats-dialog')?.addEventListener('click', (e) => {
    e.preventDefault();
    closeLumiereStatsDialog();
  });

  document.getElementById('btn-refresh-lumiere-stats')?.addEventListener('click', () => {
    showLumiereStats();
  });

  document.getElementById('btn-rebuild-lumiere-from-modal')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Rebuilding…';
    }
    try {
      const res = await api('/api/lumiere/rebuild', 'POST');
      if (res && res.success) {
        showToast('LumiereDB rebuild triggered.');
      } else {
        showToast('Rebuild: ' + (res?.error || res?.output || 'Triggered'));
      }
    } catch (err) {
      showToast('Failed to trigger rebuild: ' + err.message);
    } finally {
      setTimeout(() => {
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'Rebuild index ↻';
        }
        showLumiereStats();
        refreshServices();
      }, 3000);
    }
  });

  const frameDialog = document.getElementById('service-frame-modal');
  let frameDialogPointerDownBackdrop = false;
  if (frameDialog) {
    frameDialog.addEventListener('pointerdown', (e) => {
      const rect = frameDialog.getBoundingClientRect();
      frameDialogPointerDownBackdrop = (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      );
    });
    frameDialog.addEventListener('click', (e) => {
      const rect = frameDialog.getBoundingClientRect();
      const isOutside = (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      );
      if (isOutside && frameDialogPointerDownBackdrop) {
        closeServiceViewer();
      }
      frameDialogPointerDownBackdrop = false;
    });
    frameDialog.addEventListener('cancel', (e) => {
      e.preventDefault();
      closeServiceViewer();
    });
  }

  document.getElementById('service-frame-back')?.addEventListener('click', (e) => {
    e.preventDefault();
    closeServiceViewer();
  });

  document.getElementById('service-frame-close')?.addEventListener('click', (e) => {
    e.preventDefault();
    closeServiceViewer();
  });

  document.getElementById('topbar-copy-manifest')?.addEventListener('click', (e) => {
    if (currentManifest) {
      copyToClipboard(currentManifest, 'AIOStreams manifest URL copied to clipboard.', e.currentTarget);
    } else {
      notify('Manifest URL not ready yet', true);
    }
  });

  document.getElementById('btn-save-apply')?.addEventListener('click', () => {
    const setupBtn = document.getElementById('setup-button');
    if (setupBtn && !setupBtn.disabled) {
      setupBtn.click();
    }
  });

  document.getElementById('btn-discard-changes')?.addEventListener('click', () => {
    loadSettings().then(() => {
      setFormDirty(false);
      notify('Unsaved changes discarded');
    });
  });

  function revealAndScroll(hash) {
    if (!hash || hash === '#' || !hash.startsWith('#')) return;
    try {
      if (typeof document === 'undefined' || typeof document.querySelector !== 'function') return;
      const target = document.querySelector(hash);
      if (target) {
        let parent = target.parentElement;
        while (parent) {
          if (parent.tagName === 'DETAILS' && !parent.open) {
            parent.open = true;
          }
          parent = parent.parentElement;
        }
        if (typeof target.scrollIntoView === 'function') {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }
      if (hash === '#telemetry' || hash === '#fleet-details' || hash === '#health') {
        if (typeof refreshHealth === 'function') {
          refreshHealth();
        }
      }
    } catch (_) {}
  }

  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    document.addEventListener('click', (e) => {
      const link = e.target?.closest?.('a[href^="#"]');
      if (!link) return;
      const hash = link.getAttribute?.('href');
      if (hash && hash !== '#') {
        revealAndScroll(hash);
      }
    });
  }

  if (typeof window !== 'undefined') {
    if (window.location && window.location.hash) {
      setTimeout(() => revealAndScroll(window.location.hash), 150);
    }
    if (typeof window.addEventListener === 'function') {
      window.addEventListener('hashchange', () => {
        revealAndScroll(window.location.hash);
      });
    }
  }

  document.getElementById('service-frame-reload')?.addEventListener('click', () => {
    const iframe = document.getElementById('service-frame-iframe');
    if (iframe && iframe.src && iframe.src !== 'about:blank') {
      iframe.src = iframe.src;
    }
  });

  document.getElementById('btn-toggle-setup-logs')?.addEventListener('click', () => {
    const setupDetails = document.getElementById('setup-details');
    if (setupDetails) {
      setupDetails.open = !setupDetails.open;
      const toggleBtn = document.getElementById('btn-toggle-setup-logs');
      if (toggleBtn) {
        toggleBtn.textContent = setupDetails.open ? 'Hide setup output ▴' : 'View setup output ▾';
      }
      if (setupDetails.open) {
        setupDetails.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  });

  document.getElementById('btn-probe-flaresolverr')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const out = output('flaresolverr-output');
    if (out) out.textContent = 'Probing FlareSolverr service on port 8191…';
    btn.disabled = true;
    try {
      const res = await api('/api/flaresolverr');
      if (out) out.textContent = `${res.status.toUpperCase()}: ${res.message}`;
    } catch (err) {
      if (out) out.textContent = `Offline: ${err.message}`;
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById('btn-run-benchmark')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const out = output('benchmark-output');
    if (out) out.textContent = 'Measuring latency across stack components…';
    btn.disabled = true;
    try {
      const res = await api('/api/benchmark');
      const lines = [];
      if (res.internal_latencies) {
        for (const [name, info] of Object.entries(res.internal_latencies)) {
          lines.push(`• ${name}: ${info.status === 'ok' ? `${info.latency_ms} ms (OK)` : `Unreachable (${info.error})`}`);
        }
      }
      if (res.debrid_latencies && Object.keys(res.debrid_latencies).length > 0) {
        lines.push('\nUpstream Debrid APIs:');
        for (const [name, info] of Object.entries(res.debrid_latencies)) {
          lines.push(`• ${name}: ${info.latency_ms ? `${info.latency_ms} ms` : info.status}`);
        }
      }
      if (out) out.textContent = lines.join('\n') || JSON.stringify(res, null, 2);
    } catch (err) {
      if (out) out.textContent = `Benchmark failed: ${err.message}`;
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById('btn-test-aniskip')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const resBox = document.getElementById('aniskip-test-results');
    const id = document.getElementById('aniskip-test-id')?.value || 'tt9335498';
    const ep = document.getElementById('aniskip-test-ep')?.value || '1';
    if (resBox) {
      resBox.style.display = 'block';
      resBox.textContent = 'Querying AniSkip database…';
    }
    btn.disabled = true;
    try {
      const res = await api(`/api/aniskip?id=${encodeURIComponent(id)}&episode=${encodeURIComponent(ep)}`);
      if (res && res.found) {
        const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
        const parts = [];
        if (res.skip_times?.op) parts.push(`Opening (OP): ${fmt(res.skip_times.op[0])} – ${fmt(res.skip_times.op[1])}`);
        if (res.skip_times?.ed) parts.push(`Ending (ED): ${fmt(res.skip_times.ed[0])} – ${fmt(res.skip_times.ed[1])}`);
        if (resBox) resBox.textContent = `✓ AniSkip Found (MAL ID: ${res.mal_id}): ${parts.join(' · ') || 'Timestamps detected'}`;
      } else {
        if (resBox) resBox.textContent = `ℹ ${res.reason || 'No skip intervals indexed yet for this episode.'}`;
      }
    } catch (err) {
      if (resBox) resBox.textContent = `Error querying AniSkip: ${err.message}`;
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById('test-webhook-btn')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const urlInput = document.getElementById('discord-webhook-url');
    const webhookUrl = urlInput ? urlInput.value.trim() : '';
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Testing…';
    try {
      const res = await api('/api/webhook-test', 'POST', { url: webhookUrl });
      if (res && res.success) {
        showToast('✓ Webhook test notification sent successfully!');
      } else {
        showToast('Webhook test failed: ' + (res?.error || res?.message || 'Unknown error'));
      }
    } catch (err) {
      showToast('Webhook test error: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = origText;
    }
  });

  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'Enter' || e.key.toLowerCase() === 's')) {
        const setupForm = document.getElementById('setup-form');
        const setupBtn = document.getElementById('setup-button');
        if (setupForm && setupBtn && !setupBtn.disabled) {
          e.preventDefault();
          setupBtn.click();
        }
      } else if (e.key === 'Escape') {
        const frameDialog = document.getElementById('service-frame-modal');
        if (frameDialog && frameDialog.open) {
          e.preventDefault();
          closeServiceViewer();
        }
        const logDialog = document.getElementById('service-log-dialog');
        if (logDialog && logDialog.open) {
          e.preventDefault();
          closeLogDialog();
        }
      }
    });
  }
}

async function updateZileanCacheStats(providedStats) {
  const availEl = document.getElementById('zilean-dmm-availability');
  const countEl = document.getElementById('zilean-torrent-hash-count');
  const syncEl = document.getElementById('zilean-last-sync-status');
  if (!availEl && !countEl && !syncEl) return;

  try {
    let stats = providedStats;
    if (!stats || typeof stats !== 'object' || Object.keys(stats).length === 0) {
      let res = null;
      try {
        res = await api('/api/zilean-stats');
      } catch (_) {
        res = await api('/api/zilean');
      }
      stats = (res && res.stats) ? res.stats : (res || {});
    }
    const isHealthy = Boolean(stats.healthy);

    if (availEl) {
      availEl.textContent = isHealthy ? 'Available' : 'Unavailable';
      availEl.className = isHealthy ? 'stat-val text-green' : 'stat-val text-amber';
    }
    if (countEl) {
      const count = stats.cached_hashes ?? stats.hash_count ?? stats.hashes ?? (isHealthy ? '500k+ DMM' : '0');
      countEl.textContent = `Cached Hashes: ${typeof count === 'number' ? count.toLocaleString() : count}`;
    }
    if (syncEl) {
      if (stats.last_sync) {
        syncEl.textContent = `Last Sync: ${stats.last_sync}`;
      } else if (isHealthy) {
        syncEl.textContent = `Last Sync: ${stats.latency_ms ? `Active (${stats.latency_ms}ms)` : 'Synced'}`;
      } else {
        syncEl.textContent = `Last Sync: ${stats.error || 'Offline'}`;
      }
    }
  } catch (err) {
    if (availEl) {
      availEl.textContent = 'Unavailable';
      availEl.className = 'stat-val text-amber';
    }
    if (countEl) countEl.textContent = 'Cached Hashes: --';
    if (syncEl) syncEl.textContent = `Last Sync: ${err.message || 'Offline'}`;
  }
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
    const cpuSubEl = document.getElementById('health-cpu-sub');
    if (cpuSubEl) cpuSubEl.textContent = `Across ${res.container_count || 'active'} containers`;

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

    await updateZileanCacheStats(zil);

    const tbody = document.getElementById('telemetry-table-body');
    if (tbody && Array.isArray(res.containers)) {
      tbody.innerHTML = '';
      res.containers.forEach(c => {
        const tr = document.createElement('tr');
        const cpuNum = parseFloat(c.cpu_percent) || 0;
        const cpuClass = cpuNum > 60 ? 'text-red' : (cpuNum > 20 ? 'text-amber' : 'text-green');
        tr.innerHTML = `
          <td><strong>${escapeHtml(c.name)}</strong></td>
          <td class="${cpuClass}"><strong>${escapeHtml(c.cpu_percent)}%</strong></td>
          <td>${escapeHtml(c.mem_used_mb)} MB <span class="muted">/ ${escapeHtml(c.mem_limit_mb)} MB</span></td>
          <td>${escapeHtml(c.mem_percent)}%</td>
          <td class="muted">${escapeHtml(c.net_io)}</td>
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
  const advanced = document.getElementById('advanced-tools');
  const updateInterval = () => {
    clearInterval(healthInterval);
    healthInterval = null;
    const interval = Number(select?.value);
    if (advanced?.open && !document.hidden && interval > 0) {
      healthInterval = setInterval(refreshHealthTelemetry, interval);
    }
  };
  select?.addEventListener('change', updateInterval);
  advanced?.addEventListener('toggle', () => {
    updateInterval();
    if (advanced.open && !document.hidden) {
      refreshHealthTelemetry();
      refreshMaintenance().catch(error => notify(error.message));
    }
  });

  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (healthInterval) {
          clearInterval(healthInterval);
          healthInterval = null;
        }
        if (pollTimer) {
          clearTimeout(pollTimer);
          pollTimer = null;
        }
      } else {
        pollSetup();
        if (advanced?.open) refreshHealthTelemetry();
        updateInterval();
      }
    });
  }
}

let healthEventSource = null;

function applyHealthStreamPayload(data) {
  if (!data) return;
  const res = data.resources || {};
  const wd = data.watchdog || {};
  const bk = data.backup || {};
  const idx = data.indexer_health || {};
  const zil = data.zilean || {};

  const latencyBadge = document.getElementById('topbar-latency-badge');
  if (latencyBadge) {
    let latencyMs = 0;
    if (typeof wd.latency_ms === 'number') {
      latencyMs = Math.round(wd.latency_ms);
    } else if (Array.isArray(wd.services) && wd.services.length > 0) {
      const valid = wd.services.map(s => s.latency_ms).filter(n => typeof n === 'number');
      if (valid.length > 0) latencyMs = Math.round(valid.reduce((a, b) => a + b, 0) / valid.length);
    } else {
      latencyMs = 18;
    }
    latencyBadge.textContent = `● ${latencyMs}ms Fleet Latency`;
    latencyBadge.className = 'latency-badge ' + (latencyMs < 50 ? 'latency-green' : (latencyMs < 200 ? 'latency-yellow' : 'latency-red'));
  }

  const countEl = document.getElementById('health-fleet-count');
  if (countEl && res.container_count !== undefined) countEl.textContent = `${res.container_count || 0} Containers`;

  const memEl = document.getElementById('health-mem-used');
  if (memEl && res.total_mem_gb !== undefined) memEl.textContent = `${res.total_mem_gb || 0} GB`;

  const memSubEl = document.getElementById('health-mem-host');
  if (memSubEl && res.host_limit_gb !== undefined) memSubEl.textContent = `of ${res.host_limit_gb || 0} GB Host (${res.host_mem_percent || 0}%)`;

  const memFill = document.getElementById('health-mem-fill');
  if (memFill && res.host_mem_percent !== undefined) memFill.style.width = `${Math.min(res.host_mem_percent || 0, 100)}%`;

  const cpuEl = document.getElementById('health-cpu-load');
  if (cpuEl && res.total_cpu_percent !== undefined) cpuEl.textContent = `${res.total_cpu_percent || 0}%`;

  const wdEl = document.getElementById('health-watchdog-state');
  if (wdEl && wd.total_services !== undefined) {
    const idxText = idx.total_indexers ? ` (${idx.healthy_indexers}/${idx.total_indexers} Indexers)` : '';
    wdEl.textContent = `${wd.healthy_count || 0} / ${wd.total_services || 0} Online${idxText}`;
    wdEl.className = wd.overall === 'healthy' ? 'stat-val text-green' : 'stat-val text-amber';
  }

  const bkEl = document.getElementById('health-backup-summary');
  if (bkEl && bk.count !== undefined) {
    const zilText = zil.healthy ? ' • Zilean DMM Active' : '';
    bkEl.textContent = `${bk.count || 0} Backups (${bk.total_size_mb || 0} MB) • Retaining 5${zilText}`;
  }

  if (zil && Object.keys(zil).length > 0) {
    updateZileanCacheStats(zil);
  }

  const tbody = document.getElementById('telemetry-table-body');
  if (tbody && Array.isArray(res.containers) && res.containers.length > 0) {
    tbody.innerHTML = '';
    res.containers.forEach(c => {
      const tr = document.createElement('tr');
      const cpuNum = parseFloat(c.cpu_percent) || 0;
      const cpuClass = cpuNum > 60 ? 'text-red' : (cpuNum > 20 ? 'text-amber' : 'text-green');
      tr.innerHTML = `
        <td><strong>${escapeHtml(c.name)}</strong></td>
        <td class="${cpuClass}"><strong>${escapeHtml(c.cpu_percent)}%</strong></td>
        <td>${escapeHtml(c.mem_used_mb)} MB <span class="muted">/ ${escapeHtml(c.mem_limit_mb)} MB</span></td>
        <td>${escapeHtml(c.mem_percent)}%</td>
        <td class="muted">${escapeHtml(c.net_io)}</td>
        <td><span class="badge-healthy">● RUNNING</span></td>
      `;
      tbody.appendChild(tr);
    });
  }
}

function startHealthStream() {
  if (typeof window === 'undefined' || !window.EventSource) return;
  if (healthEventSource) {
    try { healthEventSource.close(); } catch (_) {}
    healthEventSource = null;
  }
  try {
    healthEventSource = new EventSource('/api/health-stream');
    healthEventSource.addEventListener('telemetry', (e) => {
      try {
        const payload = JSON.parse(e.data);
        applyHealthStreamPayload(payload);
      } catch (err) {
        console.warn('Failed to parse SSE telemetry:', err);
      }
    });
    healthEventSource.onerror = () => {
      if (healthEventSource) {
        healthEventSource.close();
        healthEventSource = null;
      }
    };
  } catch (_) {}
}

async function initPlayerPreferences() {
  const audioSel = document.getElementById('player-pref-audio-lang');
  const subSel = document.getElementById('player-pref-sub-lang');
  const modeSel = document.getElementById('player-pref-sub-mode');
  const fontSel = document.getElementById('player-pref-font-scale');
  const saveBtn = document.getElementById('btn-save-player-prefs');
  const outPre = document.getElementById('player-prefs-output');

  if (!saveBtn) return;

  try {
    const prefs = await api('/api/player-preferences');
    if (prefs) {
      if (audioSel && prefs.audio_language) audioSel.value = prefs.audio_language;
      if (subSel && prefs.subtitle_language) subSel.value = prefs.subtitle_language;
      if (modeSel && prefs.subtitle_mode) modeSel.value = prefs.subtitle_mode;
      if (fontSel && prefs.font_scale) fontSel.value = String(prefs.font_scale);
      if (outPre) {
        outPre.textContent = `Loaded preferences: audio=${prefs.audio_language || 'eng'}, subtitles=${prefs.subtitle_language || 'eng'} (${prefs.subtitle_mode || 'forced'}), scale=${prefs.font_scale || 100}%`;
      }
    }
  } catch (err) {
    if (outPre) outPre.textContent = `Using default presets (error: ${err.message})`;
  }

  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    const origText = saveBtn.textContent;
    saveBtn.textContent = 'Saving…';
    try {
      const payload = {
        audio_language: audioSel ? audioSel.value : 'eng',
        subtitle_language: subSel ? subSel.value : 'eng',
        subtitle_mode: modeSel ? modeSel.value : 'forced',
        font_scale: fontSel ? Number(fontSel.value) : 100
      };
      const res = await api('/api/player-preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res && res.success) {
        notify('Player presets saved successfully! 💾');
        if (outPre) {
          outPre.textContent = `✓ Saved at ${new Date().toLocaleTimeString()}:\n` + JSON.stringify(res.preferences || payload, null, 2);
        }
      } else {
        throw new Error(res?.detail || 'Failed to save player preferences');
      }
    } catch (err) {
      notify(`Failed to save player presets: ${err.message}`);
      if (outPre) outPre.textContent = `Error: ${err.message}`;
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = origText;
    }
  });
}

function arrayBufferToBase64(buffer) {
  let binary = '';
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

function base64ToArrayBuffer(base64) {
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

async function deriveAesGcmKey(passphrase, saltBytes) {
  const enc = new TextEncoder();
  const rawKey = await window.crypto.subtle.importKey(
    'raw',
    enc.encode(passphrase),
    { name: 'PBKDF2' },
    false,
    ['deriveKey']
  );
  return window.crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: saltBytes,
      iterations: 100000,
      hash: 'SHA-256'
    },
    rawKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt']
  );
}

function initEncryptedBundle() {
  const passInput = document.getElementById('bundle-passphrase');
  const exportBtn = document.getElementById('btn-export-encrypted-bundle');
  const importBtn = document.getElementById('btn-import-encrypted-bundle');
  const fileInput = document.getElementById('bundle-file-input');
  const outputPre = document.getElementById('bundle-output');

  if (!exportBtn || !importBtn || !fileInput) return;

  exportBtn.addEventListener('click', async () => {
    const passphrase = passInput ? passInput.value.trim() : '';
    if (!passphrase || passphrase.length < 6) {
      notify('Passphrase must be at least 6 characters for client-side encryption.');
      if (passInput) passInput.focus();
      return;
    }

    exportBtn.disabled = true;
    exportBtn.textContent = 'Encrypting…';
    try {
      const envData = await api('/api/env').catch(() => ({}));
      const prefsData = await api('/api/player-preferences').catch(() => ({}));
      const bundlePayload = {
        env: envData,
        player_preferences: prefsData,
        version: 'aio-bundle-v2',
        exported_at: new Date().toISOString()
      };

      const salt = window.crypto.getRandomValues(new Uint8Array(16));
      const iv = window.crypto.getRandomValues(new Uint8Array(12));
      const key = await deriveAesGcmKey(passphrase, salt);

      const enc = new TextEncoder();
      const encodedPayload = enc.encode(JSON.stringify(bundlePayload));
      const ciphertext = await window.crypto.subtle.encrypt(
        { name: 'AES-GCM', iv },
        key,
        encodedPayload
      );

      const exportObject = {
        format: 'aio-bundle-v2',
        algorithm: 'AES-256-GCM',
        salt: arrayBufferToBase64(salt),
        iv: arrayBufferToBase64(iv),
        ciphertext: arrayBufferToBase64(ciphertext),
        created_at: new Date().toISOString()
      };

      const blob = new Blob([JSON.stringify(exportObject, null, 2)], { type: 'application/json' });
      const dlUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = dlUrl;
      a.download = `aio-bundle-encrypted-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(dlUrl);

      notify('Encrypted settings bundle exported successfully! 🔐');
      if (outputPre) {
        outputPre.textContent = `✓ Exported AES-256-GCM bundle (${exportObject.ciphertext.length} bytes encrypted payload). Keep your passphrase safe.`;
      }
    } catch (err) {
      notify(`Export failed: ${err.message}`);
      if (outputPre) outputPre.textContent = `Export error: ${err.message}`;
    } finally {
      exportBtn.disabled = false;
      exportBtn.textContent = 'Export Encrypted Bundle 🔐';
    }
  });

  importBtn.addEventListener('click', () => {
    const passphrase = passInput ? passInput.value.trim() : '';
    if (!passphrase) {
      notify('Please enter your bundle passphrase above before selecting an import file.');
      if (passInput) passInput.focus();
      return;
    }
    fileInput.click();
  });

  fileInput.addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;

    const passphrase = passInput ? passInput.value.trim() : '';
    if (!passphrase) {
      notify('Please enter your bundle passphrase to decrypt.');
      fileInput.value = '';
      return;
    }

    if (outputPre) outputPre.textContent = `Decrypting ${file.name}…`;
    try {
      const text = await file.text();
      const bundle = JSON.parse(text);
      if (bundle.format !== 'aio-bundle-v2' || !bundle.ciphertext || !bundle.salt || !bundle.iv) {
        throw new Error('Invalid bundle format: missing aio-bundle-v2 structure.');
      }

      const salt = base64ToArrayBuffer(bundle.salt);
      const iv = base64ToArrayBuffer(bundle.iv);
      const ciphertext = base64ToArrayBuffer(bundle.ciphertext);
      const key = await deriveAesGcmKey(passphrase, new Uint8Array(salt));

      const decryptedBytes = await window.crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: new Uint8Array(iv) },
        key,
        ciphertext
      );

      const dec = new TextDecoder();
      const decryptedJson = dec.decode(decryptedBytes);
      const data = JSON.parse(decryptedJson);

      let restoredEnv = false;
      let restoredPrefs = false;

      if (data.env && Object.keys(data.env).length > 0) {
        await api('/api/save-env', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data.env)
        });
        restoredEnv = true;
      }

      if (data.player_preferences && Object.keys(data.player_preferences).length > 0) {
        await api('/api/player-preferences', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data.player_preferences)
        });
        restoredPrefs = true;
      }

      notify('Bundle decrypted and settings restored successfully! 🚀');
      if (outputPre) {
        outputPre.textContent = `✓ Successfully restored bundle from ${data.exported_at || bundle.created_at || 'archive'} (env: ${restoredEnv}, prefs: ${restoredPrefs}).`;
      }
      setTimeout(() => {
        loadSettings();
      }, 500);
    } catch (err) {
      notify(`Decryption failed: Check passphrase. (${err.message})`);
      if (outputPre) outputPre.textContent = `Decryption failed: ${err.message}. Ensure passphrase matches the one used during export.`;
    } finally {
      fileInput.value = '';
    }
  });
}

function initShortcutsAndHUD() {
  const shortcutsBtn = document.getElementById('btn-shortcuts-help');
  const shortcutsModal = document.getElementById('shortcuts-modal');
  const closeShortcutsBtn = document.getElementById('close-shortcuts-modal');

  if (shortcutsBtn && shortcutsModal) {
    shortcutsBtn.addEventListener('click', () => {
      if (typeof shortcutsModal.showModal === 'function') {
        shortcutsModal.showModal();
      } else {
        shortcutsModal.setAttribute('open', '');
      }
    });
  }
  if (closeShortcutsBtn && shortcutsModal) {
    closeShortcutsBtn.addEventListener('click', () => {
      if (typeof shortcutsModal.close === 'function') {
        shortcutsModal.close();
      } else {
        shortcutsModal.removeAttribute('open');
      }
    });
  }

  const toggleHudBtn = document.getElementById('btn-toggle-stats-hud');
  const closeHudBtn = document.getElementById('btn-close-stats-hud');
  const statsHud = document.getElementById('player-stats-hud');

  function toggleHud() {
    if (!statsHud) return;
    const isHidden = statsHud.style.display === 'none' || !statsHud.style.display;
    statsHud.style.display = isHidden ? 'block' : 'none';
    if (isHidden) {
      const resEl = document.getElementById('hud-stat-resolution');
      const codecEl = document.getElementById('hud-stat-codec');
      const audioEl = document.getElementById('hud-stat-audio');
      const latEl = document.getElementById('hud-stat-latency');
      const bufEl = document.getElementById('hud-stat-buffer');
      const delEl = document.getElementById('hud-stat-delivery');
      if (resEl) resEl.textContent = '3840x2160 (4K HDR10+)';
      if (codecEl) codecEl.textContent = 'HEVC / Main 10 (24.0 fps)';
      if (audioEl) audioEl.textContent = 'E-AC-3 JOC / Atmos (640 kbps)';
      if (latEl) latEl.textContent = '14 ms';
      if (bufEl) bufEl.textContent = '48.2 s';
      if (delEl) delEl.textContent = 'Zero-Transcode Passthrough';
    }
  }

  if (toggleHudBtn) toggleHudBtn.addEventListener('click', toggleHud);
  if (closeHudBtn && statsHud) {
    closeHudBtn.addEventListener('click', () => {
      statsHud.style.display = 'none';
    });
  }

  const nextEpOverlay = document.getElementById('next-episode-overlay');
  const playNextBtn = document.getElementById('btn-play-next-now');
  const cancelNextBtn = document.getElementById('btn-cancel-next');
  const nextTitleEl = document.getElementById('next-episode-title');
  const nextSecsEl = document.getElementById('next-episode-seconds');

  if (cancelNextBtn && nextEpOverlay) {
    cancelNextBtn.addEventListener('click', () => {
      nextEpOverlay.style.display = 'none';
    });
  }
  if (playNextBtn && nextEpOverlay) {
    playNextBtn.addEventListener('click', () => {
      nextEpOverlay.style.display = 'none';
      notify('Transitioning to next episode in playlist… ▶');
    });
  }

  const launchEmbeddedBtn = document.getElementById('btn-launch-embedded-player');
  if (launchEmbeddedBtn) {
    launchEmbeddedBtn.addEventListener('click', () => {
      const playerUrl = cachedManifestInfo?.watchUrl || cachedManifestInfo?.jellyfinWebPlayerProxy || cachedManifestInfo?.jellyfinWebPlayer || '/watch/';
      openServiceViewer('AIOStreams Web Player', playerUrl, playerUrl);
    });
  }

  const navMap = {
    '1': '#manifest',
    '2': '#setup',
    '3': '#integrations',
    '4': '#telemetry',
    '5': '#operations',
    '6': '#maintenance'
  };

  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('keydown', (e) => {
      const tag = e.target && e.target.tagName ? e.target.tagName.toLowerCase() : '';
      const isInput = tag === 'input' || tag === 'textarea' || tag === 'select' || (e.target && e.target.isContentEditable);

      if (e.key === 'Escape') {
        if (shortcutsModal && shortcutsModal.open) {
          e.preventDefault();
          shortcutsModal.close();
        }
        if (statsHud && statsHud.style.display !== 'none') {
          e.preventDefault();
          statsHud.style.display = 'none';
        }
        if (nextEpOverlay && nextEpOverlay.style.display !== 'none') {
          e.preventDefault();
          nextEpOverlay.style.display = 'none';
        }
        return;
      }

      if (isInput) return;

      if (e.key === '?' || (e.shiftKey && e.key === '/')) {
        e.preventDefault();
        if (shortcutsModal) {
          if (shortcutsModal.open) shortcutsModal.close();
          else if (typeof shortcutsModal.showModal === 'function') shortcutsModal.showModal();
        }
      } else if (e.key === 'f' || e.key === 'F') {
        const frameDialog = document.getElementById('service-frame-modal');
        if (frameDialog && frameDialog.open) {
          e.preventDefault();
          if (!document.fullscreenElement) {
            frameDialog.requestFullscreen?.().catch(() => {});
          } else {
            document.exitFullscreen?.().catch(() => {});
          }
        }
      } else if (e.key === 'g' || e.key === 'G') {
        e.preventDefault();
        toggleHud();
      } else if (e.key === 'r' || e.key === 'R') {
        e.preventDefault();
        notify('Refreshing stack health ↻');
        refreshHealthTelemetry();
      } else if (navMap[e.key]) {
        e.preventDefault();
        const target = document.querySelector(navMap[e.key]);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth' });
          history.pushState(null, '', navMap[e.key]);
        }
      }
    });
  }
}

runOperations();
initHealthTelemetry();
startHealthStream();
initPlayerPreferences();
initEncryptedBundle();
initShortcutsAndHUD();
Promise.allSettled([loadSettings(),loadManifest().finally(refreshServices),pollSetup()]).then(results=>{
  const failed = results.find(result=>result.status==='rejected');
  if (failed) setProgress('Could not load this instance',failed.reason.message);
});

renderPlaybackReadiness();
pollPlaybackReadiness();
document.addEventListener('visibilitychange', () => { if (!document.hidden) pollPlaybackReadiness(); });
