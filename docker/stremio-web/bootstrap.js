/* Seed the actual browser store before Stremio loads, once per guest profile.
 * A JSON file on disk alone is not imported by current upstream web builds.
 */
(() => {
  let attempts = 0;
  function initialize() {
  try {
    let existing = JSON.parse(localStorage.getItem('profile') || 'null');
    let defaults;
    if (existing?.auth) return;
    const seeded = Boolean(localStorage.getItem('aio_profile_seeded'));
    // Reuse the image's full default schema; the current web core additionally
    // requires interfaceScale, which its bundled defaults do not yet include.
    if (!existing) {
      defaults = read('/aio-defaults.json');
      existing = defaults.profile;
      existing.settings.interfaceScale ??= 1;
    }
    function read(path) {
      const request = new XMLHttpRequest();
      request.open('GET', path, false);
      request.send();
      if (request.status !== 200) throw new Error('Seed unavailable');
      return JSON.parse(request.responseText);
    }
    const seed = read('/aio-seed.json');
    if (!seed.profile?.addons?.length) {
      if (++attempts < 40) setTimeout(initialize, 1000);
      return;
    }
    if (seeded) {
      const managed = existing.addons?.find(addon => addon.manifest.id === seed.profile.addons[0].manifest.id);
      if (!managed || managed.transportUrl === seed.profile.addons[0].transportUrl) return;
    }
    for (const [key,value] of Object.entries(defaults || {})) {
      if (key !== 'profile' && localStorage.getItem(key) === null) localStorage.setItem(key,JSON.stringify(value));
    }
    const profile = {
      ...existing,
      settings: {...existing.settings},
      addons: [...seed.profile.addons]
    };
    // Preserve addons explicitly installed by a guest, without duplicating defaults.
    for (const addon of existing?.addons || []) {
      if (!profile.addons.some(item => item.manifest.id === addon.manifest.id)) profile.addons.push(addon);
    }
    if (!seeded) profile.settings.streamingServerUrl = location.origin + '/';
    localStorage.setItem('profile', JSON.stringify(profile));
    if (!seeded) localStorage.setItem('streaming_server_urls', JSON.stringify({uid: null, items: {[location.origin + '/']: new Date().toISOString()}}));
    localStorage.setItem('aio_profile_seeded', '1');
    if (document.readyState !== 'loading') location.reload();
  } catch (error) {
    console.warn('AIO initial settings unavailable; keeping existing Stremio settings.');
  }
  }
  initialize();
})();

/* ==============================================================================
 * AIO Local Anime Enhancements: AniSkip (OP/ED/Recap Auto-Skip) & Subtitle Polish
 * ============================================================================== */
