(() => {
  const docs = window.TVH_DOCS;
  if (!docs) return;

  const storageKey = 'tvh-language';
  const pageId = document.documentElement.dataset.docPage || 'home';
  const shell = document.querySelector('[data-doc-shell]');
  const getLanguage = () => {
    try { return localStorage.getItem(storageKey) === 'en' ? 'en' : 'zh-CN'; }
    catch { return 'zh-CN'; }
  };
  let language = getLanguage();
  const languageIndex = () => language === 'en' ? 1 : 0;
  const value = (pair) => Array.isArray(pair) ? pair[languageIndex()] : pair;

  const labels = {
    'zh-CN': {
      home: '官网首页', search: '搜索文档', searchPlaceholder: '搜索安装、参数、GPU、输出格式…',
      menu: '目录', close: '关闭', sections: '文档板块', onPage: '本页内容', version: '当前版本',
      previous: '上一篇', next: '下一篇', noResults: '没有找到相关文档', copy: '复制', copied: '已复制',
      github: 'GitHub 仓库', release: '下载 v0.1.3', language: 'English', footer: '官方文档 · 本地视频处理 · 源视频只读',
    },
    en: {
      home: 'Product Home', search: 'Search docs', searchPlaceholder: 'Search installation, settings, GPU, outputs…',
      menu: 'Menu', close: 'Close', sections: 'Documentation', onPage: 'On this page', version: 'Current version',
      previous: 'Previous', next: 'Next', noResults: 'No matching documentation', copy: 'Copy', copied: 'Copied',
      github: 'GitHub Repository', release: 'Download v0.1.3', language: '简体中文', footer: 'Official docs · Local video processing · Read-only source videos',
    },
  };
  const t = (key) => labels[language][key];

  const page = docs.pages.find((item) => item.id === pageId) || docs.pages[0];
  const content = docs.content[page.id] || docs.content.home;
  const pageIndex = docs.pages.findIndex((item) => item.id === page.id);

  const applySavedTheme = () => {
    let mode = 'system';
    try { mode = localStorage.getItem('tvh-color-mode') || 'system'; } catch { /* use system */ }
    if (!['system', 'light', 'dark'].includes(mode)) mode = 'system';
    const prefersDark = matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.dataset.docsTheme = mode === 'system' ? (prefersDark ? 'dark' : 'light') : mode;
  };

  const escapeHtml = (text) => String(text).replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[character]);

  const sidebarItems = docs.pages.map((item) => `
    <a class="docs-nav-link${item.id === page.id ? ' is-active' : ''}" href="${item.href}"${item.id === page.id ? ' aria-current="page"' : ''}>
      <span>${item.number}</span><strong>${escapeHtml(value(item.short))}</strong>
    </a>`).join('');

  shell.innerHTML = `
    <header class="docs-header">
      <a class="docs-brand" href="index.html" aria-label="Tennis Video Helper Docs">
        <img src="../assets/images/tennis-video-helper/app-icon.png" width="40" height="40" alt="">
        <span><strong>TENNIS VIDEO HELPER</strong><small>DOCS / v${docs.version}</small></span>
      </a>
      <div class="docs-header-actions">
        <button class="docs-search-trigger" type="button" data-doc-search-open><span>⌕</span><strong>${t('search')}</strong><kbd>Ctrl K</kbd></button>
        <button class="docs-language" type="button" data-doc-language>${t('language')}</button>
        <a class="docs-product-link" href="../index.html">${t('home')} ↗</a>
        <button class="docs-menu-trigger" type="button" data-doc-menu aria-expanded="false" aria-controls="docs-sidebar">${t('menu')}</button>
      </div>
    </header>
    <div class="docs-layout">
      <aside class="docs-sidebar" id="docs-sidebar" data-doc-sidebar>
        <div class="docs-sidebar-head"><span>${t('sections')}</span><button type="button" data-doc-menu-close aria-label="${t('close')}">×</button></div>
        <nav class="docs-sidebar-nav" aria-label="${t('sections')}">${sidebarItems}</nav>
        <div class="docs-sidebar-meta"><span>${t('version')}</span><strong>v${docs.version}</strong><a href="https://github.com/Lijinzh/TennisVideoHelper/releases/tag/v${docs.version}">${t('release')} →</a></div>
      </aside>
      <div class="docs-sidebar-backdrop" data-doc-sidebar-backdrop hidden></div>
      <main class="docs-main" id="docs-main">
        <article class="docs-article">
          <header class="docs-hero"><p>${escapeHtml(value(content.eyebrow))}</p><h1>${escapeHtml(value(content.title))}</h1><div>${escapeHtml(value(content.lede))}</div></header>
          <div class="docs-article-body" data-doc-body>${value(content.html)}</div>
          <nav class="docs-pagination" aria-label="Documentation pagination">
            ${pageIndex > 0 ? `<a href="${docs.pages[pageIndex - 1].href}"><span>← ${t('previous')}</span><strong>${escapeHtml(value(docs.pages[pageIndex - 1].title))}</strong></a>` : '<span></span>'}
            ${pageIndex < docs.pages.length - 1 ? `<a href="${docs.pages[pageIndex + 1].href}"><span>${t('next')} →</span><strong>${escapeHtml(value(docs.pages[pageIndex + 1].title))}</strong></a>` : '<span></span>'}
          </nav>
        </article>
        <aside class="docs-toc"><strong>${t('onPage')}</strong><nav data-doc-toc></nav></aside>
      </main>
    </div>
    <footer class="docs-footer"><span>${t('footer')}</span><nav><a href="https://github.com/Lijinzh/TennisVideoHelper">${t('github')}</a><a href="../index.html#feedback">Feedback</a></nav></footer>
    <dialog class="docs-search-dialog" data-doc-search-dialog aria-label="${t('search')}">
      <form method="dialog" class="docs-search-box"><div><span>⌕</span><input type="search" data-doc-search-input placeholder="${t('searchPlaceholder')}" autocomplete="off"><button value="cancel" aria-label="${t('close')}">Esc</button></div><div class="docs-search-results" data-doc-search-results></div></form>
    </dialog>`;

  document.documentElement.lang = language;
  document.title = `${value(page.title)} · Tennis Video Helper Docs`;
  applySavedTheme();

  const body = shell.querySelector('[data-doc-body]');
  const headings = [...body.querySelectorAll('h2[id], section[id] > h2')];
  headings.forEach((heading) => {
    if (!heading.id) heading.id = heading.closest('section')?.id || '';
    if (!heading.id) return;
    const anchor = document.createElement('a');
    anchor.className = 'docs-heading-anchor';
    anchor.href = `#${heading.id}`;
    anchor.setAttribute('aria-label', language === 'en' ? 'Link to this section' : '链接到本节');
    anchor.textContent = '#';
    heading.append(anchor);
  });

  const toc = shell.querySelector('[data-doc-toc]');
  toc.innerHTML = headings.filter((heading) => heading.id).map((heading) => {
    const label = heading.childNodes[0]?.textContent?.trim() || heading.textContent.trim();
    return `<a href="#${heading.id}">${escapeHtml(label)}</a>`;
  }).join('');

  body.querySelectorAll('pre').forEach((pre) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'docs-copy';
    button.textContent = t('copy');
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(pre.querySelector('code')?.textContent || pre.textContent);
        button.textContent = t('copied');
        setTimeout(() => { button.textContent = t('copy'); }, 1400);
      } catch { button.textContent = t('copy'); }
    });
    pre.append(button);
  });

  const sidebar = shell.querySelector('[data-doc-sidebar]');
  const backdrop = shell.querySelector('[data-doc-sidebar-backdrop]');
  const menuButton = shell.querySelector('[data-doc-menu]');
  const setMenu = (open) => {
    sidebar.classList.toggle('is-open', open);
    backdrop.hidden = !open;
    menuButton.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('docs-menu-open', open);
  };
  menuButton.addEventListener('click', () => setMenu(!sidebar.classList.contains('is-open')));
  shell.querySelector('[data-doc-menu-close]').addEventListener('click', () => setMenu(false));
  backdrop.addEventListener('click', () => setMenu(false));

  shell.querySelector('[data-doc-language]').addEventListener('click', () => {
    language = language === 'en' ? 'zh-CN' : 'en';
    try { localStorage.setItem(storageKey, language === 'en' ? 'en' : 'zh-CN'); } catch { /* render anyway */ }
    location.reload();
  });

  const dialog = shell.querySelector('[data-doc-search-dialog]');
  const input = shell.querySelector('[data-doc-search-input]');
  const results = shell.querySelector('[data-doc-search-results]');
  const searchable = docs.pages.map((item) => {
    const pageContent = docs.content[item.id];
    const container = document.createElement('div');
    container.innerHTML = `${pageContent?.html?.[languageIndex()] || ''}`;
    return { item, text: `${value(item.title)} ${container.textContent}`.replace(/\s+/g, ' ').trim() };
  });
  const renderSearch = (query = '') => {
    const normalized = query.trim().toLocaleLowerCase(language);
    const matches = searchable.filter(({ text }) => !normalized || text.toLocaleLowerCase(language).includes(normalized)).slice(0, 8);
    results.innerHTML = matches.length ? matches.map(({ item, text }) => {
      const source = text.replace(value(item.title), '').trim();
      const lower = source.toLocaleLowerCase(language);
      const position = normalized ? Math.max(0, lower.indexOf(normalized) - 55) : 0;
      const excerpt = `${position > 0 ? '…' : ''}${source.slice(position, position + 150)}${source.length > position + 150 ? '…' : ''}`;
      return `<a href="${item.href}"><span>${item.number}</span><div><strong>${escapeHtml(value(item.title))}</strong><p>${escapeHtml(excerpt)}</p></div></a>`;
    }).join('') : `<p class="docs-search-empty">${t('noResults')}</p>`;
  };
  const openSearch = () => { renderSearch(); dialog.showModal(); requestAnimationFrame(() => input.focus()); };
  shell.querySelector('[data-doc-search-open]').addEventListener('click', openSearch);
  input.addEventListener('input', () => renderSearch(input.value));
  dialog.addEventListener('close', () => { input.value = ''; });
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch(); }
    if (event.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) { event.preventDefault(); openSearch(); }
    if (event.key === 'Escape') setMenu(false);
  });

  if ('IntersectionObserver' in window && headings.length) {
    const tocLinks = new Map([...toc.querySelectorAll('a')].map((link) => [link.hash.slice(1), link]));
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (!visible) return;
      tocLinks.forEach((link, id) => link.classList.toggle('is-active', id === visible.target.id));
    }, { rootMargin: '-15% 0px -70% 0px' });
    headings.forEach((heading) => observer.observe(heading));
  }
})();
