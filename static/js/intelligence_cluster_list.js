document.addEventListener('DOMContentLoaded', () => {
    // 复用 ArticleRenderer 提供的时间高亮和卡片生成能力
    // 这里第二个参数传空，因为聚类页面我们不使用标准的分页条
    const renderer = new ArticleRenderer('article-list-container', '');
    const listContainer = document.getElementById('article-list-container');
    const limitSelect = document.getElementById('limit-select');
    const refreshBtn = document.getElementById('refresh-btn');

    async function loadClusters() {
        const limit = limitSelect ? limitSelect.value : 50;
        renderer.showLoading();

        try {
            const response = await fetch(`/api/clusters/latest?limit=${limit}`);
            if (!response.ok) throw new Error(`API Error: ${response.status}`);

            const data = await response.json();
            const clusters = data.clusters || [];

            if (clusters.length === 0) {
                listContainer.innerHTML = '<p style="text-align:center; padding: 50px;">No Aggregated Clusters Available</p>';
                return;
            }

            // 生成聚类 HTML
            let html = '';
            clusters.forEach(cluster => {
                const doc = cluster.repr_doc;
                // 利用重构后的 generateArticleCardHtml 单独生成代表文章的卡片
                const reprCardHtml = renderer.generateArticleCardHtml(doc);

                // 只有 size > 1 时才显示展开按钮
                const toggleBtn = cluster.size > 1
                    ? `<button class="cluster-toggle-btn" data-cluster-id="${cluster.cluster_id}">
                         <i class="bi bi-chevron-down"></i> Expand (${cluster.size - 1} related)
                       </button>`
                    : '';

                html += `
                <div class="cluster-container" data-cluster-id="${cluster.cluster_id}">
                    <div class="cluster-badge"><i class="bi bi-diagram-3"></i> Cluster ID: ${cluster.cluster_id} • Total: ${cluster.size}</div>
                    <div class="cluster-header">
                        ${toggleBtn}
                        ${reprCardHtml}
                    </div>
                    <div class="cluster-members" id="members-${cluster.cluster_id}">
                        </div>
                </div>`;
            });

            listContainer.innerHTML = html;

            // 触发来源图标渲染和时间颜色更新
            renderer.enhanceSourceLinks();
            renderer.updateTimeBackgrounds();

        } catch (error) {
            console.error('Load Error:', error);
            renderer.showError(error.message);
        }
    }

    // 处理展开/收起事件 (事件委托)
    listContainer.addEventListener('click', async (e) => {
        const btn = e.target.closest('.cluster-toggle-btn');
        if (!btn) return;

        const clusterId = btn.getAttribute('data-cluster-id');
        const membersDiv = document.getElementById(`members-${clusterId}`);
        const icon = btn.querySelector('i');

        // Toggle 逻辑
        if (membersDiv.classList.contains('expanded')) {
            membersDiv.classList.remove('expanded');
            icon.classList.replace('bi-chevron-up', 'bi-chevron-down');
            btn.innerHTML = `<i class="bi bi-chevron-down"></i> Expand`;
            return;
        }

        membersDiv.classList.add('expanded');
        icon.classList.replace('bi-chevron-down', 'bi-chevron-up');
        btn.innerHTML = `<i class="bi bi-chevron-up"></i> Collapse`;

        // 如果已经加载过，直接返回
        if (membersDiv.innerHTML.trim() !== '') return;

        membersDiv.innerHTML = `<div class="loading-spinner"><i class="bi bi-arrow-repeat article-spinner"></i> Loading members...</div>`;

        // 动态加载子成员
        try {
            // 请求上限 500 (如果超出可通过 API 增加 offset 机制，这里简写全拉)
            const resp = await fetch(`/api/clusters/${clusterId}/members?limit=500`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const data = await resp.json();
            const items = data.items || [];

            // 去除代表文章本身（通常是列表第一条，或者依靠 uuid 过滤）
            // 因为代表文章已经在 cluster-header 里显示过了
            const containerEl = btn.closest('.cluster-container');
            const reprUuid = containerEl.querySelector('.article-title').getAttribute('data-uuid');

            const filteredItems = items.filter(item => item.uuid !== reprUuid);

            if (filteredItems.length === 0) {
                membersDiv.innerHTML = '<p style="color:#666; font-size: 0.9em;">No other members in this cluster.</p>';
                return;
            }

            // 渲染子文章
            const membersHtml = filteredItems.map(item => renderer.generateArticleCardHtml(item.doc)).join('');
            membersDiv.innerHTML = membersHtml;

            renderer.enhanceSourceLinks();
            renderer.updateTimeBackgrounds();

        } catch (err) {
            membersDiv.innerHTML = `<div style="color:red;">Error loading members: ${err.message}</div>`;
        }
    });

    if (refreshBtn) refreshBtn.addEventListener('click', loadClusters);
    if (limitSelect) limitSelect.addEventListener('change', loadClusters);

    // 初始加载
    loadClusters();

    // ==========================================
    // 复用原有的 Modal 逻辑，拦截文章点击
    // ==========================================
    (function initArticleDetailModal() {
        const overlay = document.getElementById('article-detail-overlay');
        const bodyEl = document.getElementById('article-modal-body');
        const titleEl = document.getElementById('article-modal-title');
        const uuidEl = document.getElementById('article-modal-uuid');
        const closeBtn = document.getElementById('article-close-btn');
        const copyBtn = document.getElementById('article-copy-link-btn');
        const openNewBtn = document.getElementById('article-open-newtab-btn');

        if (!overlay) return;
        let isOpen = false;

        async function open(pageUrl, uuid, titleFallback) {
            overlay.style.display = 'flex';
            document.body.classList.add('body-scroll-locked');
            titleEl.textContent = 'Loading...';
            uuidEl.textContent = uuid ? `UUID: ${uuid}` : '';
            bodyEl.innerHTML = `<div class="article-modal-loading"><i class="bi bi-arrow-repeat article-spinner"></i> Loading...</div>`;
            openNewBtn.onclick = () => window.open(pageUrl, '_blank', 'noopener');
            isOpen = true;

            try {
                const resp = await fetch(`/api/intelligence/${encodeURIComponent(uuid)}`);
                if (resp.status === 401) {
                    bodyEl.innerHTML = `<div style="color:#c00;">You are not authorized.</div>`;
                    return;
                }
                const payload = await resp.json();
                const article = payload?.data || payload;

                titleEl.textContent = article?.EVENT_TITLE || titleFallback || 'Detail';
                bodyEl.innerHTML = ArticleDetailRenderer.generateHTML(article);
                ArticleDetailRenderer.bindEvents(bodyEl, uuid, 'article-toast-container');

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

        function close() {
            if (!isOpen) return;
            overlay.style.display = 'none';
            document.body.classList.remove('body-scroll-locked');
            bodyEl.innerHTML = '';
            isOpen = false;
        }

        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
        closeBtn.addEventListener('click', () => close());
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && isOpen) close(); });

        document.addEventListener('click', async (e) => {
            const a = e.target.closest('a.article-title[data-uuid]');
            if (!a) return;
            if (e.button !== 0 || e.metaKey || e.ctrlKey) return;
            e.preventDefault();
            const uuid = a.dataset.uuid;
            if (uuid) await open(`/intelligence/${uuid}`, uuid, a.textContent?.trim());
        });
    })();
});
