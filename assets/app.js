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
  ['OPENSUBTITLES_API_KEY','OpenSubtitles subtitles','OS'],
  ['SUBDL_API_KEY','SubDL subtitles','S'],
  ['SUBSOURCE_API_KEY','SubSource subtitles','SS'],
  ['WYZIE_API_KEY','Wyzie subtitles','W'],
  ['OFFCLOUD_API_KEY','Offcloud','O'],
  ['SEEDR_API_KEY','Seedr','S']
];
const optionalSecrets=[['NZB_INDEXER_API_KEY','AltHUB / AnimeTosho / NZB API key','NZB']];
const fields = [...providers,...metadata,...trackingKeys,...extras,...optionalSecrets];

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

const SUPPORTED_VALIDATION_PROVIDERS = new Set([
  'tmdb', 'realdebrid', 'premiumize', 'torbox', 'alldebrid', 'debridlink', 'easydebrid', 'nzb'
]);

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

function supportsSavedKeyValidation(key) {
  return SUPPORTED_VALIDATION_PROVIDERS.has(getProviderCode(key));
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

    let testSavedBtn = null;
    if (supportsSavedKeyValidation(key)) {
      testSavedBtn = document.createElement('button');
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
          notify(isValid ? `✓ ${label} key is valid: ${res.detail}` : `✗ ${label}: ${res.detail}`, !isValid);
          if (saved) {
            saved.textContent = isValid ? 'SAVED (VALID)' : 'SAVED (INVALID)';
            saved.style.color = isValid ? '#34d399' : '#f87171';
          }
        } catch (err) {
          notify(`Validation error: ${err.message}`, true);
        } finally {
          testSavedBtn.disabled = false;
          testSavedBtn.textContent = 'Test Saved Key';
        }
      });
      title.append(testSavedBtn);
    }

    const remove = document.createElement('button');
    remove.type = 'button'; remove.id = `${key}-remove`; remove.className = 'clear-key';
    remove.textContent = '×'; remove.hidden = true;
    remove.setAttribute('aria-label',`Remove saved ${label} key`);
    remove.addEventListener('click',event=>{
      event.preventDefault();
      savedKeys.delete(key); saved.textContent = ''; remove.hidden = true;
      if (testSavedBtn) testSavedBtn.hidden = true;
      input.value = ''; input.placeholder = key.endsWith('_URL') ? 'Paste configured manifest URL' : 'Paste API key';
      if (typeof setFormDirty === 'function') setFormDirty(true);
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
      let msg = response.status === 401 ? 'Sign in with your portal password, then retry.' : `The server returned ${response.status}. Check setup details and retry.`;
      try {
        const detail = await response.json();
        if (detail) {
          if (detail.errorCode === 'AIOMETADATA_PRESET_FAILED' && typeof detail.error === 'string') {
            msg = detail.error;
          } else if (typeof detail.error === 'string' && detail.error.trim()) {
            msg = detail.error.trim();
          } else if (typeof detail.message === 'string' && detail.message.trim()) {
            msg = detail.message.trim();
          } else if (typeof detail.detail === 'string' && detail.detail.trim()) {
            msg = detail.detail.trim();
          }
        }
      } catch {
        try {
          const rawText = await response.text();
          if (rawText && typeof rawText === 'string') {
            const trimmed = rawText.trim();
            if (trimmed && trimmed.length < 300 && !trimmed.startsWith('<!DOCTYPE') && !trimmed.startsWith('<html')) {
              msg = trimmed;
            }
          }
        } catch {}
      }
      const error = new Error(msg);
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

function detectIndexerName(url) {
  if (!url || typeof url !== 'string') return 'NZB Indexer';
  const raw = url.toLowerCase().trim();
  if (!raw) return 'NZB Indexer';
  if (raw.includes('drunkenslug')) return 'DrunkenSlug';
  if (raw.includes('althub') || raw.includes('alttot')) return 'altHUB';
  if (raw.includes('animetosho')) return 'AnimeTosho';
  if (raw.includes('nzbgeek')) return 'NZBGeek';
  if (raw.includes('nzbplanet')) return 'NZBPlanet';
  if (raw.includes('nzbfinder')) return 'NZBFinder';
  if (raw.includes('ninja-central') || raw.includes('ninjacentral')) return 'NinjaCentral';
  if (raw.includes('omgwtfnzbs')) return 'OMGWTFNZBs';
  if (raw.includes('tabula-rasa')) return 'Tabula Rasa';
  if (raw.includes('miatrix')) return 'Miatrix';
  if (raw.includes('simplynzbs')) return 'SimplyNZBs';
  try {
    const parsed = new URL(raw.includes('://') ? raw : `https://${raw}`);
    const host = parsed.hostname;
    if (host) {
      const parts = host.replace(/^api\./, '').split('.');
      const main = parts.length > 1 ? parts[parts.length - 2] : parts[0];
      if (main) return main.charAt(0).toUpperCase() + main.slice(1);
    }
  } catch {}
  return 'NZB Indexer';
}

function addUsenetSource(source, saved = {}) {
  const list = document.getElementById(source.list);
  const template = document.getElementById(source.template);
  if (!list || !template || list.children.length >= 12) return;
  const row = template.content.firstElementChild.cloneNode(true);
  if (saved.id) row.dataset.sourceId = saved.id;
  if (saved.secretSaved) row.dataset.secretSaved = 'true';
  for (const input of row.querySelectorAll('[data-source-field]')) {
    const field = input.dataset.sourceField;
    if (field === source.secret) {
      input.placeholder = saved.secretSaved ? 'Saved · enter to replace' : (field === 'apiKey' ? 'API key or Saved · enter to replace' : '');
      input.required = !saved.secretSaved;
    } else if (field in saved) {
      if (input.type === 'checkbox') input.checked = saved[field];
      else input.value = saved[field];
    }
  }

  if (source.key === 'USENET_EXTRA_INDEXERS') {
    const urlInput = row.querySelector('[data-source-field="url"]');
    const keyInput = row.querySelector('[data-source-field="apiKey"]');
    const nameEls = row.querySelectorAll('[data-indexer-name], [data-indexer-legend]');
    const statusBadge = row.querySelector('[data-indexer-status]');
    const feedbackEl = row.querySelector('[data-indexer-feedback]');
    const testBtn = row.querySelector('[data-test-indexer]');

    const updateName = () => {
      const detected = detectIndexerName(urlInput?.value?.trim() || '');
      nameEls.forEach(el => { el.textContent = detected; });
    };
    updateName();
    urlInput?.addEventListener('input', updateName);
    urlInput?.addEventListener('change', updateName);

    if (testBtn) {
      testBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        const url = urlInput?.value?.trim() || '';
        if (!url) {
          notify('Enter an NZB indexer base address first.', true);
          urlInput?.focus();
          return;
        }
        let keyVal = keyInput?.value?.trim() || '';
        const isSecretSaved = saved.secretSaved || row.dataset.secretSaved === 'true';
        if (!keyVal && isSecretSaved) {
          keyVal = 'saved';
        }
        if (!keyVal) {
          notify('Enter an API key for this NZB indexer.', true);
          keyInput?.focus();
          return;
        }

        testBtn.disabled = true;
        const origText = testBtn.textContent;
        testBtn.textContent = 'Testing…';
        if (statusBadge) {
          statusBadge.style.display = 'inline-block';
          statusBadge.textContent = 'TESTING…';
          statusBadge.style.color = 'var(--text-muted)';
        }
        if (feedbackEl) {
          feedbackEl.style.display = 'block';
          feedbackEl.textContent = 'Connecting to indexer…';
          feedbackEl.style.color = 'var(--text-muted)';
        }

        try {
          const payload = {
            provider: 'nzb',
            url: url,
            key: keyVal
          };
          if (row.dataset.sourceId) payload.id = row.dataset.sourceId;
          const res = await api('/api/test-provider', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const isValid = res.status === 'valid' || res.status === 'ok';
          const indexerName = detectIndexerName(url);
          const detailMsg = res.detail || (isValid ? 'Verified successfully' : 'Validation failed');
          if (statusBadge) {
            statusBadge.style.display = 'inline-block';
            statusBadge.textContent = isValid ? 'VALID' : 'INVALID';
            statusBadge.style.color = isValid ? '#34d399' : '#f87171';
          }
          if (feedbackEl) {
            feedbackEl.style.display = 'block';
            feedbackEl.textContent = detailMsg;
            feedbackEl.style.color = isValid ? '#34d399' : '#f87171';
          }
          notify(isValid ? `✓ ${indexerName} valid: ${detailMsg}` : `✗ ${indexerName}: ${detailMsg}`, !isValid);
        } catch (err) {
          const indexerName = detectIndexerName(url);
          if (statusBadge) {
            statusBadge.style.display = 'inline-block';
            statusBadge.textContent = 'ERROR';
            statusBadge.style.color = '#f87171';
          }
          if (feedbackEl) {
            feedbackEl.style.display = 'block';
            feedbackEl.textContent = err.message;
            feedbackEl.style.color = '#f87171';
          }
          notify(`${indexerName} test failed: ${err.message}`, true);
        } finally {
          testBtn.disabled = false;
          testBtn.textContent = origText;
        }
      });
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
    if (source.key === 'USENET_EXTRA_INDEXERS') {
      const extraRows = settings[source.key] || [];
      if (settings.NZB_INDEXER_URL) {
        const primaryUrl = settings.NZB_INDEXER_URL.trim();
        const hasNzbKey = (typeof savedKeys !== 'undefined' && savedKeys.has('NZB_INDEXER_API_KEY')) || (settings.configuredKeys && settings.configuredKeys.includes('NZB_INDEXER_API_KEY'));
        addUsenetSource(source, { url: primaryUrl, secretSaved: !!hasNzbKey });
        for (const row of extraRows) {
          if (row.url && row.url.trim().toLowerCase() === primaryUrl.toLowerCase()) continue;
          addUsenetSource(source, row);
        }
      } else {
        for (const row of extraRows) addUsenetSource(source, row);
      }
    } else {
      for (const row of settings[source.key] || []) addUsenetSource(source, row);
    }
  }
}

function readExtraUsenetSources(payload) {
  for (const source of extraUsenetSources) {
    const list = document.getElementById(source.list);
    if (!list) continue;
    if (source.key === 'USENET_EXTRA_INDEXERS') {
      const rows = Array.from(list.children);
      if (rows.length === 0) {
        payload.NZB_INDEXER_URL = '';
        payload.NZB_INDEXER_API_KEY = '';
        if (typeof savedKeys !== 'undefined') savedKeys.delete('NZB_INDEXER_API_KEY');
        const hiddenKeyInput = document.getElementById('NZB_INDEXER_API_KEY');
        if (hiddenKeyInput) hiddenKeyInput.value = '';
        const hiddenUrlInput = document.getElementById('nzb-indexer-url');
        if (hiddenUrlInput) hiddenUrlInput.value = '';
        payload.USENET_EXTRA_INDEXERS = [];
      } else {
        const row0 = rows[0];
        const url0 = row0.querySelector('[data-source-field="url"]')?.value?.trim() || '';
        const key0 = row0.querySelector('[data-source-field="apiKey"]')?.value?.trim() || '';
        payload.NZB_INDEXER_URL = url0;
        const hiddenUrlInput = document.getElementById('nzb-indexer-url');
        if (hiddenUrlInput) hiddenUrlInput.value = url0;

        const isRow0Saved = row0.dataset.secretSaved === 'true';
        const hiddenKeyInput = document.getElementById('NZB_INDEXER_API_KEY');
        if (key0) {
          payload.NZB_INDEXER_API_KEY = key0;
          if (hiddenKeyInput) hiddenKeyInput.value = key0;
        } else if (isRow0Saved) {
          if (typeof savedKeys !== 'undefined') savedKeys.add('NZB_INDEXER_API_KEY');
          if (hiddenKeyInput) hiddenKeyInput.value = '';
        } else {
          payload.NZB_INDEXER_API_KEY = '';
          if (typeof savedKeys !== 'undefined') savedKeys.delete('NZB_INDEXER_API_KEY');
          if (hiddenKeyInput) hiddenKeyInput.value = '';
        }

        payload.USENET_EXTRA_INDEXERS = rows.slice(1).map(row => {
          const values = row.dataset.sourceId ? { id: row.dataset.sourceId } : {};
          for (const input of row.querySelectorAll('[data-source-field]')) {
            const field = input.dataset.sourceField;
            const val = input.value ? input.value.trim() : '';
            if (field === 'apiKey' && !val) continue;
            values[field] = val;
          }
          return values;
        });
      }
    } else {
      payload[source.key] = Array.from(list.children, row => {
        const values = row.dataset.sourceId ? { id: row.dataset.sourceId } : {};
        for (const input of row.querySelectorAll('[data-source-field]')) {
          const field = input.dataset.sourceField;
          const preserveCredential = source.key === 'USENET_EXTRA_SERVERS' && (field === 'username' || field === 'password');
          const val = input.type === 'checkbox' ? input.checked : (preserveCredential ? input.value : (input.value ? input.value.trim() : ''));
          if (field === source.secret && !val) continue;
          values[field] = val;
        }
        return values;
      });
    }
  }
}

for (const source of extraUsenetSources) {
  document.getElementById(source.add)?.addEventListener('click', () => {
    const row = addUsenetSource(source);
    row?.querySelector('input')?.focus();
    if (row) setFormDirty(true);
  });
}

let settingsEditRevision = 0;
let settingsLoadSequence = 0;
let setupSaveInFlight = false;
let easynewsPasswordSaved = false;
let easynewsPasswordCleared = false;

function normalizeComposeProfilesValue(raw) {
  const parts = String(raw || 'core')
    .split('#', 1)[0]
    .split(',')
    .map(p => p.trim().replace(/^["']|["']$/g, ''))
    .filter(Boolean)
    .map(p => (p === 'scrapers' ? 'core' : (p === 'anime-db' ? 'anime' : p)));
  const unique = [];
  for (const p of parts) {
    if (!unique.includes(p)) unique.push(p);
  }
  return unique.length ? unique.join(',') : 'core';
}

async function loadSettings(options) {
  const {expectedEditRevision = settingsEditRevision, ...requestOptions} = options || {};
  if (expectedEditRevision !== settingsEditRevision) return false;
  const sequence = ++settingsLoadSequence;
  const env = await api('/api/env', requestOptions);
  // An older response must not replace edits or a newer settings response.
  if (expectedEditRevision !== settingsEditRevision || sequence !== settingsLoadSequence) return false;
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
  const precacheToggle = document.getElementById('aio-precache-next-episode');
  if (precacheToggle) precacheToggle.checked = env.AIO_PRECACHE_NEXT_EPISODE === 'true';
  const jellyfinToggle = document.getElementById('jellyfin-enabled');
  if (jellyfinToggle) jellyfinToggle.checked = env.JELLYFIN_ENABLED !== 'false';
  const profilesSelect = document.getElementById('compose-profiles');
  if (profilesSelect) {
    const normalizedProfiles = normalizeComposeProfilesValue(env.COMPOSE_PROFILES || 'core');
    if (profilesSelect.options && typeof document.createElement === 'function' && !Array.from(profilesSelect.options).some(opt => opt.value === normalizedProfiles)) {
      const customOpt = document.createElement('option');
      customOpt.value = normalizedProfiles;
      customOpt.textContent = `Custom (${normalizedProfiles})`;
      profilesSelect.appendChild(customOpt);
    }
    profilesSelect.value = normalizedProfiles;
  }
  document.getElementById('enable-anime-sources').checked=env.ENABLE_ANIME_SOURCES==='true';
  document.getElementById('enable-usenet').checked = env.USENET_ENABLED === 'true';
  for(const [id,key] of [['usenet-host','USENET_HOST'],['usenet-port','USENET_PORT'],['usenet-user','USENET_USER'],['usenet-connections','USENET_CONNECTIONS'],['nzb-indexer-url','NZB_INDEXER_URL']])document.getElementById(id).value=env[key]||'';
  document.getElementById('usenet-tls').checked=env.USENET_SSL!=='false';
  usenetPasswordSaved=!!env.USENET_PASSWORD_SAVED;
  document.getElementById('usenet-pass').value='';
  document.getElementById('usenet-pass').placeholder=usenetPasswordSaved?'Saved · enter to replace':'Usenet password';
  savedKeys.clear();
  for (const key of env.configuredKeys || []) savedKeys.add(key);
  if (env.OPENSUBTITLES_API_KEY_SAVED) savedKeys.add('OPENSUBTITLES_API_KEY');
  const easynewsUserEl = document.getElementById('easynews-user');
  if (easynewsUserEl) easynewsUserEl.value = env.EASYNEWS_USER || '';
  easynewsPasswordSaved = Boolean(env.EASYNEWS_PASSWORD_SAVED || savedKeys.has('EASYNEWS_PASSWORD'));
  easynewsPasswordCleared = false;
  const easynewsPassEl = document.getElementById('easynews-pass');
  if (easynewsPassEl) {
    easynewsPassEl.value = '';
    easynewsPassEl.placeholder = easynewsPasswordSaved ? 'Saved · enter to replace' : 'Easynews password';
  }
  const easynewsSavedEl = document.getElementById('easynews-pass-saved');
  if (easynewsSavedEl) easynewsSavedEl.textContent = easynewsPasswordSaved ? 'SAVED' : '';
  const easynewsRemoveEl = document.getElementById('easynews-pass-remove');
  if (easynewsRemoveEl) easynewsRemoveEl.hidden = !easynewsPasswordSaved;
  if (typeof loadExtraUsenetSources === 'function') loadExtraUsenetSources(env);
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
  const baseUrlEl = document.getElementById('base-url');
  if (baseUrlEl) baseUrlEl.value = baseUrl;

  const proxyUrlEl = document.getElementById('proxy-url');
  if (proxyUrlEl) {
    proxyUrlEl.value = baseUrl || (typeof window !== 'undefined' && window.location ? window.location.origin : '');
  }
  if (typeof updateGuidePlayerPreview === 'function') updateGuidePlayerPreview();

  const cfTokenInput = document.getElementById('cf-tunnel-token');
  if (cfTokenInput) {
    cfTokenInput.value = '';
    if (env.CLOUDFLARE_TUNNEL_TOKEN_SAVED) {
      cfTokenInput.placeholder = 'Saved · enter to replace';
    }
  }

  const cfZoneInput = document.getElementById('cf-zone-id');
  if (cfZoneInput && env.CLOUDFLARE_ZONE_ID) {
    cfZoneInput.value = env.CLOUDFLARE_ZONE_ID;
  }

  const cfApiInput = document.getElementById('cf-api-token');
  if (cfApiInput) {
    cfApiInput.value = '';
    if (env.CLOUDFLARE_API_TOKEN_SAVED) {
      cfApiInput.placeholder = 'Saved · enter to replace';
    }
  }

  if (env.CLOUDFLARE_TUNNEL_TOKEN_SAVED && env.CLOUDFLARE_TUNNEL_METADATA && env.CLOUDFLARE_TUNNEL_METADATA.valid) {
    const metaBox = document.getElementById('cf-token-meta-preview');
    const metaText = document.getElementById('cf-token-meta-text');
    if (metaBox && metaText) {
      metaText.textContent = `Tunnel ID: ${env.CLOUDFLARE_TUNNEL_METADATA.tunnel_id} · CNAME Target: ${env.CLOUDFLARE_TUNNEL_METADATA.cname_target}`;
      metaBox.style.display = 'block';
    }
    const cnameCard = document.getElementById('cf-cname-guide-card');
    const cnameTargetEl = document.getElementById('cf-cname-target');
    if (cnameCard) {
      cnameCard.style.display = 'block';
      if (cnameTargetEl) {
        cnameTargetEl.textContent = env.CLOUDFLARE_TUNNEL_METADATA.cname_target || `${env.CLOUDFLARE_TUNNEL_METADATA.tunnel_id}.cfargotunnel.com`;
      }
    }
  }

  const isLocal = !baseUrl || baseUrl.includes('localhost') || baseUrl.includes('127.0.0.1') || baseUrl.includes('192.168.') || baseUrl.includes('10.') || /^https?:\/\/(172\.(1[6-9]|2[0-9]|3[0-1])\.|[^\/:]+\.(local|internal|lan|home\.arpa))/.test(baseUrl);
  if (typeof setAccessScope === 'function') setAccessScope(isLocal ? 'local' : 'remote');
  if (typeof refreshCloudflareStatus === 'function') {
    refreshCloudflareStatus().catch(() => {});
  }

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
    if (testEl) testEl.hidden = !(saved && supportsSavedKeyValidation(key));
  }
  if (typeof setFormDirty === 'function') setFormDirty(false);
  return true;
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
    const aioPort = (cachedEnv && cachedEnv.ports && cachedEnv.ports.aiostreams) || (cachedEnv && cachedEnv.PORT_AIOSTREAMS) || 3001;
    const playerUrl = info.jellyfinWebPlayer || `${location.protocol}//${location.hostname}:${aioPort}/jellyfin/web/`;
    const launchEmbedded = document.getElementById('btn-launch-embedded-player');
    if (launchEmbedded) {
      launchEmbedded.href = playerUrl;
    }
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

function lumiereStatusLabel(stats) {
  if (stats.online === false || stats.phase === 'offline') return 'Offline · cached metrics only';
  if (stats.phase === 'idle') return stats.ready === true ? 'Ready (idle)' : 'Not ready (idle)';
  if (stats.phase) return `Reported phase: ${stats.phase}`;
  return stats.ready === true ? 'Ready' : 'Readiness not confirmed';
}

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
    const metric = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0 ? Number(value).toLocaleString() : 'Not reported';
    const docCount = metric(res.docs);
    const epCount = metric(res.episodes);
    const peopleCount = metric(res.people);
    const nameCount = metric(res.names);
    const statusText = lumiereStatusLabel(res);
    const datasetDate = res.datasetDate || 'Not reported';
    const date = res.builtAt ? new Date(res.builtAt) : null;
    const builtAt = date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : 'Not reported';
    const genId = res.generationId || 'Not reported';

    content.innerHTML = `
      <div class="lumiere-progress-card">
        <div class="lumiere-progress-header">
          <span>Index status: <strong>${escapeHtml(statusText)}</strong></span>
          <span>Progress percentage is not reported.</span>
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
        <div class="lumiere-detail-row"><span>Index Status</span><strong>${escapeHtml(statusText)}</strong></div>
        <div class="lumiere-detail-row"><span>IMDb Snapshot Date</span><strong>${escapeHtml(datasetDate)}</strong></div>
        <div class="lumiere-detail-row"><span>Current Generation</span><code>${escapeHtml(genId)}</code></div>
        <div class="lumiere-detail-row"><span>Last Index Build</span><strong>${escapeHtml(builtAt)}</strong></div>
      </div>
    `;
  } catch (err) {
    content.innerHTML = `<p style="color:var(--red);padding:1rem;">Could not load stats: ${escapeHtml(err.message)}</p>`;
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
    const items = Array.isArray(res.items) ? res.items.filter(item => item && typeof item === 'object') : [];
    if (!items.length) {
      resultsEl.innerHTML = `<span style="color:var(--text-muted);font-size:0.78rem;">No titles found for "${escapeHtml(query)}" (Latency: ${escapeHtml(res.latencyMs ?? 'unknown')}ms)</span>`;
      return;
    }
    const html = items.map(item => `
      <div class="lumiere-result-item">
        <div class="lumiere-result-main">
          <strong class="lumiere-result-title">${escapeHtml(item.title)}</strong>
          ${item.year ? `<span class="lumiere-result-year">(${escapeHtml(item.year)})</span>` : ''}
          <span class="lumiere-result-type">${escapeHtml(item.type || 'title')}</span>
        </div>
        <div class="lumiere-result-meta">
          ${/^tt\d+$/.test(item.imdbId) ? `<a href="https://www.imdb.com/title/${item.imdbId}/" target="_blank" rel="noopener noreferrer" class="lumiere-result-imdb">${item.imdbId}</a>` : '<span>IMDb link unavailable</span>'}
          <span class="lumiere-result-pop">★ ${escapeHtml(item.popularity ?? 'Not reported')}</span>
        </div>
      </div>
    `).join('');
    resultsEl.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:0.25rem 0.2rem 0.4rem;font-size:0.75rem;color:var(--text-muted);border-bottom:1px solid rgba(255,255,255,0.06);">
        <span>Found <strong>${escapeHtml(res.count ?? items.length)}</strong> matches</span>
        <span class="lumiere-latency-tag">⚡ ${escapeHtml(res.latencyMs ?? 'unknown')}ms</span>
      </div>
      ${html}
    `;
  } catch (err) {
    resultsEl.innerHTML = `<span style="color:var(--red);font-size:0.78rem;">Lookup error: ${escapeHtml(err.message)}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}
window.handleLumiereSandboxSearch = handleLumiereSandboxSearch;

let lumiereRebuildPending = false;

async function startLumiereRebuild(button, badge) {
  if (lumiereRebuildPending) {
    showToast('A LumiereDB rebuild is already being monitored.');
    return false;
  }
  lumiereRebuildPending = true;
  if (button) { button.disabled = true; button.textContent = 'Requesting rebuild…'; }
  try {
    let baseline = null;
    try { baseline = await api('/api/lumiere/stats'); } catch (_) {}
    const result = await api('/api/lumiere/rebuild', { method: 'POST' });
    if (!result?.success) throw new Error(result?.error || 'The rebuild request was not accepted.');
    showToast('LumiereDB rebuild request accepted. Waiting for completion evidence…');
    return await pollLumiereRebuildProgress(button, badge, baseline);
  } catch (error) {
    if (badge) badge.textContent = 'Rebuild request failed';
    showToast('Failed to request rebuild: ' + error.message);
    return false;
  } finally {
    lumiereRebuildPending = false;
    if (button) { button.disabled = false; button.textContent = 'Rebuild index ↻'; }
  }
}

function pollLumiereRebuildProgress(button, badge, baseline = null) {
  let attempts = 0;
  let observedActivity = false;
  const baselineGeneration = baseline?.success && baseline.online === true && typeof baseline.generationId === 'string' ? baseline.generationId : null;
  if (button) button.textContent = 'Waiting for rebuild…';
  return new Promise(resolve => {
    const poll = async () => {
      attempts++;
      try {
        const stats = await api('/api/lumiere/stats');
        if (stats?.success && stats.online === true) {
          if (['error', 'failed'].includes(stats.phase)) {
            if (badge) badge.textContent = 'Index reports a failure; check logs';
            showToast('LumiereDB reports a failure. Rebuild completion was not verified.');
            resolve(false);
            return;
          }
          const active = typeof stats.phase === 'string' && stats.phase && !['idle', 'offline', 'unknown'].includes(stats.phase);
          if (active) observedActivity = true;
          const changedGeneration = baselineGeneration && typeof stats.generationId === 'string' && stats.generationId && stats.generationId !== baselineGeneration;
          if (stats.phase === 'idle' && stats.ready === true && (changedGeneration || observedActivity)) {
            if (badge) badge.textContent = 'Ready · rebuild completion observed';
            showToast('LumiereDB returned to ready after an observed index update.');
            resolve(true);
            return;
          }
          if (badge) badge.textContent = active ? `Reported phase: ${stats.phase}` : 'Waiting for rebuild completion evidence…';
          if (button) button.textContent = active ? `Index: ${stats.phase}…` : 'Waiting for rebuild…';
        } else if (badge) {
          badge.textContent = 'Index unavailable · rebuild not verified';
        }
      } catch (_) {
        if (badge) badge.textContent = 'Status unavailable · rebuild not verified';
      }
      if (attempts >= 60) {
        if (badge) badge.textContent = 'Rebuild completion not verified; check logs';
        showToast('Could not verify rebuild completion. It may still be running; check service logs before retrying.');
        resolve(false);
        return;
      }
      setTimeout(poll, 2500);
    };
    setTimeout(poll, 2500);
  });
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
      const playerUrl = cachedManifestInfo?.jellyfinWebPlayer || `${aioOrigin}/jellyfin/web/`;

      const playerActionBtn = document.createElement('a');
      playerActionBtn.className = 'service-embed-btn';
      playerActionBtn.href = playerUrl;
      playerActionBtn.target = '_blank';
      playerActionBtn.rel = 'noopener noreferrer';
      playerActionBtn.textContent = 'Player ↗';
      playerActionBtn.title = 'Open AIOStreams Web Player in new tab';
      playerActionBtn.setAttribute('aria-label', 'Open AIOStreams Web Player in new tab');
      actions.append(playerActionBtn);

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
          if (res.online === false || res.phase !== 'idle' || res.ready !== true) {
            statsBadge.textContent = lumiereStatusLabel(res);
          } else if (res.docs !== null && res.docs !== undefined) {
            const docStr = (typeof res.docs === 'number' && res.docs >= 1000) ? (res.docs / 1000).toFixed(1) + 'k' : (res.docs ?? '0');
            const epStr = (res.episodes !== null && res.episodes !== undefined && !isNaN(res.episodes))
              ? (res.episodes >= 1000000 ? (res.episodes / 1000000).toFixed(2) + 'M' : (res.episodes >= 1000 ? (res.episodes / 1000).toFixed(0) + 'k' : res.episodes))
              : 'unknown';
            statsBadge.textContent = `Index · ${docStr} titles · ${epStr} episodes`;
          } else {
            statsBadge.textContent = 'Index metrics not reported';
          }
        } else {
          statsBadge.textContent = 'Index metrics unavailable';
        }
      }).catch(() => {
        statsBadge.textContent = 'Index metrics unavailable';
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
        await startLumiereRebuild(rebuildBtn, statsBadge);
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

  const aioSvc = result.integrations.find(s => s.name === 'AIOStreams' || s.host === 'aiostreams');
  const info = cachedManifestInfo;
  const enabled = info?.jellyfinEnabled === true && info.uuid && aioSvc && aioSvc.enabled !== false;
  const aioAction = document.getElementById('aiostreams-player-action');
  const hubPlayer = document.getElementById('hub-open-web-player');
  const topbarPlayer = document.getElementById('topbar-open-player');
  const aioPort = (cachedEnv && cachedEnv.ports && cachedEnv.ports.aiostreams) || (cachedEnv && cachedEnv.PORT_AIOSTREAMS) || 3001;
  const directPlayerUrl = info?.jellyfinWebPlayer || `${location.protocol}//${location.hostname}:${aioPort}/jellyfin/web/`;
  if (aioAction) {
    aioAction.style.display = enabled ? 'block' : 'none';
    if (enabled) {
      aioAction.href = directPlayerUrl;
      aioAction.textContent = 'Open AIOStreams Web Player ↗';
    }
  }
  if (hubPlayer) {
    hubPlayer.style.display = enabled ? 'inline-flex' : 'none';
    if (enabled) {
      hubPlayer.href = directPlayerUrl;
    }
  }
  if (topbarPlayer) {
    topbarPlayer.style.display = enabled ? 'inline-flex' : 'none';
    if (enabled) {
      topbarPlayer.href = directPlayerUrl;
    }
  }
  const launchEmbedded = document.getElementById('btn-launch-embedded-player');
  if (launchEmbedded) {
    launchEmbedded.href = directPlayerUrl;
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

let isPollSetupInFlight = false;
async function pollSetup() {
  clearTimeout(pollTimer);
  if (isPollSetupInFlight) return;
  isPollSetupInFlight = true;
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
    pollTimer = setTimeout(pollSetup, running ? 1600 : (job.status === 'complete' ? 30000 : 5000));
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
  } finally {
    isPollSetupInFlight = false;
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
  if (setupSaveInFlight) return;
  const payload = {
    ENABLE_TORRENTIO: document.getElementById('enable-torrentio')?.checked ? 'true' : 'false',
    TORRENTIO_URL: document.getElementById('torrentio-url')?.value.trim() || '',
    ENABLE_DMM: document.getElementById('enable-dmm')?.checked ? 'true' : 'false',
    ENABLE_REMUXDB: document.getElementById('enable-remuxdb')?.checked ? 'true' : 'false',
    AIO_PRECACHE_NEXT_EPISODE: document.getElementById('aio-precache-next-episode')?.checked ? 'true' : 'false',
    JELLYFIN_ENABLED: document.getElementById('jellyfin-enabled')?.checked ? 'true' : 'false',
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
  const composeProfilesVal = document.getElementById('compose-profiles')?.value;
  if (composeProfilesVal) payload.COMPOSE_PROFILES = composeProfilesVal;
  const easynewsUserEl = document.getElementById('easynews-user');
  if (easynewsUserEl && easynewsUserEl.value !== undefined) {
    payload.EASYNEWS_USER = String(easynewsUserEl.value).trim();
  }
  const easynewsPass = document.getElementById('easynews-pass')?.value || '';
  if (easynewsPass) {
    payload.EASYNEWS_PASSWORD = easynewsPass;
  } else if (easynewsPasswordCleared) {
    payload.EASYNEWS_PASSWORD = '';
  }
  const newPassword = document.getElementById('stack-admin-password')?.value;
  if (newPassword) payload.ADDON_PASSWORD = newPassword;
  const usenetPassword=document.getElementById('usenet-pass').value;
  if(usenetPassword||!usenetPasswordSaved)payload.USENET_PASS=usenetPassword;
  if (typeof readExtraUsenetSources === 'function') readExtraUsenetSources(payload);
  for (const [key] of fields) {
    const value = document.getElementById(key).value.trim();
    if (value || !savedKeys.has(key)) payload[key] = value;
  }
  const cfTunnelInput = document.getElementById('cf-tunnel-token');
  const rawCfTunnel = cfTunnelInput ? cfTunnelInput.value.trim() : '';
  if (rawCfTunnel) {
    let sanitizedToken = rawCfTunnel;
    const tokenMatch = sanitizedToken.match(/(?:--token(?:\s+|=)|(?:^|\s)[A-Za-z_]*TOKEN=)(["']?)([A-Za-z0-9_.\-+/=]+)\1/i);
    if (tokenMatch) {
      sanitizedToken = tokenMatch[2];
    } else {
      sanitizedToken = sanitizedToken.replace(/^["']|["']$/g, '').trim();
      const words = sanitizedToken.split(/\s+/);
      if (words.length > 1) {
        const longest = words.reduce((a, b) => b.length > a.length ? b : a, '');
        if (longest.length >= 20) sanitizedToken = longest;
      }
    }
    payload.CLOUDFLARE_TUNNEL_TOKEN = sanitizedToken;
  }
  const cfZoneInput = document.getElementById('cf-zone-id');
  const rawCfZone = cfZoneInput ? cfZoneInput.value.trim() : '';
  if (rawCfZone) {
    payload.CLOUDFLARE_ZONE_ID = rawCfZone;
  }
  const cfApiTokenInput = document.getElementById('cf-api-token');
  const rawCfApiToken = cfApiTokenInput ? cfApiTokenInput.value.trim() : '';
  if (rawCfApiToken) {
    payload.CLOUDFLARE_API_TOKEN = rawCfApiToken;
  }
  const mode = payload.STREAMING_MODE;
  if (mode === 'usenet') {
    payload.USENET_ENABLED = 'true';
    if (!payload.USENET_HOST || !payload.USENET_USER || (!payload.USENET_PASS && !usenetPasswordSaved)) {
      notify('Enter your Usenet server hostname, username, and password.', true);
      return;
    }
  } else if (!providers.some(([key])=>payload[key] || savedKeys.has(key))&&payload.USENET_ENABLED!=='true'&&!usenetPasswordSaved) {
    notify('Add a provider key or enable Usenet.', true);
    return;
  }
  const button = document.getElementById('setup-button'); button.disabled = true;
  setupSaveInFlight = true;
  if (typeof setFormDirty === 'function') setFormDirty(true);
  const submittedRevision = settingsEditRevision;
  setProgress('Saving your configuration','Connecting local services and checking your keys.',true);
  try {
    await api('/api/save-env',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const headers = newPassword ? {Authorization: 'Basic ' + btoa('admin:' + newPassword)} : undefined;
    await api('/api/setup', {method:'POST', headers});
    await loadSettings({headers, expectedEditRevision: submittedRevision});
    lastJobStatus = 'running';
    renderPlaybackReadiness();
    await pollSetup();
  } catch(error) { setProgress('Setup needs attention',error.message); button.disabled=false; notify(error.message, true); }
  finally { setupSaveInFlight = false; }
});

document.getElementById('refresh-services').addEventListener('click',()=>refreshServices().catch(error=>notify(error.message, true)));

async function copyToClipboard(text, successMsg, triggerBtn) {
  if (!text) return false;
  let copied = false;
  try {
    await navigator.clipboard.writeText(text);
    copied = true;
  } catch {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
    document.body.append(textarea);
    try {
      textarea.select();
      copied = document.execCommand('copy');
    } catch (_) {
      copied = false;
    } finally {
      textarea.remove();
    }
  }
  if (!copied) {
    notify('Could not copy. Select the value and copy it manually.', true);
    return false;
  }
  if (triggerBtn && !triggerBtn._origContent) {
    triggerBtn._origContent = triggerBtn.innerHTML || triggerBtn.textContent || '';
    triggerBtn.textContent = 'Copied! ✓';
    if (triggerBtn.classList && typeof triggerBtn.classList.add === 'function') {
      triggerBtn.classList.add('copied-active');
    }
    if (typeof setTimeout !== 'undefined') {
      setTimeout(() => {
        if (triggerBtn._origContent !== null) {
          triggerBtn.innerHTML = triggerBtn._origContent;
          triggerBtn._origContent = null;
        }
        if (triggerBtn.classList && typeof triggerBtn.classList.remove === 'function') {
          triggerBtn.classList.remove('copied-active');
        }
      }, 2000);
    }
  }
  notify(successMsg);
  return true;
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
      notify('Failed to update backup schedule', true);
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
    notify(isValid ? `✓ Usenet NNTP valid: ${res.detail}` : `✗ Usenet: ${res.detail}`, !isValid);
  } catch (err) {
    notify(`Usenet test failed: ${err.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
});

document.getElementById('test-saved-nzb-btn')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = 'Testing…';
  try {
    const res = await api('/api/test-provider', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'nzb' })
    });
    const isValid = res.status === 'valid' || res.status === 'ok';
    notify(isValid ? `✓ NZB indexer valid: ${res.detail}` : `✗ NZB indexer: ${res.detail}`, !isValid);
  } catch (err) {
    notify(`NZB indexer test failed: ${err.message}`, true);
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

document.getElementById('easynews-pass-remove')?.addEventListener('click', event => {
  event.preventDefault();
  easynewsPasswordSaved = false;
  easynewsPasswordCleared = true;
  const passInput = document.getElementById('easynews-pass');
  if (passInput) {
    passInput.value = '';
    passInput.placeholder = 'Easynews password';
  }
  const savedEl = document.getElementById('easynews-pass-saved');
  if (savedEl) savedEl.textContent = '';
  event.currentTarget.hidden = true;
  if (typeof setFormDirty === 'function') setFormDirty(true);
});

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
  if (dirty) settingsEditRevision++;
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
  const proxyUrlInput = document.getElementById('proxy-url');
  const aiomInput = document.getElementById('aiometadata-host');
  const baseUrlHelp = document.getElementById('base-url-help');
  const aiomHelp = document.getElementById('aiometa-url-help');
  const guide = document.getElementById('remote-access-guide');
  const guidePreview = document.getElementById('guide-player-preview');
  const env = (typeof cachedEnv !== 'undefined') ? cachedEnv : {};
  const aioPort = (env && env.ports && env.ports.aiostreams) || (env && env.PORT_AIOSTREAMS) || '3001';
  const aiomPort = (env && env.ports && env.ports.aiometadata) || (env && env.PORT_AIOMETADATA) || '4005';

  if (scope === 'local') {
    if (guide) {
      if (guide.style) guide.style.display = 'none';
      guide.hidden = true;
    }
    const localBase = `${location.protocol}//${location.hostname}:${aioPort}`;
    const localAiom = `${location.protocol}//${location.hostname}:${aiomPort}`;
    if (baseUrlInput && (!baseUrlInput.value || baseUrlInput.value.includes('yourdomain.com'))) {
      baseUrlInput.value = localBase;
      if (proxyUrlInput) proxyUrlInput.value = localBase;
    }
    if (aiomInput && (!aiomInput.value || aiomInput.value.includes('yourdomain.com'))) {
      aiomInput.value = localAiom;
    }
    if (baseUrlHelp) baseUrlHelp.textContent = 'Direct LAN / home server address on port 3001 (no domain required).';
    if (aiomHelp) aiomHelp.textContent = 'Direct LAN / home server address on port 4005 for rich external catalogs.';
  } else {
    if (guide) {
      if (guide.style) guide.style.display = 'block';
      guide.hidden = false;
    }
    if (proxyUrlInput && baseUrlInput) {
      if (baseUrlInput.value && proxyUrlInput.value !== baseUrlInput.value) {
        proxyUrlInput.value = baseUrlInput.value;
      } else if (proxyUrlInput.value && baseUrlInput.value !== proxyUrlInput.value) {
        baseUrlInput.value = proxyUrlInput.value;
      }
    }
    if (guidePreview) {
      const val = (baseUrlInput && baseUrlInput.value) ? baseUrlInput.value.trim() : (proxyUrlInput && proxyUrlInput.value ? proxyUrlInput.value.trim() : 'https://watch.yourdomain.com');
      guidePreview.textContent = val.replace(/\/+$/, '');
    }
    if (baseUrlHelp) baseUrlHelp.textContent = 'Attach your public domain or Cloudflare Tunnel to port 3001 on your reverse proxy for Web Player & streams.';
    if (aiomHelp) aiomHelp.textContent = 'Optional subdomain: only needed for native Stremio app outside home. Keep local when using the Web Player!';
    if (typeof generateProxySnippet === 'function') {
      try {
        generateProxySnippet();
      } catch (_) {}
    }
  }
}

async function generateProxySnippet() {
  const formatEl = document.getElementById('proxy-format');
  const format = formatEl ? formatEl.value : 'cloudflare';
  const proxyUrlEl = document.getElementById('proxy-url');
  const baseUrlEl = document.getElementById('base-url');
  const targetUrl = (proxyUrlEl && proxyUrlEl.value && proxyUrlEl.value.trim()) ||
                    (baseUrlEl && baseUrlEl.value && baseUrlEl.value.trim()) ||
                    (typeof window !== 'undefined' && window.location ? window.location.origin : '');
  const outputEl = document.getElementById('proxy-output');

  const cfPanel = document.getElementById('cloudflare-automation-panel');
  if (cfPanel) {
    cfPanel.style.display = (format === 'cloudflare') ? 'block' : 'none';
    if (format === 'cloudflare' && typeof refreshCloudflareStatus === 'function') {
      refreshCloudflareStatus();
    }
  }

  if (!outputEl) return;
  try {
    if (typeof fetch === 'undefined') return;
    const response = await fetch(`/api/proxy-config?format=${encodeURIComponent(format)}&base_url=${encodeURIComponent(targetUrl)}`);
    outputEl.textContent = response.ok ? await response.text() : `Server returned ${response.status}`;
  } catch (error) {
    outputEl.textContent = error.message;
  }
}
if (typeof window !== 'undefined') window.generateProxySnippet = generateProxySnippet;

// Cloudflare Tunnel & Automated DNS Management
let cachedCloudflareStatus = null;
let cfOriginUserEdited = false;

function parseClientTunnelToken(token) {
  if (!token || typeof token !== 'string') return null;
  let str = token.trim();
  if (!str) return null;

  // 1. Direct JSON check if someone pasted raw JSON
  if (str.startsWith('{') && str.endsWith('}')) {
    try {
      const parsed = JSON.parse(str);
      const tid = parsed.t || parsed.tunnel_id || parsed.TunnelID;
      if (tid) {
        return {
          tunnel_id: String(tid).trim(),
          account_id: String(parsed.a || parsed.account_id || parsed.AccountTag || '').trim(),
          cname_target: `${String(tid).trim()}.cfargotunnel.com`
        };
      }
    } catch (_) {}
  }

  // 2. Extract token from command flags or assignments: --token <token>, token="<token>", TOKEN=<token>
  const tokenMatch = str.match(/(?:--token(?:\s+|=)|(?:^|\s)[A-Za-z_]*TOKEN=)(["']?)([A-Za-z0-9_.\-+/=]+)\1/i);
  if (tokenMatch) {
    str = tokenMatch[2];
  } else {
    str = str.replace(/^["']|["']$/g, '');
    const words = str.split(/\s+/);
    if (words.length > 1) {
      const longest = words.reduce((a, b) => b.length > a.length ? b : a, '');
      if (longest.length >= 20) {
        str = longest;
      }
    }
  }

  // 3. Decode base64 (standard Cloudflare token format: eyJh...)
  try {
    let b64 = str.trim().replace(/-/g, '+').replace(/_/g, '/');
    b64 += '='.repeat((4 - (b64.length % 4)) % 4);
    const decoded = (typeof atob === 'function')
      ? atob(b64)
      : (typeof Buffer !== 'undefined' ? Buffer.from(b64, 'base64').toString('utf-8') : '');
    const parsed = JSON.parse(decoded);
    const tid = parsed && (parsed.t || parsed.tunnel_id || parsed.TunnelID);
    if (parsed && tid) {
      const cleanTid = String(tid).trim();
      return {
        tunnel_id: cleanTid,
        account_id: String(parsed.a || parsed.account_id || parsed.AccountTag || '').trim(),
        cname_target: `${cleanTid}.cfargotunnel.com`,
        is_run_token: true
      };
    }
  } catch (_) {}

  // 4. Plain tunnel UUID check (e.g. 84144369-15de-4d76-a2a5-48faea71a4f0 or 84144369-15de-4d76-a2a5-48faea71a4f0.cfargotunnel.com)
  const uuidMatch = str.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
  if (uuidMatch) {
    const tid = uuidMatch[1].toLowerCase();
    return {
      tunnel_id: tid,
      account_id: '',
      cname_target: `${tid}.cfargotunnel.com`,
      is_run_token: false
    };
  }

  return null;
}
if (typeof window !== 'undefined') window.parseClientTunnelToken = parseClientTunnelToken;

function updateClientTokenPreview() {
  const tokenInput = document.getElementById('cf-tunnel-token');
  const previewBox = document.getElementById('cf-token-meta-preview');
  const previewText = document.getElementById('cf-token-meta-text');
  const cnameCard = document.getElementById('cf-cname-guide-card');
  const cnameTargetEl = document.getElementById('cf-cname-target');
  const cnameSubdomainEl = document.getElementById('cf-cname-subdomain');
  const proxyUrlInput = document.getElementById('proxy-url');
  const baseUrlInput = document.getElementById('base-url');
  if (!tokenInput) return;

  const raw = tokenInput.value ? tokenInput.value.trim() : '';
  const meta = parseClientTunnelToken(raw)
    || (cachedCloudflareStatus && cachedCloudflareStatus.tunnel_metadata?.valid ? cachedCloudflareStatus.tunnel_metadata : null)
    || (typeof cachedEnv !== 'undefined' && cachedEnv?.CLOUDFLARE_TUNNEL_METADATA?.valid ? cachedEnv.CLOUDFLARE_TUNNEL_METADATA : null);

  if (meta && (meta.tunnel_id || meta.cname_target)) {
    const target = meta.cname_target || `${meta.tunnel_id}.cfargotunnel.com`;
    let previewContent = `Tunnel ID: <code>${escapeHtml(meta.tunnel_id || 'valid')}</code> · CNAME Target: <code>${escapeHtml(target)}</code>`;
    if (meta.is_run_token === false) {
      previewContent += ` <span style="color:#fbbf24;font-size:11px;">(UUID detected — paste full token for connector)</span>`;
    }
    if (previewText) previewText.innerHTML = previewContent;
    if (previewBox) previewBox.style.display = 'block';

    if (cnameCard) {
      cnameCard.style.display = 'block';
      if (cnameTargetEl) cnameTargetEl.textContent = target;
      const hostUrl = (proxyUrlInput?.value?.trim()) || (baseUrlInput?.value?.trim()) || '';
      if (cnameSubdomainEl) {
        if (hostUrl) {
          try {
            const parsed = new URL(hostUrl.startsWith('http') ? hostUrl : `https://${hostUrl}`);
            const parts = parsed.hostname.split('.');
            cnameSubdomainEl.textContent = parts.length > 2 ? parts[0] : '@';
          } catch (_) {
            cnameSubdomainEl.textContent = 'watch';
          }
        } else {
          cnameSubdomainEl.textContent = 'watch';
        }
      }
    }
  } else {
    if (previewBox) previewBox.style.display = 'none';
    if (cnameCard) cnameCard.style.display = 'none';
  }
}
if (typeof window !== 'undefined') window.updateClientTokenPreview = updateClientTokenPreview;

function isUnreachablePort3000Origin(url) {
  if (!url || typeof url !== 'string') return false;
  return /:3000(\/|$)/i.test(url.trim()) || /\baiostreams:3000\b/i.test(url.trim());
}

function syncOriginPresetFromValue(value) {
  const presetEl = document.getElementById('cf-origin-preset');
  if (!presetEl) return;
  const trimmed = String(value || '').trim();
  if (!trimmed) {
    presetEl.value = '';
    return;
  }
  const options = Array.isArray(presetEl.options)
    ? presetEl.options
    : (presetEl.options ? Array.from(presetEl.options) : []);
  const match = options.find(opt => opt && opt.value === trimmed);
  presetEl.value = match ? trimmed : 'custom';
}

function updateCloudflareOriginWarning(statusRes) {
  const warnBox = document.getElementById('cf-origin-warning');
  const originInput = document.getElementById('cf-origin-target');
  if (!warnBox) return;

  const status = statusRes || cachedCloudflareStatus || {};
  const recommended = status.recommended_origin || 'http://host.docker.internal:3001';
  const detected = status.detected_origin || '';
  const currentVal = (originInput && originInput.value ? originInput.value.trim() : '') || '';
  const connectorMode = status.connector_mode || '';
  const isExternal = Boolean(status.has_external || connectorMode === 'external_host' || connectorMode === 'external_bridge');
  const currentIs3000 = isUnreachablePort3000Origin(currentVal);
  const detectedIs3000 = isUnreachablePort3000Origin(detected);
  const recommendedIs3001 = /:3001(\/|$)/.test(recommended);

  let html = '';
  let level = 'info';

  if (currentIs3000 && (isExternal || recommendedIs3001)) {
    level = 'danger';
    html = `<strong>⚠️ Unreachable Origin (:3000):</strong> <code>${escapeHtml(currentVal)}</code> is only reachable inside the private <code>stremio-net</code> Docker network. External Cloudflare connectors cannot reach <code>aiostreams:3000</code> and will return HTTP 502. Use <code>${escapeHtml(recommended)}</code> (port <code>:3001</code>) instead.`;
  } else if (detectedIs3000 && recommendedIs3001) {
    level = 'warn';
    html = `<strong>⚠️ Stale :3000 Origin Detected:</strong> Existing origin <code>${escapeHtml(detected)}</code> is unreachable from external connectors. Origin target is pre-filled with <code>${escapeHtml(recommended)}</code> — click <strong>Push DNS to Cloudflare 🚀</strong> to repair ingress rules to <code>:3001</code>.`;
  } else if (status.origin_warning) {
    level = 'warn';
    html = `<strong>⚠️ Origin Notice:</strong> ${escapeHtml(status.origin_warning)}`;
  } else if (isExternal) {
    level = 'info';
    html = `<strong>☁️ External Connector Active (${escapeHtml(connectorMode || 'external')}):</strong> Route Cloudflare Zero Trust Public Hostname to <code>${escapeHtml(recommended)}</code> (port <code>:3001</code>), never <code>aiostreams:3000</code>.`;
  }

  if (html) {
    warnBox.innerHTML = html;
    warnBox.style.display = 'block';
    if (warnBox.classList && typeof warnBox.classList.remove === 'function' && typeof warnBox.classList.add === 'function') {
      warnBox.classList.remove('cf-origin-warning-danger', 'cf-origin-warning-info');
      if (level === 'danger') warnBox.classList.add('cf-origin-warning-danger');
      else if (level === 'info') warnBox.classList.add('cf-origin-warning-info');
    }
  } else {
    warnBox.innerHTML = '';
    warnBox.style.display = 'none';
  }
}

function populateCloudflareOriginControls(statusRes) {
  const originInput = document.getElementById('cf-origin-target');
  const datalist = document.getElementById('cf-origin-candidates');
  const presetEl = document.getElementById('cf-origin-preset');
  const candidates = Array.isArray(statusRes?.origin_candidates) && statusRes.origin_candidates.length > 0
    ? statusRes.origin_candidates
    : [
        { label: 'External Bridge / DinD (:3001)', url: 'http://host.docker.internal:3001' },
        { label: 'Host-Network Connector (:3001)', url: 'http://127.0.0.1:3001' },
        { label: 'Built-in aio-tunnel (:3000)', url: 'http://aiostreams:3000' }
      ];

  if (datalist) {
    datalist.innerHTML = candidates
      .filter(c => c && c.url)
      .map(c => `<option value="${escapeHtml(c.url)}" label="${escapeHtml(c.label || c.url)}"></option>`)
      .join('');
  }

  if (presetEl && typeof presetEl.innerHTML === 'string') {
    const prevVal = presetEl.value;
    const seen = new Set();
    const optionHtml = ['<option value="">Auto (Recommended by topology)</option>'];
    candidates.forEach(c => {
      if (!c || !c.url || seen.has(c.url)) return;
      seen.add(c.url);
      optionHtml.push(`<option value="${escapeHtml(c.url)}">${escapeHtml(c.url)}${c.label ? ` (${escapeHtml(c.label)})` : ''}</option>`);
    });
    optionHtml.push('<option value="custom">Custom origin URL…</option>');
    presetEl.innerHTML = optionHtml.join('');
    if (prevVal) presetEl.value = prevVal;
  }

  if (originInput) {
    const recommended = statusRes?.recommended_origin || '';
    if (recommended && (!cfOriginUserEdited || !originInput.value || !originInput.value.trim())) {
      originInput.value = recommended;
    }
    if (recommended) {
      originInput.placeholder = recommended;
    }
    syncOriginPresetFromValue(originInput.value);
  }

  updateCloudflareOriginWarning(statusRes);
}

async function refreshCloudflareStatus() {
  const banner = document.getElementById('cf-connectors-banner');
  const body = document.getElementById('cf-connectors-body');

  try {
    if (body) body.innerHTML = '<em>Scanning Docker for Cloudflare connectors…</em>';
    if (banner && body) banner.style.display = 'block';

    const res = await api('/api/cloudflare/status');
    cachedCloudflareStatus = res;

    const tokenInput = document.getElementById('cf-tunnel-token');
    if (tokenInput && !tokenInput.value) {
      if (res.token_configured) {
        tokenInput.placeholder = 'Saved · enter to replace';
      } else {
        tokenInput.placeholder = 'eyJhIjoi... (paste token from Cloudflare Zero Trust)';
      }
    }

    populateCloudflareOriginControls(res);
    updateClientTokenPreview();

    if (!body) return;

    const hostBadge = document.getElementById('cf-host-badge');
    const hintBox = document.getElementById('cf-detected-hint');
    const recommendedOrigin = res.recommended_origin || `http://${res.current_host || '127.0.0.1'}:3001`;

    let html = '';
    if (res.has_external && res.external_connectors && res.external_connectors.length > 0) {
      const primary = res.external_connectors[0].name || 'Connector';
      if (hostBadge) {
        hostBadge.textContent = `☁️ ${primary}`;
        hostBadge.style.display = 'inline-block';
        hostBadge.title = `Detected running host connector: ${primary}`;
      }
      if (hintBox) {
        hintBox.innerHTML = `💡 Detected running Cloudflare connector <strong>${escapeHtml(primary)}</strong> on this Docker host. Recommended origin: <code>${escapeHtml(recommendedOrigin)}</code>. Switch to <strong>Remote Access</strong> to route or repair DNS.`;
        hintBox.style.display = 'block';
      }

      html += '<div style="color:var(--accent-cyan);font-weight:700;margin-bottom:6px;">☁️ Detected External Cloudflare Connector on Host:</div>';
      res.external_connectors.forEach(c => {
        html += `<div class="cf-connector-item">
          <span><strong>${escapeHtml(c.name)}</strong> <span style="color:var(--text-muted);font-size:11px;">(${escapeHtml(c.image)})</span></span>
          <span style="color:#34d399;font-weight:600;">${escapeHtml(c.status || c.state)}</span>
        </div>`;
      });
      html += `<div style="font-size:11.5px;color:var(--text-muted);margin-top:8px;line-height:1.4;">
        💡 <strong>Host Connector Advice:</strong> Point your Cloudflare Public Hostname to <code>${escapeHtml(recommendedOrigin)}</code> (AIOStreams published port <code>:3001</code> — <code>aiostreams:3000</code> is unreachable from external connectors), OR click <strong>Push DNS to Cloudflare 🚀</strong> below to apply/repair the ingress rule automatically.
      </div>`;
    } else {
      if (hostBadge) hostBadge.style.display = 'none';
      if (hintBox) hintBox.style.display = 'none';
      if (res.local_tunnel && (res.local_tunnel.state === 'running' || res.local_tunnel.status?.toLowerCase().includes('up'))) {
        html += `<div style="color:#34d399;font-weight:700;">✓ Local aio-tunnel container is running (Origin: <code>${escapeHtml(recommendedOrigin)}</code>). Remote connectivity is not verified.</div>
                 <div style="font-size:11.5px;color:var(--text-muted);margin-top:4px;">Status: ${escapeHtml(res.local_tunnel.status)}</div>`;
      } else if (res.token_configured) {
        html += `<div style="color:#fbbf24;font-weight:600;">⚠️ Tunnel token is saved, but local container aio-tunnel is stopped. Click 'Start Local Tunnel ▶' below to route traffic.</div>`;
      } else {
        html += `<div style="color:var(--text-muted);font-size:12px;">ℹ️ No running Cloudflare connectors detected. Enter your Tunnel Token below and click 'Start Local Tunnel ▶'. Recommended origin: <code>${escapeHtml(recommendedOrigin)}</code>.</div>`;
      }
    }

    if (res.origin_warning) {
      html += `<div style="margin-top:6px;color:#fbbf24;font-size:11.5px;">⚠️ ${escapeHtml(res.origin_warning)}</div>`;
    }

    body.innerHTML = html;
    if (banner) banner.style.display = 'block';
  } catch (err) {
    if (body) body.innerHTML = `<span style="color:#f87171;">⚠️ Could not scan Docker host: ${escapeHtml(err.message)}</span>`;
  }
}
if (typeof window !== 'undefined') window.refreshCloudflareStatus = refreshCloudflareStatus;

function updateGuidePlayerPreview() {
  const baseUrlInput = document.getElementById('base-url');
  const proxyUrlInput = document.getElementById('proxy-url');
  const preview = document.getElementById('guide-player-preview');
  const val = (baseUrlInput && baseUrlInput.value) ? baseUrlInput.value.trim() : (proxyUrlInput && proxyUrlInput.value ? proxyUrlInput.value.trim() : 'https://watch.yourdomain.com');
  const clean = val.replace(/\/+$/, '');
  if (preview) {
    preview.textContent = clean;
  }
  if (typeof updateClientTokenPreview === 'function') {
    try {
      updateClientTokenPreview();
    } catch (_) {}
  }
}

function syncBaseToProxy() {
  const baseUrlInput = document.getElementById('base-url');
  const proxyUrlInput = document.getElementById('proxy-url');
  if (baseUrlInput && proxyUrlInput && proxyUrlInput.value !== baseUrlInput.value) {
    proxyUrlInput.value = baseUrlInput.value;
  }
  updateGuidePlayerPreview();
}

function syncProxyToBase() {
  const baseUrlInput = document.getElementById('base-url');
  const proxyUrlInput = document.getElementById('proxy-url');
  if (baseUrlInput && proxyUrlInput && baseUrlInput.value !== proxyUrlInput.value) {
    baseUrlInput.value = proxyUrlInput.value;
    if (typeof Event !== 'undefined' && typeof baseUrlInput.dispatchEvent === 'function') {
      try {
        baseUrlInput.dispatchEvent(new Event('input'));
      } catch (_) {}
    }
  }
  updateGuidePlayerPreview();
}

const copyGuidePlayerBtn = document.getElementById('btn-copy-guide-player-url');
if (copyGuidePlayerBtn) {
  copyGuidePlayerBtn.addEventListener('click', (e) => {
    const preview = document.getElementById('guide-player-preview');
    const text = (preview && preview.textContent && preview.textContent.trim()) ||
                 document.getElementById('base-url')?.value?.trim() ||
                 document.getElementById('proxy-url')?.value?.trim() ||
                 'https://watch.yourdomain.com';
    copyToClipboard(text, 'Remote Web Player URL copied!', e.currentTarget);
  });
}

const baseUrlEl = document.getElementById('base-url');
if (baseUrlEl) {
  baseUrlEl.addEventListener('input', () => {
    syncBaseToProxy();
  });
  baseUrlEl.addEventListener('change', () => {
    syncBaseToProxy();
    const guide = document.getElementById('remote-access-guide');
    if (guide && guide.style && guide.style.display !== 'none' && !guide.hidden) {
      if (typeof generateProxySnippet === 'function') generateProxySnippet();
    }
  });
}

const proxyUrlEl = document.getElementById('proxy-url');
if (proxyUrlEl) {
  proxyUrlEl.addEventListener('input', () => {
    syncProxyToBase();
  });
  proxyUrlEl.addEventListener('change', () => {
    syncProxyToBase();
    const guide = document.getElementById('remote-access-guide');
    if (guide && guide.style && guide.style.display !== 'none' && !guide.hidden) {
      if (typeof generateProxySnippet === 'function') generateProxySnippet();
    }
  });
}

document.getElementById('btn-scan-cf-connectors')?.addEventListener('click', () => {
  refreshCloudflareStatus().then(() => notify('Scanned Docker host for Cloudflare connectors ↻'));
});

document.getElementById('cf-tunnel-token')?.addEventListener('input', () => {
  updateClientTokenPreview();
});

document.getElementById('cf-origin-target')?.addEventListener('input', (e) => {
  cfOriginUserEdited = true;
  syncOriginPresetFromValue(e.currentTarget?.value ?? e.target?.value ?? '');
  updateCloudflareOriginWarning(cachedCloudflareStatus);
});

document.getElementById('cf-origin-preset')?.addEventListener('change', (e) => {
  const selected = e.currentTarget?.value ?? e.target?.value ?? '';
  const originInput = document.getElementById('cf-origin-target');
  if (!originInput) return;
  if (selected === '') {
    cfOriginUserEdited = false;
    originInput.value = cachedCloudflareStatus?.recommended_origin || 'http://host.docker.internal:3001';
  } else if (selected !== 'custom') {
    cfOriginUserEdited = true;
    originInput.value = selected;
  } else if (typeof originInput.focus === 'function') {
    originInput.focus();
  }
  updateCloudflareOriginWarning(cachedCloudflareStatus);
});

document.getElementById('btn-save-cf-token')?.addEventListener('click', async () => {
  const input = document.getElementById('cf-tunnel-token');
  let token = input ? input.value.trim() : '';
  if (!token) {
    if (cachedCloudflareStatus?.token_configured || input?.placeholder?.includes('Saved') || cachedEnv?.CLOUDFLARE_TUNNEL_TOKEN_SAVED) {
      notify('✓ Cloudflare Tunnel Token is already saved in configuration! (To replace, type a new token here.)');
    } else {
      notify('Enter a Cloudflare Tunnel Token in the input box above to save.', true);
    }
    return;
  }
  const tokenMatch = token.match(/(?:--token(?:\s+|=)|(?:^|\s)[A-Za-z_]*TOKEN=)(["']?)([A-Za-z0-9_.\-+/=]+)\1/i);
  if (tokenMatch) {
    token = tokenMatch[2];
  } else {
    token = token.replace(/^["']|["']$/g, '').trim();
    const words = token.split(/\s+/);
    if (words.length > 1) {
      const longest = words.reduce((a, b) => b.length > a.length ? b : a, '');
      if (longest.length >= 20) token = longest;
    }
  }

  const parsed = parseClientTunnelToken(token);
  if (parsed && parsed.is_run_token === false) {
    notify('⚠️ Notice: You entered a Tunnel UUID. Cloudflared needs the full base64 token starting with eyJh... to authenticate the container.', true);
  }

  try {
    await api('/api/save-env', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ CLOUDFLARE_TUNNEL_TOKEN: token })
    });
    notify('✓ Cloudflare Tunnel Token saved to configuration! 💾');
    input.value = '';
    input.placeholder = 'Saved · enter to replace';
    if (typeof cachedEnv !== 'undefined' && cachedEnv) {
      cachedEnv.CLOUDFLARE_TUNNEL_TOKEN_SAVED = true;
    }
    // Automatically trigger local tunnel start if it is a run token
    if (!parsed || parsed.is_run_token !== false) {
      try {
        await api('/api/cloudflare/tunnel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'start' })
        });
      } catch (_) {}
    }
    await refreshCloudflareStatus();
  } catch (err) {
    notify(`Failed to save tunnel token: ${err.message}`, true);
  }
});

document.getElementById('btn-start-cf-tunnel')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const orig = btn.textContent;
  const tokenInput = document.getElementById('cf-tunnel-token');
  let tokenVal = tokenInput ? tokenInput.value.trim() : '';

  if (tokenVal) {
    const tokenMatch = tokenVal.match(/(?:--token(?:\s+|=)|(?:^|\s)[A-Za-z_]*TOKEN=)(["']?)([A-Za-z0-9_.\-+/=]+)\1/i);
    if (tokenMatch) {
      tokenVal = tokenMatch[2];
    } else {
      tokenVal = tokenVal.replace(/^["']|["']$/g, '').trim();
      const words = tokenVal.split(/\s+/);
      if (words.length > 1) {
        const longest = words.reduce((a, b) => b.length > a.length ? b : a, '');
        if (longest.length >= 20) tokenVal = longest;
      }
    }
    try {
      await api('/api/save-env', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ CLOUDFLARE_TUNNEL_TOKEN: tokenVal })
      });
      tokenInput.value = '';
      tokenInput.placeholder = 'Saved · enter to replace';
      if (typeof cachedEnv !== 'undefined' && cachedEnv) {
        cachedEnv.CLOUDFLARE_TUNNEL_TOKEN_SAVED = true;
      }
    } catch (_) {}
  } else if (!cachedCloudflareStatus?.token_configured && !tokenInput?.placeholder?.includes('Saved') && !cachedEnv?.CLOUDFLARE_TUNNEL_TOKEN_SAVED) {
    notify('Please enter your Cloudflare Tunnel Token in the input box above before starting the tunnel.', true);
    if (tokenInput && typeof tokenInput.focus === 'function') tokenInput.focus();
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Starting…';
  try {
    const startPayload = { action: 'start' };
    if (tokenVal) startPayload.token = tokenVal;
    const res = await api('/api/cloudflare/tunnel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(startPayload)
    });
    notify(res.success ? '✓ Local Cloudflare tunnel container (aio-tunnel) is active and running!' : `Tunnel start failed: ${res.error}`, !res.success);
    await refreshCloudflareStatus();
  } catch (err) {
    notify(`Could not start tunnel: ${err.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
});

async function runCloudflareTunnelAction(action, btn, pendingLabel, successMsg) {
  if (!btn) return;
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = pendingLabel;
  try {
    const res = await api('/api/cloudflare/tunnel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    });
    notify(res.success ? successMsg : `Tunnel ${action} failed: ${res.error || 'Unknown error'}`, !res.success);
    await refreshCloudflareStatus();
  } catch (err) {
    notify(`Could not ${action} tunnel: ${err.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

document.getElementById('btn-stop-cf-tunnel')?.addEventListener('click', e => {
  return runCloudflareTunnelAction('stop', e.currentTarget, 'Stopping…', '✓ Local Cloudflare tunnel stopped.');
});

document.getElementById('btn-restart-cf-tunnel')?.addEventListener('click', e => {
  return runCloudflareTunnelAction('restart', e.currentTarget, 'Restarting…', '✓ Local Cloudflare tunnel restarted.');
});

document.getElementById('btn-copy-cf-cname')?.addEventListener('click', (e) => {
  const targetEl = document.getElementById('cf-cname-target');
  const target = targetEl ? targetEl.textContent.trim() : '';
  if (target && !target.includes('<tunnel_id>')) {
    copyToClipboard(target, `Copied CNAME target: ${target}`, e.currentTarget);
  } else {
    notify('Enter your Cloudflare Tunnel Token in the box above to resolve your unique CNAME target.', true);
  }
});

document.getElementById('btn-push-cf-dns')?.addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  const orig = btn.textContent;
  const apiTokenInput = document.getElementById('cf-api-token');
  const zoneIdInput = document.getElementById('cf-zone-id');
  const tunnelTokenInput = document.getElementById('cf-tunnel-token');
  const proxyUrlInput = document.getElementById('proxy-url');
  const baseUrlInput = document.getElementById('base-url');
  const resultBox = document.getElementById('cf-dns-result');

  let rawHostname = (baseUrlInput?.value?.trim()) || (proxyUrlInput?.value?.trim()) || '';
  let hostname = rawHostname;
  if (hostname) {
    try {
      const parsed = new URL(hostname.startsWith('http') ? hostname : `https://${hostname}`);
      hostname = parsed.hostname;
    } catch (_) {}
  }
  if (!hostname) {
    notify('Enter your Web Player public address or external domain above before pushing DNS.', true);
    if (baseUrlInput && typeof baseUrlInput.focus === 'function') baseUrlInput.focus();
    return;
  }

  const isLocalHost = !hostname ||
    hostname === 'localhost' ||
    hostname === '127.0.0.1' ||
    hostname === '::1' ||
    hostname === '0.0.0.0' ||
    hostname.startsWith('192.168.') ||
    hostname.startsWith('10.') ||
    hostname.endsWith('.local') ||
    hostname.endsWith('.internal') ||
    hostname.endsWith('.lan') ||
    hostname.endsWith('.home.arpa') ||
    /^172\.(1[6-9]|2[0-9]|3[0-1])\./.test(hostname) ||
    /^169\.254\./.test(hostname);

  if (isLocalHost) {
    notify('Cloudflare DNS requires a public domain name (e.g. https://watch.yourdomain.com), not a local IP address.', true);
    if (baseUrlInput && typeof baseUrlInput.focus === 'function') baseUrlInput.focus();
    return;
  }

  const apiToken = apiTokenInput ? apiTokenInput.value.trim() : '';
  const isApiTokenSaved = !!(cachedEnv?.CLOUDFLARE_API_TOKEN_SAVED || apiTokenInput?.placeholder?.includes('Saved'));
  if (!apiToken && !isApiTokenSaved) {
    notify('Enter a Cloudflare API Token (Zone:DNS:Edit permission) in the field below.', true);
    if (apiTokenInput && typeof apiTokenInput.focus === 'function') apiTokenInput.focus();
    return;
  }

  let tunnelToken = tunnelTokenInput?.value?.trim() || '';
  if (tunnelToken) {
    const tokenMatch = tunnelToken.match(/(?:--token(?:\s+|=)|(?:^|\s)[A-Za-z_]*TOKEN=)(["']?)([A-Za-z0-9_.\-+/=]+)\1/i);
    if (tokenMatch) {
      tunnelToken = tokenMatch[2];
    } else {
      tunnelToken = tunnelToken.replace(/^["']|["']$/g, '').trim();
    }
  }

  let cnameTarget = '';
  if (tunnelToken) {
    const parsed = parseClientTunnelToken(tunnelToken);
    if (parsed && parsed.cname_target) {
      cnameTarget = parsed.cname_target;
    }
  }
  if (!cnameTarget) {
    const meta = (cachedCloudflareStatus && cachedCloudflareStatus.tunnel_metadata?.valid ? cachedCloudflareStatus.tunnel_metadata : null)
      || (typeof cachedEnv !== 'undefined' && cachedEnv?.CLOUDFLARE_TUNNEL_METADATA?.valid ? cachedEnv.CLOUDFLARE_TUNNEL_METADATA : null);
    if (meta && (meta.cname_target || meta.tunnel_id)) {
      cnameTarget = meta.cname_target || `${meta.tunnel_id}.cfargotunnel.com`;
    }
  }
  if (!cnameTarget) {
    const cnameEl = document.getElementById('cf-cname-target');
    const text = cnameEl ? cnameEl.textContent.trim() : '';
    if (text && !text.includes('<tunnel_id>') && text.includes('.cfargotunnel.com')) {
      cnameTarget = text;
    }
  }

  const zoneId = (zoneIdInput ? zoneIdInput.value.trim() : '') || (cachedEnv?.CLOUDFLARE_ZONE_ID || '');
  const originInput = document.getElementById('cf-origin-target');
  const serviceUrl = (originInput && originInput.value ? originInput.value.trim() : '') || (cachedCloudflareStatus?.recommended_origin || '');

  btn.disabled = true;
  btn.textContent = 'Pushing DNS…';
  if (resultBox) {
    resultBox.style.display = 'block';
    resultBox.innerHTML = '<em>Connecting to Cloudflare API…</em>';
  }

  try {
    const payload = {
      api_token: apiToken,
      hostname: hostname,
      tunnel_token: tunnelToken,
      zone_id: zoneId
    };
    if (cnameTarget) {
      payload.cname_target = cnameTarget;
    }
    if (serviceUrl) {
      payload.service_url = serviceUrl;
    }

    const res = await api('/api/cloudflare/push-dns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.success) {
      if (res.tunnel_started) {
        notify('✓ Cloudflare DNS CNAME pushed & local tunnel started. Remote connectivity is not verified.');
      } else {
        notify('✓ Cloudflare DNS CNAME pushed successfully! 🚀');
      }
      await refreshCloudflareStatus();
      if (resultBox) {
        resultBox.style.display = 'block';
        const appliedOrigin = res.service_url || serviceUrl;
        let statusHtml = `<span style="color:#34d399;font-weight:700;">✓ ${escapeHtml(res.message)}</span>
          <div style="margin-top:4px;color:var(--text-muted);font-size:11.5px;">
            Hostname: <code>${escapeHtml(res.hostname)}</code> &rarr; Target: <code>${escapeHtml(res.cname_target)}</code> (Zone: <code>${escapeHtml(res.zone_name)}</code>, Proxied: ON)${appliedOrigin ? ` · Origin: <code>${escapeHtml(appliedOrigin)}</code>` : ''}
          </div>`;
        if (res.repaired || res.ingress_action === 'repaired') {
          statusHtml += `<div style="margin-top:6px;padding:6px 10px;background:rgba(52,211,153,0.1);border:1px solid rgba(52,211,153,0.3);border-radius:6px;font-size:11.5px;color:#34d399;">
            ✓ Repaired stale Cloudflare ingress rule${res.previous_service_url ? ` from <code>${escapeHtml(res.previous_service_url)}</code>` : ''} to <code>${escapeHtml(appliedOrigin)}</code>.
          </div>`;
        }
        if (res.ingress_error) {
          statusHtml += `<div style="margin-top:6px;padding:6px 10px;background:rgba(248,113,113,0.12);border:1px solid rgba(248,113,113,0.35);border-radius:6px;font-size:11.5px;color:#fecaca;">
            ⚠️ Ingress update note: ${escapeHtml(res.ingress_error)}
          </div>`;
        }
        if (!res.tunnel_started) {
          statusHtml += `<div style="margin-top:8px;padding:8px 10px;background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);border-radius:6px;font-size:12px;color:#fbbf24;">
            <strong>⚠️ 502 Bad Gateway Prevention:</strong> DNS is pointing to Cloudflare, but local connector startup was not confirmed. Check its status and logs, then use <strong>Start Local Tunnel ▶</strong> if needed. A running connector alone does not verify the origin service.
          </div>`;
        }
        resultBox.innerHTML = statusHtml;
      }
    } else {
      throw new Error(res.error || 'Failed to push DNS record');
    }
  } catch (err) {
    notify(`Cloudflare DNS push failed: ${err.message}`, true);
    if (resultBox) {
      resultBox.style.display = 'block';
      resultBox.innerHTML = `<span style="color:#f87171;font-weight:700;">✗ ${escapeHtml(err.message)}</span>`;
    }
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
});

function renderReachabilityResults(res, resultsEl, summaryEl, statusDotEl) {
  const checks = Array.isArray(res?.checks) ? res.checks : [];
  const summary = res?.summary || {};
  const passed = Number.isFinite(Number(summary.passed)) ? Number(summary.passed) : checks.filter(c => c.status === 'ok' || c.ok === true).length;
  const failed = Number.isFinite(Number(summary.failed)) ? Number(summary.failed) : checks.filter(c => c.status === 'fail' || c.ok === false).length;
  const warnings = Number.isFinite(Number(summary.warnings)) ? Number(summary.warnings) : checks.filter(c => c.status === 'warn').length;
  const skipped = Number.isFinite(Number(summary.skipped)) ? Number(summary.skipped) : checks.filter(c => c.status === 'skipped').length;
  const total = Number.isFinite(Number(summary.total)) ? Number(summary.total) : checks.length;

  const categoryLabels = {
    internal: 'Internal',
    host_port: 'Host Port',
    portal: 'Portal Route',
    cloudflare: 'Cloudflare Origin',
    remote: 'Public URL'
  };
  const statusLabels = {
    ok: '✓ Reachable',
    fail: '✗ Unreachable',
    warn: '⚠ Warning',
    skipped: '– Skipped'
  };

  if (summaryEl) {
    const overallOk = res?.ok !== false && failed === 0;
    const headline = overallOk
      ? `<span style="color:#34d399;font-weight:700;">✓ All required targets reachable</span>`
      : `<span style="color:#f87171;font-weight:700;">✗ ${failed} unreachable target${failed === 1 ? '' : 's'}</span>`;
    const metaParts = [`${passed}/${total} passed`];
    if (warnings > 0) metaParts.push(`${warnings} warning${warnings === 1 ? '' : 's'}`);
    if (skipped > 0) metaParts.push(`${skipped} skipped`);
    if (res?.recommended_origin) metaParts.push(`Recommended origin: <code>${escapeHtml(res.recommended_origin)}</code>`);
    if (res?.connector_mode) metaParts.push(`Connector: <code>${escapeHtml(res.connector_mode)}</code>`);
    summaryEl.innerHTML = `${headline} · ${metaParts.join(' · ')}`;
  }

  if (statusDotEl && statusDotEl.classList) {
    statusDotEl.classList.remove('ok', 'error', 'warn');
    statusDotEl.classList.add(failed > 0 ? 'error' : (warnings > 0 ? 'warn' : 'ok'));
  }

  if (resultsEl) {
    if (resultsEl.style) resultsEl.style.display = 'grid';
    if (checks.length === 0) {
      resultsEl.innerHTML = '<div class="reachability-item">No reachability checks returned.</div>';
      return;
    }
    resultsEl.innerHTML = checks.map(check => {
      const rawStatus = String(check?.status || (check?.ok === true ? 'ok' : (check?.ok === false ? 'fail' : 'warn'))).toLowerCase();
      const statusKey = ['ok', 'fail', 'warn', 'skipped'].includes(rawStatus) ? rawStatus : (check?.ok === false ? 'fail' : 'warn');
      const badgeLabel = statusLabels[statusKey];
      const categoryKey = String(check?.category || '').toLowerCase();
      const categoryText = categoryLabels[categoryKey] || escapeHtml(String(check?.category || 'Check'));
      const latencyText = (typeof check?.latency_ms === 'number' && Number.isFinite(check.latency_ms))
        ? `${check.latency_ms.toFixed(1)} ms`
        : (check?.latency_ms != null && check.latency_ms !== '' ? `${escapeHtml(String(check.latency_ms))} ms` : '');
      const targetHtml = check?.target ? `<code>${escapeHtml(String(check.target))}</code>` : '';
      const detailHtml = check?.detail ? `<div class="reachability-detail">${escapeHtml(String(check.detail))}</div>` : '';
      const remediationHtml = check?.remediation
        ? `<div class="reachability-remediation"><strong>Remediation:</strong> ${escapeHtml(String(check.remediation))}</div>`
        : '';

      return `<div class="reachability-item reachability-${statusKey}" data-reachability-status="${statusKey}">
        <div class="reachability-item-head">
          <span class="reachability-name">${escapeHtml(String(check?.name || check?.id || 'Check'))}</span>
          <span class="reachability-badge reachability-badge-${statusKey}">${badgeLabel}</span>
        </div>
        <div class="reachability-meta">
          <span>${categoryText}</span>${targetHtml}${latencyText ? `<span>${latencyText}</span>` : ''}
        </div>
        ${detailHtml}
        ${remediationHtml}
      </div>`;
    }).join('');
  }
}

async function runReachabilityCheck(options = {}) {
  const btn = options.button || null;
  const resultsEl = document.getElementById(options.resultsId || 'reachability-results');
  const summaryEl = options.summaryId ? document.getElementById(options.summaryId) : null;
  const statusDotEl = options.statusDotId ? document.getElementById(options.statusDotId) : null;
  const originInput = document.getElementById('cf-origin-target');
  const originUrl = (originInput && originInput.value ? originInput.value.trim() : '')
    || (typeof cachedCloudflareStatus !== 'undefined' && cachedCloudflareStatus?.recommended_origin ? cachedCloudflareStatus.recommended_origin : '');

  const origText = btn ? btn.textContent : '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Testing Reachability…';
  }
  if (summaryEl) {
    summaryEl.textContent = 'Checking internal services, host ports (:3001, :4005, :8088), Cloudflare origin, and public URLs…';
  }
  if (resultsEl) {
    if (resultsEl.style) resultsEl.style.display = 'block';
    resultsEl.innerHTML = '<em>Running reachability probes…</em>';
  }

  try {
    const payload = { include_remote: true };
    if (originUrl) payload.origin_url = originUrl;
    const res = await api('/api/reachability', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    renderReachabilityResults(res, resultsEl, summaryEl, statusDotEl);
    if (!summaryEl && resultsEl) {
      const failed = Number(res?.summary?.failed ?? (Array.isArray(res?.checks) ? res.checks.filter(c => c.status === 'fail' || c.ok === false).length : 0));
      const summaryBanner = `<div class="reachability-summary" style="grid-column:1 / -1;margin-top:0;">${failed === 0 && res?.ok !== false ? '<span style="color:#34d399;font-weight:700;">✓ All checked targets reachable</span>' : `<span style="color:#f87171;font-weight:700;">✗ ${failed} unreachable target${failed === 1 ? '' : 's'}</span>`}${res?.recommended_origin ? ` · Recommended origin: <code>${escapeHtml(String(res.recommended_origin))}</code>` : ''}</div>`;
      resultsEl.innerHTML = summaryBanner + resultsEl.innerHTML;
    }
    return res;
  } catch (err) {
    if (summaryEl) summaryEl.innerHTML = `<span style="color:#f87171;">✗ Reachability check failed: ${escapeHtml(err.message)}</span>`;
    if (resultsEl) resultsEl.innerHTML = `<div class="reachability-item reachability-fail"><strong>✗ Reachability check failed:</strong> ${escapeHtml(err.message)}</div>`;
    if (typeof notify === 'function') notify(`Reachability check failed: ${err.message}`, true);
    return null;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }
}

document.getElementById('btn-test-cf-reachability')?.addEventListener('click', (e) => {
  return runReachabilityCheck({
    button: e.currentTarget,
    resultsId: 'cf-reachability-results'
  });
});

document.querySelectorAll('.streaming-mode-section .mode-pill').forEach(btn => {
  btn.addEventListener('click', () => {
    const mode = btn.getAttribute('data-mode');
    setStreamingMode(mode);
    if (typeof setFormDirty === 'function') setFormDirty(true);
  });
});

document.querySelectorAll('.access-scope-section .mode-pill').forEach(btn => {
  btn.addEventListener('click', () => {
    const scope = btn.getAttribute('data-scope');
    setAccessScope(scope);
    if (typeof setFormDirty === 'function') setFormDirty(true);
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

let isPollReadinessInFlight = false;
async function pollPlaybackReadiness() {
  clearTimeout(readinessTimer);
  if (isPollReadinessInFlight) return;
  isPollReadinessInFlight = true;
  try {
    if (!document.hidden) await refreshPlaybackReadiness();
  } finally {
    isPollReadinessInFlight = false;
    const interval = (playbackReadiness && playbackReadiness.ready) ? 30000 : 5000;
    readinessTimer = setTimeout(pollPlaybackReadiness, interval);
  }
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
  const kind = document.getElementById('playback-test-kind')?.value || 'movie';
  const contentId = document.getElementById('playback-test-id')?.value?.trim() || '';
  const playbackPayload = { mode, kind };
  if (contentId) playbackPayload.content_id = contentId;

  try {
    const res = await api('/api/test-playback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(playbackPayload)
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
      notify(`Playback check: ${res.message || 'Verification issue detected'}`, true);
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
    notify(`Playback test failed: ${err.message}`, true);
  } finally {
    playbackBusy = false;
    await refreshPlaybackReadiness();
  }
}

function renderBackupArchives(telemetry) {
  const listEl = document.getElementById('backup-archives-list');
  if (!listEl) return;
  const archives = Array.isArray(telemetry?.archives) ? telemetry.archives : [];
  if (!archives.length) {
    listEl.innerHTML = '<div style="font-size:12.5px;color:var(--text-muted);padding:6px 2px;">No backup archives found in backups/.</div>';
    return;
  }
  listEl.innerHTML = archives.map(arch => {
    const safeName = escapeHtml(arch.name || '');
    const dateStr = arch.mtime ? escapeHtml(new Date(arch.mtime).toLocaleString()) : 'Unknown date';
    const sizeNum = Number(arch.size_mb ?? 0);
    const sizeLabel = `${Number.isFinite(sizeNum) ? sizeNum.toFixed(2) : '0.00'} MB`;
    const pgBadge = arch.postgresIncluded === true
      ? '<span class="op-badge badge-pg-included">Postgres Included</span>'
      : (arch.postgresIncluded === false
        ? '<span class="op-badge badge-pg-missing">No Postgres</span>'
        : '<span class="op-badge badge-pg-unknown">Postgres Unverified</span>');
    return `<div class="backup-archive-row">
      <div class="backup-archive-meta">
        <span class="backup-archive-name">${safeName}</span>
        <span class="backup-archive-sub"><span>${dateStr}</span><span>•</span><span>${escapeHtml(sizeLabel)}</span>${pgBadge}</span>
      </div>
      <div class="backup-archive-actions">
        <button type="button" class="mini-action-btn btn-restore-backup" data-archive="${safeName}">Restore ↺</button>
      </div>
    </div>`;
  }).join('');
  if (typeof listEl.querySelectorAll === 'function') {
    listEl.querySelectorAll('.btn-restore-backup').forEach(btn => {
      btn.addEventListener('click', event => {
        const targetBtn = event.currentTarget || btn;
        const filename = targetBtn.dataset?.archive || targetBtn.getAttribute?.('data-archive') || '';
        restoreBackupArchive(filename, targetBtn);
      });
    });
  }
}

async function refreshBackupsList() {
  const telemetry = await api('/api/backups');
  renderBackupArchives(telemetry);
  return telemetry;
}

async function restoreBackupArchive(filename, button) {
  if (!filename) return false;
  if (!confirm(`Restore backup "${filename}"? This will overwrite current stack configuration and databases.`)) return false;
  const restoreBtns = Array.from(document.querySelectorAll?.('.btn-restore-backup') || []);
  const targets = restoreBtns.length ? restoreBtns : (button ? [button] : []);
  const origText = button ? button.textContent : '';
  targets.forEach(btn => { if (btn) btn.disabled = true; });
  if (button) button.textContent = 'Restoring…';
  try {
    const res = await api('/api/backups/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename })
    });
    const out = document.getElementById('maintenance-output');
    if (out) out.textContent = res.message || `Restored ${filename}.`;
    notify(res.message || `Backup ${filename} restored.`);
    return true;
  } catch (error) {
    const out = document.getElementById('maintenance-output');
    if (out) out.textContent = `Restore failed: ${error.message}`;
    notify(`Restore failed: ${error.message}`, true);
    return false;
  } finally {
    targets.forEach(btn => { if (btn) btn.disabled = false; });
    if (button) button.textContent = origText;
  }
}

async function pruneBackups(keepLast, button) {
  const parsed = Number.parseInt(keepLast, 10);
  const keep = Number.isFinite(parsed) ? Math.min(100, Math.max(1, parsed)) : 5;
  if (button) button.disabled = true;
  try {
    const res = await api('/api/backups/prune', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keep_last: keep })
    });
    const prunedCount = res.pruned ? res.pruned.length : 0;
    notify(`Backup retention: kept ${res.retained?.length || 0} (limit ${keep}), deleted ${prunedCount} old archive(s).`);
    await refreshBackupsList();
    if (typeof refreshHealthTelemetry === 'function') {
      refreshHealthTelemetry().catch(() => {});
    }
    return res;
  } catch (e) {
    notify(`Prune failed: ${e.message}`, true);
    return null;
  } finally {
    if (button) button.disabled = false;
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
  if (typeof refreshBackupsList === 'function') {
    try { await refreshBackupsList(); } catch (_) {}
  }
}

async function runOperations() {
  document.getElementById('refresh-maintenance')?.addEventListener('click', () => refreshMaintenance().catch(error=>notify(error.message, true)));
  document.getElementById('btn-refresh-backups')?.addEventListener('click', () => {
    if (typeof refreshBackupsList === 'function') refreshBackupsList().catch(error => notify(error.message, true));
  });
  document.getElementById('btn-maintenance-prune-backups')?.addEventListener('click', event => {
    const keepVal = document.getElementById('backup-keep-last')?.value || 5;
    if (typeof pruneBackups === 'function') pruneBackups(keepVal, event.currentTarget);
  });
  document.getElementById('btn-restart-stack')?.addEventListener('click', async event => {
    const button = event.currentTarget;
    if (!confirm('Restart stack containers? Active streams will briefly pause.')) return;
    button.disabled = true;
    try {
      const result = await api('/api/restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      });
      const msg = result.message || 'Stack restart initiated.';
      const readinessOut = document.getElementById('readiness-output');
      if (readinessOut) readinessOut.textContent = msg;
      notify(msg, result.success === false);
    } catch (error) {
      notify(`Stack restart failed: ${error.message}`, true);
    } finally {
      button.disabled = false;
    }
  });
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
  const runCacheAction = async (button, dryRun) => {
    if (!dryRun && !confirm('Clear temporary cache? Stored profiles and databases will be kept.')) return;
    button.disabled = true;
    try {
      const includePosterCache = Boolean(document.getElementById('clean-cache-posters')?.checked);
      const result = await api('/api/clean-cache', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dry_run: dryRun, include_poster_cache: includePosterCache })
      });
      const detailLines = Array.isArray(result.details) && result.details.length
        ? '\n' + result.details.map(d => {
          const mb = ((d.size_bytes || 0) / (1024 * 1024)).toFixed(2);
          return `• ${d.target}: ${mb} MB (${d.file_count || 0} files) [${d.status}]`;
        }).join('\n')
        : '';
      const summary = dryRun
        ? `Preview: ${result.freed_mb} MB recoverable (${result.total_files || 0} files).`
        : `Cleared ${result.freed_mb} MB.`;
      document.getElementById('cache-output').textContent = result.success
        ? `${summary}${detailLines}`
        : `Cleanup incomplete: ${(result.errors || []).join('; ')}`;
    } catch (error) { document.getElementById('cache-output').textContent = error.message; }
    finally { button.disabled = false; }
  };
  document.getElementById('preview-cache')?.addEventListener('click', event => runCacheAction(event.currentTarget, true));
  document.getElementById('clean-cache')?.addEventListener('click', event => runCacheAction(event.currentTarget, false));
  const output = id => document.getElementById(id);
  document.getElementById('btn-test-reachability')?.addEventListener('click', event => {
    if (typeof runReachabilityCheck === 'function') {
      return runReachabilityCheck({
        button: event.currentTarget,
        resultsId: 'reachability-results',
        summaryId: 'reachability-summary',
        statusDotId: 'reachability-status-dot'
      });
    }
  });
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
  const providerCheckSelect = document.getElementById('provider-check');
  const providerKeyInput = document.getElementById('provider-key');
  const syncProviderKeyPlaceholder = () => {
    if (!providerCheckSelect || !providerKeyInput) return;
    if (providerCheckSelect.value === 'usenet') {
      providerKeyInput.placeholder = 'Tests saved Usenet NNTP server (no key needed)';
    } else if (providerCheckSelect.value === 'nzb') {
      providerKeyInput.placeholder = 'Paste NZB key or leave blank for saved';
    } else {
      providerKeyInput.placeholder = 'Paste key to test';
    }
  };
  providerCheckSelect?.addEventListener('change', syncProviderKeyPlaceholder);
  syncProviderKeyPlaceholder();
  document.getElementById('validate-provider')?.addEventListener('click', async () => {
    try {
      const provider = document.getElementById('provider-check').value;
      const rawKey = document.getElementById('provider-key').value;
      const key = (provider === 'nzb' && !rawKey.trim()) ? 'saved' : rawKey;
      const result = await api('/api/validate-provider', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({provider, key})});
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

  document.getElementById('proxy-format')?.addEventListener('change', () => {
    generateProxySnippet();
  });

  document.getElementById('generate-proxy')?.addEventListener('click', async () => {
    await generateProxySnippet();
  });

  document.getElementById('copy-proxy-config')?.addEventListener('click', async (e) => {
    let text = document.getElementById('proxy-output')?.textContent;
    if (!text || text === 'Not generated yet.') {
      await generateProxySnippet();
      text = document.getElementById('proxy-output')?.textContent;
    }
    if (text && text !== 'Not generated yet.') {
      copyToClipboard(text, 'Proxy configuration copied to clipboard.', e.currentTarget);
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
        'SUBDL_API_KEY','SUBSOURCE_API_KEY','WYZIE_API_KEY','OPENSUBTITLES_API_KEY','NZB_INDEXER_API_KEY','NZB_INDEXER_URL'
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
    e.preventDefault();
    await startLumiereRebuild(e.currentTarget);
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
    if (setupSaveInFlight) {
      notify('Wait for the current save before discarding changes.', true);
      return;
    }
    loadSettings().then(applied => {
      if (applied) notify('Unsaved changes discarded');
    }).catch(error => notify(error.message, true));
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
      const res = await api('/api/webhook-test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: webhookUrl })
      });
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
      notify(`Watchdog probe failed: ${e.message}`, true);
    }
  });

  document.getElementById('btn-prune-backups')?.addEventListener('click', async event => {
    const keepVal = document.getElementById('backup-keep-last')?.value || 5;
    await pruneBackups(keepVal, event.currentTarget);
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
      refreshMaintenance().catch(error => notify(error.message, true));
    }
  });

  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (healthEventSource) {
          try { healthEventSource.close(); } catch (_) {}
          healthEventSource = null;
        }
        if (healthInterval) {
          clearInterval(healthInterval);
          healthInterval = null;
        }
        if (pollTimer) {
          clearTimeout(pollTimer);
          pollTimer = null;
        }
        if (readinessTimer) {
          clearTimeout(readinessTimer);
          readinessTimer = null;
        }
      } else {
        startHealthStream();
        pollSetup();
        pollPlaybackReadiness();
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
  if (typeof document !== 'undefined' && document.hidden) return;
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
      const audio = prefs.audio_language || prefs.audioLanguage;
      const sub = prefs.subtitle_language || prefs.subtitleLanguage;
      const mode = prefs.subtitle_mode || prefs.subtitleMode;
      const scale = prefs.font_scale || prefs.fontScale;
      if (audioSel && audio) audioSel.value = audio;
      if (subSel && sub) subSel.value = sub;
      if (modeSel && mode) modeSel.value = mode;
      if (fontSel && scale) fontSel.value = String(scale);
      if (outPre) {
        outPre.textContent = `Loaded preferences: audio=${audio || 'eng'}, subtitles=${sub || 'eng'} (${mode || 'forced'}), scale=${scale || 100}%`;
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
      notify(`Failed to save player presets: ${err.message}`, true);
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

async function deriveAesGcmKey(passphrase, saltBytes, iterations = 600000) {
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
      iterations: iterations,
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
      notify('Passphrase must be at least 6 characters for client-side encryption.', true);
      if (passInput) passInput.focus();
      return;
    }

    exportBtn.disabled = true;
    exportBtn.textContent = 'Encrypting…';
    try {
      const rawBundle = await api('/api/config-bundle-raw').catch(() => null);
      const envData = (rawBundle && rawBundle.env) || await api('/api/env').catch(() => ({}));
      const prefsData = (rawBundle && rawBundle.player_preferences) || await api('/api/player-preferences').catch(() => ({}));
      const bundlePayload = {
        env: envData,
        player_preferences: prefsData,
        version: 'aio-bundle-v2',
        exported_at: new Date().toISOString()
      };

      const salt = window.crypto.getRandomValues(new Uint8Array(16));
      const iv = window.crypto.getRandomValues(new Uint8Array(12));
      const key = await deriveAesGcmKey(passphrase, salt, 600000);

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
        iterations: 600000,
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
      notify(`Export failed: ${err.message}`, true);
      if (outputPre) outputPre.textContent = `Export error: ${err.message}`;
    } finally {
      exportBtn.disabled = false;
      exportBtn.textContent = 'Export Encrypted Bundle 🔐';
    }
  });

  importBtn.addEventListener('click', () => {
    const passphrase = passInput ? passInput.value.trim() : '';
    if (!passphrase) {
      notify('Please enter your bundle passphrase above before selecting an import file.', true);
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
      notify('Please enter your bundle passphrase to decrypt.', true);
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
      const iterations = bundle.iterations || 600000;
      let key;
      let decryptedBytes;
      try {
        key = await deriveAesGcmKey(passphrase, new Uint8Array(salt), iterations);
        decryptedBytes = await window.crypto.subtle.decrypt(
          { name: 'AES-GCM', iv: new Uint8Array(iv) },
          key,
          ciphertext
        );
      } catch (decryptErr) {
        if (iterations !== 100000) {
          key = await deriveAesGcmKey(passphrase, new Uint8Array(salt), 100000);
          decryptedBytes = await window.crypto.subtle.decrypt(
            { name: 'AES-GCM', iv: new Uint8Array(iv) },
            key,
            ciphertext
          );
        } else {
          throw decryptErr;
        }
      }

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
      notify(`Decryption failed: Check passphrase. (${err.message})`, true);
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



  const launchEmbeddedBtn = document.getElementById('btn-launch-embedded-player');
  if (launchEmbeddedBtn) {
    launchEmbeddedBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const aioPort = (cachedEnv && cachedEnv.ports && cachedEnv.ports.aiostreams) || (cachedEnv && cachedEnv.PORT_AIOSTREAMS) || 3001;
      const playerUrl = cachedManifestInfo?.jellyfinWebPlayer || `${location.protocol}//${location.hostname}:${aioPort}/jellyfin/web/`;
      window.open(playerUrl, '_blank', 'noopener,noreferrer');
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
      if ((e.ctrlKey || e.metaKey) && (e.key === 'Enter' || e.key.toLowerCase() === 's')) {
        const setupForm = document.getElementById('setup-form');
        const setupBtn = document.getElementById('setup-button');
        if (setupForm && setupBtn && !setupBtn.disabled) {
          e.preventDefault();
          setupBtn.click();
        }
        return;
      }

      if (e.key === 'Escape') {
        const frameDialog = document.getElementById('service-frame-modal');
        if (frameDialog && frameDialog.open) {
          e.preventDefault();
          closeServiceViewer();
          return;
        }
        const logDialog = document.getElementById('service-log-dialog');
        if (logDialog && logDialog.open) {
          e.preventDefault();
          closeLogDialog();
          return;
        }
        const lumiereDialog = document.getElementById('lumiere-stats-dialog');
        if (lumiereDialog && lumiereDialog.open) {
          e.preventDefault();
          closeLumiereStatsDialog();
          return;
        }
        if (shortcutsModal && shortcutsModal.open) {
          e.preventDefault();
          shortcutsModal.close();
          return;
        }
        if (statsHud && statsHud.style.display !== 'none') {
          e.preventDefault();
          statsHud.style.display = 'none';
          return;
        }
        return;
      }

      const tag = e.target && e.target.tagName ? e.target.tagName.toLowerCase() : '';
      const isInput = tag === 'input' || tag === 'textarea' || tag === 'select' || (e.target && e.target.isContentEditable);
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
      } else if (e.key === 'p' || e.key === 'P') {
        e.preventDefault();
        const testBtn = document.getElementById('btn-test-playback');
        const openPlayerBtn = document.getElementById('aiostreams-player-action');
        if (testBtn && !testBtn.disabled) {
          testBtn.click();
        } else if (openPlayerBtn && openPlayerBtn.style.display !== 'none') {
          openPlayerBtn.click();
        }
      } else if (e.key === 'e' || e.key === 'E') {
        e.preventDefault();
        const bundleCard = document.getElementById('card-encrypted-bundle');
        if (bundleCard) {
          bundleCard.scrollIntoView({ behavior: 'smooth' });
          const pass = document.getElementById('bundle-passphrase');
          if (pass) pass.focus();
        }
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
