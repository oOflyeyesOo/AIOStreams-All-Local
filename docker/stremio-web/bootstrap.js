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
