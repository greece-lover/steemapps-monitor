// sources.html — list of measurement contributors with their counts.
//
// Server returns the primary monitor first, then every active
// participant. We keep that order so the operator/community split is
// visible at a glance.

(() => {
  const { el, getJson, showError, clearError } = window.SteemAPI;

  function row(s) {
    const handleHref = `https://steemit.com/@${encodeURIComponent(s.steem_account)}`;
    const handleCell = el('td', {}, [
      el('a', { href: handleHref, target: '_blank', rel: 'noopener' }, [`@${s.steem_account}`]),
      s.primary ? el('span', { class: 'pill pill-primary', title: 'central monitor' }, [' primary']) : null,
    ]);
    const lastSeen = s.last_seen ? new Date(s.last_seen).toLocaleString() : '—';
    return el('tr', {}, [
      handleCell,
      el('td', {}, [s.display_label]),
      el('td', { class: 'muted' }, [s.region || '—']),
      el('td', { class: 'mono' }, [String(s.measurements_24h)]),
      el('td', { class: 'mono' }, [String(s.measurements_7d)]),
      el('td', { class: 'muted' }, [lastSeen]),
    ]);
  }

  async function load() {
    try {
      clearError();
      const data = await getJson('/api/v1/sources');
      const tbody = document.querySelector('#sources-table tbody');
      tbody.innerHTML = '';
      if (!data.sources.length) {
        tbody.appendChild(el('tr', {}, [
          el('td', { colspan: 6, class: 'muted' }, ['No sources yet.']),
        ]));
        return;
      }
      for (const s of data.sources) tbody.appendChild(row(s));
    } catch (e) {
      showError(`Could not load sources: ${e.message}`);
    }
  }

  load();
})();