(() => {
  try {
    const subStyle = document.createElement('style');
    subStyle.id = 'aio-anime-subtitles';
    subStyle.textContent = `
      video::cue {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Trebuchet MS", sans-serif !important;
        font-weight: 600 !important;
        color: #ffffff !important;
        text-shadow: -1.5px -1.5px 0 #000, 1.5px -1.5px 0 #000, -1.5px 1.5px 0 #000, 1.5px 1.5px 0 #000, 0 3px 6px rgba(0,0,0,0.95) !important;
        background-color: transparent !important;
      }
      .aniskip-btn {
        position: absolute;
        right: 32px;
        bottom: 88px;
        background: rgba(18, 23, 25, 0.92);
        color: #edf0ed;
        border: 1px solid rgba(230, 165, 107, 0.7);
        padding: 9px 18px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 13px;
        letter-spacing: 0.02em;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 7px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.6), 0 0 10px rgba(230,165,107,0.25);
        z-index: 2147483647;
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        user-select: none;
        backdrop-filter: blur(8px);
      }
      .aniskip-btn:hover {
        background: rgba(230, 165, 107, 0.95);
        color: #0b0f10;
        transform: translateY(-2px) scale(1.03);
        box-shadow: 0 6px 20px rgba(0,0,0,0.8), 0 0 16px rgba(230,165,107,0.45);
      }
      .aniskip-btn:active {
        transform: translateY(0) scale(0.98);
      }
      .aniskip-toast {
        position: absolute;
        top: 36px;
        left: 50%;
        transform: translateX(-50%);
        background: rgba(18, 23, 25, 0.92);
        color: #e6a56b;
        border: 1px solid rgba(230, 165, 107, 0.5);
        padding: 7px 16px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 600;
        z-index: 2147483647;
        pointer-events: none;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        transition: opacity 0.3s;
      }
    `;
    if (!document.getElementById('aio-anime-subtitles')) {
      document.head.appendChild(subStyle);
    }
  } catch (e) {}

  let currentSkipTimes = null;
  let activeSkipBtn = null;
  let lastQueriedHash = '';

  async function checkAniSkip(video) {
    const hash = (typeof window !== 'undefined' && window.location ? window.location.hash : '') || '';
    if (hash === lastQueriedHash && currentSkipTimes !== null) return;
    lastQueriedHash = hash;
    currentSkipTimes = null;

    const match = hash.match(/(?:%2F|\/)(tt\d+|kitsu:\d+)%3A(\d+)%3A(\d+)/i) || 
                  hash.match(/(tt\d+|kitsu:\d+)[:%3A](\d+)[:%3A](\d+)/i);
    if (!match) return;

    const [_, rawId, s, ep] = match;
    const portalHost = (typeof window !== 'undefined' && window.location ? window.location.hostname : '') || 'localhost';
    const portalUrl = `http://${portalHost}:8088/api/aniskip?id=${encodeURIComponent(rawId)}&season=${s}&episode=${ep}&duration=${Math.round(video.duration || 0)}`;

    try {
      const resp = await fetch(portalUrl, { mode: 'cors' });
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.found && Array.isArray(data.results)) {
        currentSkipTimes = data.results;
      }
    } catch (e) {}
  }

  function handleVideoTimeUpdate(video) {
    if (!currentSkipTimes || !currentSkipTimes.length) {
      removeSkipButton();
      return;
    }

    const t = video.currentTime;
    const active = currentSkipTimes.find(item => {
      const start = item.interval?.startTime ?? -1;
      const end = item.interval?.endTime ?? -1;
      return t >= start && t < end;
    });

    if (!active) {
      removeSkipButton();
      return;
    }

    const autoSkip = localStorage.getItem('aio_auto_skip_anime') === '1';
    if (autoSkip && (active.skipType === 'op' || active.skipType === 'recap')) {
      video.currentTime = active.interval.endTime + 0.3;
      showToast(`Skipped ${active.skipType.toUpperCase()} ⏭`);
      return;
    }

    showSkipButton(video, active);
  }

  function showSkipButton(video, item) {
    if (activeSkipBtn && activeSkipBtn.dataset.skipType === item.skipType) return;
    removeSkipButton();

    const parent = video.parentElement || document.body;
    const btn = document.createElement('button');
    btn.className = 'aniskip-btn';
    btn.dataset.skipType = item.skipType;
    const label = item.skipType === 'op' ? 'Skip Intro' : 
                  item.skipType === 'ed' ? 'Skip Outro' : 
                  item.skipType === 'recap' ? 'Skip Recap' : 'Skip';
    btn.innerHTML = `<span>⏭</span><span>${label}</span>`;

    btn.onclick = (e) => {
      e.stopPropagation();
      video.currentTime = item.interval.endTime + 0.3;
      removeSkipButton();
    };

    parent.appendChild(btn);
    activeSkipBtn = btn;
  }

  function removeSkipButton() {
    if (activeSkipBtn) {
      activeSkipBtn.remove();
      activeSkipBtn = null;
    }
  }

  function showToast(msg) {
    const toast = document.createElement('div');
    toast.className = 'aniskip-toast';
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 400);
    }, 2000);
  }

  /* ==============================================================================
   * AIO Local Web Player Shortcuts (Space, Seek, Fullscreen, AniSkip)
   * ============================================================================== */
  if (typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('keydown', (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) ||
          document.activeElement?.isContentEditable) {
        return;
      }
      const video = document.querySelector('video');
      if (!video) return;

      if (e.code === 'Space' || e.key === 'k') {
        e.preventDefault();
        if (video.paused) video.play(); else video.pause();
      } else if (e.code === 'ArrowLeft' || e.key === 'j') {
        e.preventDefault();
        video.currentTime = Math.max(0, video.currentTime - 10);
        showToast('⏪ -10s');
      } else if (e.code === 'ArrowRight' || e.key === 'l') {
        e.preventDefault();
        video.currentTime = Math.min(video.duration || Infinity, video.currentTime + 10);
        showToast('⏩ +10s');
      } else if (e.key === 's' || e.key === 'S') {
        if (activeSkipBtn) {
          e.preventDefault();
          activeSkipBtn.click();
        }
      } else if (e.key === 'f' || e.key === 'F') {
        e.preventDefault();
        if (!document.fullscreenElement) {
          (video.closest('.player-container') || video).requestFullscreen?.().catch(() => {});
        } else {
          document.exitFullscreen?.().catch(() => {});
        }
      }
    });
  }

  if (typeof setInterval !== 'undefined') {
    setInterval(() => {
      const video = document.querySelector('video');
      if (!video) {
        removeSkipButton();
        return;
      }
      if (!video.dataset.aioHooked) {
        video.dataset.aioHooked = '1';
        video.addEventListener('timeupdate', () => handleVideoTimeUpdate(video));
        video.addEventListener('loadedmetadata', () => checkAniSkip(video));
        video.addEventListener('play', () => checkAniSkip(video));
        checkAniSkip(video);
      }
    }, 1000);
  }
})();
