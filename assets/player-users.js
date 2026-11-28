/* Player-only invitations use the existing AIOStreams profiles, never portal accounts. */
(() => {
  const section = document.getElementById('player-users');
  const list = document.getElementById('player-users-list');
  const status = document.getElementById('player-users-status');
  const form = document.getElementById('player-users-form');
  const nameInput = document.getElementById('player-user-name');
  const refresh = document.getElementById('player-users-refresh');
  if (!section || !list || !status || !form || !nameInput || !refresh) return;
  let busy = false;
  let loaded = false;
  let revision = null;
  let canManage = false;
  let canInvite = false;

  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  const button = (label, handler) => {
    const el = node('button', label, 'text-button');
    el.type = 'button';
    el.addEventListener('click', handler);
    return el;
  };
  const safeInvite = value => {
    if (typeof value !== 'string' || !value) return null;
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
      return url.href;
    } catch { return null; }
  };
  const setBusy = value => {
    busy = value;
    section.setAttribute('aria-busy', String(value));
    for (const el of section.querySelectorAll('button, input')) el.disabled = value;
    for (const el of form.querySelectorAll('input, button[type="submit"]')) el.disabled = value || !canInvite;
  };
  const clearStatus = () => status.replaceChildren();

  function renderUsers(users) {
    list.replaceChildren();
    if (!users.length) {
      list.append(node('p', 'No invited users yet. Add a person to share your catalogs with their own player profile.', 'field-help'));
      return;
    }
    for (const user of users) {
      if (!user || typeof user.id !== 'string' || typeof user.name !== 'string') continue;
      const row = node('div', undefined, 'player-user-row');
      row.append(node('strong', user.name));
      const actions = node('div', undefined, 'player-user-actions');
      const invite = safeInvite(user.inviteUrl);
      if (invite) actions.append(button('Copy invite link', e => copyToClipboard(invite, 'Player invite link copied.', e.currentTarget)));
      else row.append(node('span', 'Invite link unavailable', 'field-help'));
      if (user.isolated && canManage) {
      if (canInvite) {
      actions.append(button('Reset PIN', () => mutate({action: 'reset_pin', id: user.id})));
      actions.append(button('Replace link', () => {
        if (!busy && window.confirm(`Replace the invite link for ${user.name}? Their previous link will stop working.`)) {
          return mutate({action: 'replace_link', id: user.id});
        }
      }));
      }
      actions.append(button('Remove access', () => {
        if (!busy && window.confirm(`Remove player access for ${user.name}? Existing devices can take up to 30 seconds to sign out.`)) return mutate({action: 'remove', id: user.id});
      }));
      } else row.append(node('span', 'Manage this profile in AIOStreams.', 'field-help'));
      row.append(actions);
      list.append(row);
    }
  }

  function acceptResponse(res) {
    if (res?.success !== true || !Array.isArray(res.users)) throw new Error('Could not load player users. Try again after setup completes.');
    revision = res.revision;
    canManage = typeof revision === 'string';
    canInvite = canManage && res.enabled === true && res.pinSignInEnabled === true;
    renderUsers(res.users);
    loaded = true;
  }

  async function loadUsers() {
    if (busy) return;
    clearStatus();
    status.textContent = 'Loading player users…';
    setBusy(true);
    try {
      acceptResponse(await api('/api/player-users'));
      clearStatus();
      if (!canInvite) status.textContent = 'Invitations need PIN sign-in enabled. Update and recreate AIOStreams, then refresh.';
    } catch (error) {
      status.textContent = error.message || 'Could not load player users.';
    } finally { setBusy(false); }
  }

  async function mutate(payload) {
    if (busy || !canManage || !revision || (payload.action !== 'remove' && !canInvite)) return;
    clearStatus();
    status.textContent = 'Saving player access…';
    setBusy(true);
    try {
      const res = await api('/api/player-users', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...payload, expectedRevision: revision})
      });
      acceptResponse(res);
      if (payload.action === 'create') nameInput.value = '';
      clearStatus();
      // Do not retain the PIN in application state, storage, or list responses.
      // Closing this section or taking another action removes the one-time display.
      if (section.open && typeof res.pin === 'string' && /^\d{6,12}$/.test(res.pin)) {
        status.append(node('span', 'PIN — copy it now: '), node('strong', res.pin));
        status.append(button('Copy PIN', e => copyToClipboard(res.pin, 'Player PIN copied.', e.currentTarget)));
        status.append(node('span', ' Share the invite link and PIN with this person. This PIN is shown only now.', 'field-help'));
      } else {
        status.textContent = payload.action === 'remove' ? 'Player access removed. Existing sessions may take up to 30 seconds to stop working.' : 'Player access updated.';
      }
      const invite = safeInvite(res.inviteUrl);
      if (section.open && invite) status.append(button('Copy invite link', e => copyToClipboard(invite, 'Player invite link copied.', e.currentTarget)));
    } catch (error) {
      loaded = false;
      canManage = false;
      canInvite = false;
      revision = null;
      status.textContent = (error.message || 'Could not update player access.') + ' Select Refresh before another change.';
    } finally { setBusy(false); }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    if (busy) return;
    const name = nameInput.value.trim();
    if (!name || name.length > 32) {
      status.textContent = 'Enter a name between 1 and 32 characters.';
      nameInput.focus();
      return;
    }
    return mutate({action: 'create', name});
  });
  refresh.addEventListener('click', loadUsers);
  section.addEventListener('toggle', () => {
    if (!section.open) clearStatus();
    else if (!loaded) return loadUsers();
  });
  document.getElementById('open-player-users')?.addEventListener('click', () => { section.open = true; });
  setBusy(false);
  if (section.open) loadUsers();
})();
