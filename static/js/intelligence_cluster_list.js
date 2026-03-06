// static/js/intelligence_cluster_list.js
document.addEventListener('DOMContentLoaded', () => {
  const API_LATEST = '/api/clusters/latest';
  const API_MEMBERS = (clusterId) => `/api/clusters/${encodeURIComponent(clusterId)}/members`;

  const container = document.getElementById('cluster-list-container');
  const refreshBtn = document.getElementById('refresh-btn');
  const sortSelect = document.getElementById('sort-select');

  function showLoading() {
    container.innerHTML = `<div class="loading-spinner">Loading Clusters...</div>`;
  }

  function showError(msg) {
    container.innerHTML = `<div style="color:red;padding:20px;text-align:center;">Error: ${msg}</div>`;
  }

  function escapeHTML(str) {
    if (str === null || str === undefined) return "";
    return String(str).replace(/[&<>"']/g, m => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[m]));
  }

  async function loadClusters() {
    const sortBy = sortSelect ? sortSelect.value : 'size';
    showLoading();
    try {
      const url = `${API_LATEST}?sort_by=${encodeURIComponent(sortBy)}&desc=1&limit=200`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      renderClusters(data);
    } catch (e) {
      console.error(e);
      showError(String(e));
    }
  }

  function renderClusters(payload) {
    const clusters = payload?.clusters || [];
    if (!clusters.length) {
      container.innerHTML = `<p style="text-align:center; padding: 50px;">NO Clusters</p>`;
      return;
    }

    const version = payload?.version || '';
    const headerHtml = version
      ? `<div class="cluster-header-hint">Version: <span class="version-badge">${escapeHTML(version)}</span></div>`
      : '';

    const html = clusters.map(c => {
      const clusterId = c.cluster_id;
      const size = c.size || 0;
      const uuid = c.repr_uuid || '';
      const title = c.repr_title || '(No Title)';
      const brief = c.repr_brief || '';
      const href = c.href || (uuid ? `/intelligence/${uuid}` : '#');

      return `
        <div class="article-card cluster-card" data-cluster-id="${escapeHTML(clusterId)}">
          <h3>
            <a href="${href}" class="article-title" data-uuid="${escapeHTML(uuid)}">
              ${escapeHTML(title)}
            </a>
          </h3>

          <div class="article-meta">
            <span class="article-time">Cluster: ${escapeHTML(clusterId)}</span>
            <span class="article-time">Size: ${size}</span>
            ${version ? `<span class="version-badge">${escapeHTML(version)}</span>` : ''}
            <button class="cluster-toggle" type="button" data-cluster-id="${escapeHTML(clusterId)}">
              Expand
            </button>
          </div>

          ${brief ? `<p class="article-summary">${escapeHTML(brief)}</p>` : ''}

          <div class="cluster-children" id="children-${escapeHTML(clusterId)}" style="display:none;">
            <div class="cluster-children-loading">Loading...</div>
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = headerHtml + html;
  }

  // Expand/Collapse handler (event delegation)
  document.body.addEventListener('click', async (e) => {
    const btn = e.target.closest('.cluster-toggle');
    if (!btn) return;

    const clusterId = btn.dataset.clusterId;
    const box = document.getElementById(`children-${clusterId}`);
    if (!box) return;

    const isOpen = box.style.display !== 'none';
    if (isOpen) {
      box.style.display = 'none';
      btn.textContent = 'Expand';
      return;
    }

    // open
    box.style.display = 'block';
    btn.textContent = 'Collapse';

    // lazy load once
    if (box.dataset.loaded === '1') return;

    try {
      box.innerHTML = `<div class="cluster-children-loading">Loading members...</div>`;
      const resp = await fetch(`${API_MEMBERS(clusterId)}?limit=120&offset=0`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      const items = data.items || [];
      if (!items.length) {
        box.innerHTML = `<div style="color:#666;">No members</div>`;
        box.dataset.loaded = '1';
        return;
      }

      // render children list (each link uses article-title + data-uuid to reuse modal)
      box.innerHTML = `
        <div class="cluster-children-list">
          ${items.map(it => `
            <div class="cluster-child-item">
              <a href="${it.href}" class="article-title cluster-child-title" data-uuid="${escapeHTML(it.uuid)}">
                ${escapeHTML(it.title)}
              </a>
            </div>
          `).join('')}
        </div>
      `;
      box.dataset.loaded = '1';
    } catch (err) {
      console.error(err);
      box.innerHTML = `<div style="color:#c00;">Load members failed: ${escapeHTML(String(err))}</div>`;
    }
  });

  if (refreshBtn) refreshBtn.addEventListener('click', loadClusters);
  if (sortSelect) sortSelect.addEventListener('change', loadClusters);

  loadClusters();

  // ----------------------------
  // 复用你现有的 Article Detail Modal 管理器（直接拷贝）
  // ----------------------------
  (function initArticleDetailModal() {
    const overlay = document.getElementById('article-detail-overlay');
    const bodyEl = document.getElementById('article-modal-body');
    const titleEl = document.getElementById('article-modal-title');
    const uuidEl = document.getElementById('article-modal-uuid');
    const closeBtn = document.getElementById('article-close-btn');
    const copyBtn = document.getElementById('article-copy-link-btn');
    const openNewBtn = document.getElementById('article-open-newtab-btn');

    if (!overlay || !bodyEl || !titleEl || !uuidEl || !closeBtn || !copyBtn || !openNewBtn) return;

    let lastFocus = null;
    let isOpen = false;
    let pushedState = false;

    async function openByUuid(uuid) {
      const pageUrl = `/intelligence/${encodeURIComponent(uuid)}`;
      await open(pageUrl, uuid, 'Detail');
    }

    async function open(pageUrl, uuid, titleFallback) {
      overlay.style.display = 'flex';
      overlay.setAttribute('aria-hidden', 'false');
      document.body.classList.add('body-scroll-locked');
      titleEl.textContent = 'Loading...';
      uuidEl.textContent = uuid ? `UUID: ${uuid}` : '';
      bodyEl.innerHTML = `<div class="article-modal-loading"><i class="bi bi-arrow-repeat article-spinner"></i> Loading...</div>`;
      openNewBtn.onclick = () => window.open(pageUrl, '_blank', 'noopener');

      lastFocus = document.activeElement;
      closeBtn.focus();

      if (location.pathname !== pageUrl) {
        history.pushState({ modal: 'article', url: pageUrl }, '', pageUrl);
        pushedState = true;
      }
      isOpen = true;

      try {
        const resp = await fetch(`/api/intelligence/${encodeURIComponent(uuid)}`);
        if (resp.status === 401) {
          bodyEl.innerHTML = `<div style="color:#c00;">You are not authorized.</div>`;
          return;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const payload = await resp.json();
        const article = payload?.data || payload;

        titleEl.textContent = article?.EVENT_TITLE || titleFallback || 'Detail';
        bodyEl.innerHTML = ArticleDetailRenderer.generateHTML(article);
        ArticleDetailRenderer.bindEvents(bodyEl, uuid, 'article-toast-container');

        bodyEl.querySelectorAll('a[href^="/intelligence/"]').forEach(a => {
          a.addEventListener('click', (e) => {
            if (a.target === '_blank' || e.button !== 0 || e.metaKey || e.ctrlKey) return;
            e.preventDefault();
            const nextUuid = (a.href.match(/\/intelligence\/([^/?#]+)/i) || [,''])[1];
            if (nextUuid) openByUuid(nextUuid);
          });
        });

        copyBtn.onclick = async () => {
          try {
            await navigator.clipboard.writeText(location.origin + pageUrl);
            ArticleDetailRenderer.showToast('article-toast-container', 'Link copied!', 'success');
          } catch {
            ArticleDetailRenderer.showToast('article-toast-container', 'Copy failed', 'danger');
          }
        };
      } catch (err) {
        titleEl.textContent = 'Load Failed';
        bodyEl.innerHTML = `<div style="color:#c00;">Failed to load: ${String(err)}</div>`;
      }
    }

    function close({ fromHistory } = { fromHistory: false }) {
      if (!isOpen) return;
      overlay.style.display = 'none';
      overlay.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('body-scroll-locked');
      bodyEl.innerHTML = '';
      isOpen = false;

      if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();

      if (!fromHistory && pushedState) {
        window._preventListReload = true;
        history.back();
      }
      pushedState = false;
    }

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    closeBtn.addEventListener('click', () => close());
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && isOpen) close(); });

    document.addEventListener('click', async (e) => {
      const a = e.target.closest('a.article-title[data-uuid]');
      if (!a) return;
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      const uuid = a.dataset.uuid;
      if (uuid) await open(`/intelligence/${uuid}`, uuid, a.textContent?.trim() || 'Detail');
    });

    window.addEventListener('popstate', () => {
      if (isOpen) {
        window._preventListReload = true;
        close({ fromHistory: true });
      }
    });
  })();
});