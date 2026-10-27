// Lead board: businesses grouped by niche, each with a status, a drafted
// WhatsApp message and a button that opens the chat with it typed.
//
// Shared by the dashboard's Leads tab (statuses saved through the API) and the
// standalone leads.html export (statuses saved in this browser). The page
// passes `save(id, status)`; the board only renders and calls it.

(function () {
  const STATUSES = [
    ['novo', 'Não contatado'],
    ['enviado', 'Mensagem enviada'],
    ['negociando', 'Em negociação'],
    ['fechado', 'Venda fechada'],
    ['sem_interesse', 'Sem interesse'],
  ];
  const STATUS_LABEL = Object.fromEntries(STATUSES);
  const SIGNAL_LABELS = {
    NO_WEBSITE: 'sem site', WHATSAPP_ONLY_BOOKING: 'agenda só pelo WhatsApp',
    UNCLAIMED_LISTING: 'perfil do Google não reivindicado',
    NO_ONLINE_BOOKING: 'sem agendamento online', NO_SCHEMA_MARKUP: 'SEO básico faltando',
    BLOG_STALE: 'site desatualizado', RUNNING_GOOGLE_ADS: 'anuncia no Google',
    RUNNING_META_ADS: 'anuncia no Instagram/Facebook', INCUMBENT_AGENCY: 'já tem agência',
  };
  // Potential 0-100 read as a band, so nobody has to interpret a number.
  const BANDS = [
    [70, 'alto', '🔥', 'Potencial alto'],
    [60, 'bom', '👍', 'Potencial bom'],
    [45, 'medio', '🙂', 'Potencial médio'],
    [0, 'baixo', '💤', 'Potencial baixo'],
  ];
  function band(score) {
    const [, key, emoji, label] = BANDS.find(b => (score || 0) >= b[0]);
    return {key, emoji, label};
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }

  function nicheOf(l) { return (l.industry || 'sem categoria').trim().toLowerCase(); }

  function mount(root, opts) {
    const state = {
      leads: opts.leads || [],
      filter: 'todos', query: '', mobileOnly: false,
      open: new Set(), openLeads: new Set(),   // every niche starts closed
    };
    const save = opts.save || (() => Promise.resolve(true));

    root.classList.add('lb');
    root.innerHTML =
      '<div class="lb-toolbar">' +
        '<input class="lb-search" type="search" placeholder="Buscar empresa, telefone ou endereço">' +
        '<label class="lb-check"><input type="checkbox" class="lb-mobile"> Só celular</label>' +
        '<button type="button" class="lb-btn lb-csv">Baixar planilha</button>' +
      '</div>' +
      '<div class="lb-chips"></div>' +
      '<div class="lb-groups"></div>';

    const $ = sel => root.querySelector(sel);
    $('.lb-search').addEventListener('input', e => { state.query = e.target.value.trim().toLowerCase(); render(); });
    $('.lb-mobile').addEventListener('change', e => { state.mobileOnly = e.target.checked; render(); });
    $('.lb-csv').addEventListener('click', () => downloadCsv(state.leads));

    function visible(l) {
      if (state.filter !== 'todos' && (l.status || 'novo') !== state.filter) return false;
      if (state.mobileOnly && l.phone_type !== 'mobile') return false;
      if (state.query) {
        const hay = [l.company_name, l.phone, l.address, l.industry].join(' ').toLowerCase();
        if (!hay.includes(state.query)) return false;
      }
      return true;
    }

    function renderChips() {
      const counts = {todos: state.leads.length};
      STATUSES.forEach(([k]) => { counts[k] = 0; });
      state.leads.forEach(l => { counts[l.status || 'novo']++; });
      $('.lb-chips').innerHTML = [['todos', 'Todos']].concat(STATUSES).map(([k, label]) =>
        '<button type="button" class="lb-chip st-' + k + (state.filter === k ? ' on' : '') +
        '" data-filter="' + k + '">' + esc(label) + ' <b>' + counts[k] + '</b></button>').join('');
      root.querySelectorAll('.lb-chip').forEach(b => b.addEventListener('click', () => {
        state.filter = b.dataset.filter; render();
      }));
    }

    function potBadge(score, short) {
      const b = band(score);
      return '<span class="lb-pot pot-' + b.key + '" title="' + esc(b.label) + ' (' + (score || 0) + ' de 100)">' +
        b.emoji + ' ' + esc(short ? b.label.replace('Potencial ', '') : b.label) + '</span>';
    }

    function statusSelect(l, i) {
      return '<select class="lb-status st-' + esc(l.status || 'novo') + '" data-i="' + i + '" aria-label="Status">' +
        STATUSES.map(([k, label]) => '<option value="' + k + '"' +
          ((l.status || 'novo') === k ? ' selected' : '') + '>' + esc(label) + '</option>').join('') +
        '</select>';
    }

    function leadRow(l) {
      const i = state.leads.indexOf(l);
      let codes = (l.signals || '').split(';').filter(Boolean);
      if (codes.includes('WHATSAPP_ONLY_BOOKING')) codes = codes.filter(c => c !== 'NO_ONLINE_BOOKING');
      const tags = codes.map(c => '<span class="lb-tag">' + esc(SIGNAL_LABELS[c] || c) + '</span>').join('');
      const rating = l.rating !== '' && l.rating != null
        ? '★ ' + Number(l.rating).toFixed(1).replace('.', ',') + (l.review_count !== '' && l.review_count != null ? ' (' + l.review_count + ')' : '')
        : '';
      const mobile = l.phone_type === 'mobile';
      const links = [
        l.maps_url ? '<a href="' + esc(l.maps_url) + '" target="_blank" rel="noopener">mapa</a>' : '',
        l.website ? '<a href="' + esc(l.website) + '" target="_blank" rel="noopener">site</a>' : '',
      ].filter(Boolean).join(' · ');
      const isOpen = state.openLeads.has(l.id);
      return '<details class="lb-lead st-' + esc(l.status || 'novo') + '" data-id="' + esc(l.id) + '"' + (isOpen ? ' open' : '') + '>' +
        '<summary>' +
          '<span class="lb-name">' + esc(l.company_name) + '</span>' +
          '<span class="lb-meta">' + esc(rating) + (rating ? ' · ' : '') +
            (mobile ? 'celular' : (l.phone ? 'fixo' : 'sem telefone')) + '</span>' +
          potBadge(l.score, true) +
          statusSelect(l, i) +
        '</summary>' +
        '<div class="lb-body">' +
          '<div class="lb-info">' + esc(l.phone || 'sem telefone') + (l.address ? ' · ' + esc(l.address) : '') +
            (links ? ' · ' + links : '') + (l.status_at ? ' · status desde ' + esc(l.status_at) : '') + '</div>' +
          (tags ? '<div class="lb-tags">' + tags + '</div>' : '') +
          '<textarea class="lb-msg" rows="6" data-i="' + i + '">' + esc(l.whatsapp_message) + '</textarea>' +
          '<div class="lb-actions">' +
            (mobile && l.phone_e164
              ? '<button type="button" class="lb-btn lb-wa" data-i="' + i + '">Abrir no WhatsApp</button>'
              : '<span class="lb-note">' + (l.phone ? 'Telefone fixo: ligue ou visite' : 'Sem telefone') + '</span>') +
            '<button type="button" class="lb-btn lb-copy" data-i="' + i + '">Copiar texto</button>' +
          '</div>' +
        '</div>' +
      '</details>';
    }

    function render() {
      renderChips();
      const groups = new Map();
      state.leads.filter(visible).forEach(l => {
        const k = nicheOf(l);
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(l);
      });
      const all = new Map();
      state.leads.forEach(l => {
        const k = nicheOf(l);
        if (!all.has(k)) all.set(k, []);
        all.get(k).push(l);
      });
      // Highest average potential first; a bigger niche wins a tie.
      const avgOf = k => { const xs = all.get(k); return Math.round(xs.reduce((s, l) => s + (l.score || 0), 0) / xs.length); };
      const order = [...groups.keys()].sort((a, b) =>
        avgOf(b) - avgOf(a) || all.get(b).length - all.get(a).length || a.localeCompare(b));
      // Typing a name opens the niches it matches; nothing else opens one.
      const searching = Boolean(state.query);

      $('.lb-groups').innerHTML = order.length ? order.map(k => {
        const items = groups.get(k).slice().sort((a, b) => (b.score || 0) - (a.score || 0));
        const every = all.get(k);
        const avg = Math.round(every.reduce((s, l) => s + (l.score || 0), 0) / every.length);
        const counts = STATUSES.map(([s, label]) => {
          const n = every.filter(l => (l.status || 'novo') === s).length;
          return n ? '<span class="lb-mini st-' + s + '" title="' + esc(label) + '">' + n + '</span>' : '';
        }).join('');
        const open = searching || state.open.has(k);
        return '<details class="lb-niche" data-niche="' + esc(k) + '"' + (open ? ' open' : '') + '>' +
          '<summary><span class="lb-arrow" aria-hidden="true"></span>' +
            '<span class="lb-niche-name">' + esc(k) + '</span>' +
            '<span class="lb-niche-count">' + items.length + (items.length !== every.length ? ' de ' + every.length : '') +
              ' empresa' + (every.length === 1 ? '' : 's') + '</span>' +
            '<span class="lb-minis">' + counts + '</span>' +
            '<span class="lb-niche-score">' + potBadge(avg, false) + '</span>' +
          '</summary>' +
          '<div class="lb-leads">' + items.map(leadRow).join('') + '</div>' +
        '</details>';
      }).join('') : '<p class="lb-empty">Nenhuma empresa com esse filtro.</p>';
      wire();
    }

    function wire() {
      root.querySelectorAll('.lb-niche').forEach(d => d.addEventListener('toggle', () => {
        const k = d.dataset.niche;
        if (d.open) state.open.add(k); else state.open.delete(k);
      }));
      root.querySelectorAll('.lb-lead').forEach(d => d.addEventListener('toggle', () => {
        if (d.open) state.openLeads.add(d.dataset.id); else state.openLeads.delete(d.dataset.id);
      }));
      root.querySelectorAll('.lb-status').forEach(sel => {
        // A select inside <summary> would also toggle the row open/closed.
        sel.addEventListener('click', e => e.stopPropagation());
        sel.addEventListener('keydown', e => e.stopPropagation());
        sel.addEventListener('change', () => setStatus(Number(sel.dataset.i), sel.value));
      });
      root.querySelectorAll('.lb-msg').forEach(t => t.addEventListener('input', () => {
        state.leads[Number(t.dataset.i)].whatsapp_message = t.value;
      }));
      root.querySelectorAll('.lb-wa').forEach(b => b.addEventListener('click', () => {
        const l = state.leads[Number(b.dataset.i)];
        window.open('https://wa.me/' + l.phone_e164.replace('+', '') + '?text=' +
                    encodeURIComponent(l.whatsapp_message), '_blank', 'noopener');
        if ((l.status || 'novo') === 'novo') setStatus(Number(b.dataset.i), 'enviado');
      }));
      root.querySelectorAll('.lb-copy').forEach(b => b.addEventListener('click', async () => {
        const l = state.leads[Number(b.dataset.i)];
        try { await navigator.clipboard.writeText(l.whatsapp_message); b.textContent = 'Copiado'; }
        catch (e) { b.textContent = 'Selecione e copie'; }
        setTimeout(() => { b.textContent = 'Copiar texto'; }, 1500);
      }));
    }

    async function setStatus(i, status) {
      const l = state.leads[i];
      const before = [l.status, l.status_at];
      l.status = status;
      l.status_at = new Date().toISOString().slice(0, 10);
      render();
      let ok = false;
      try { ok = await save(l.id, status); } catch (e) { ok = false; }
      if (!ok) {
        [l.status, l.status_at] = before;
        render();
        if (opts.onError) opts.onError('Não consegui salvar o status.');
      } else if (opts.onChange) {
        opts.onChange(state.leads);
      }
    }

    render();
    return {
      setLeads(leads) { state.leads = leads; render(); },
      leads: () => state.leads,
    };
  }

  function downloadCsv(leads) {
    const cols = [['company_name', 'empresa'], ['industry', 'nicho'], ['status', 'status'],
      ['status_at', 'status_desde'], ['potencial', 'potencial'], ['score', 'potencial_0_a_100'], ['phone', 'telefone'],
      ['phone_type', 'tipo_telefone'], ['rating', 'nota'], ['review_count', 'avaliacoes'],
      ['address', 'endereco'], ['website', 'site'], ['maps_url', 'mapa'],
      ['whatsapp_message', 'mensagem']];
    const cell = v => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
    const lines = [cols.map(c => c[1]).join(',')].concat(leads.map(l => cols.map(([k]) =>
      cell(k === 'status' ? STATUS_LABEL[l.status || 'novo']
           : k === 'potencial' ? band(l.score).label.replace('Potencial ', '') : l[k])).join(',')));
    const blob = new Blob(['﻿' + lines.join('\r\n')], {type: 'text/csv;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'leads.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  window.LeadBoard = {mount, STATUSES};
})();
