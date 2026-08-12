(() => {
  const repositoryUrl = 'https://github.com/Lijinzh/TennisVideoHelper';
  const repositoryApiUrl = 'https://api.github.com/repos/Lijinzh/TennisVideoHelper';
  const publishedStarSnapshot = 0;

  const signalStrip = document.querySelector('.tennis-signal-strip');
  if (!signalStrip || document.querySelector('#star')) return;

  const section = document.createElement('section');
  section.className = 'tennis-star-section';
  section.id = 'star';
  section.setAttribute('aria-labelledby', 'star-title');
  section.innerHTML = `
    <div class="tennis-star-section__copy">
      <p class="tennis-kicker"><span>PLAYER SUPPORT</span> 给独立项目一点助力</p>
      <h2 id="star-title">喜欢 Tennis Video Helper？点亮一个 Star。</h2>
      <p>Star 能让更多网球爱好者找到这个工具。按钮会打开 GitHub 的项目页面；登录后点击右上角 Star 即可，本站不会索取或保存你的 GitHub Token。</p>
    </div>
    <div class="tennis-star-card">
      <div class="tennis-star-card__score">
        <span class="tennis-star-card__icon" aria-hidden="true">★</span>
        <div><span>CURRENT STARS</span><strong data-github-star-count aria-label="当前 Star 数量">${publishedStarSnapshot}</strong></div>
      </div>
      <a class="tennis-star-card__button" href="${repositoryUrl}" target="_blank" rel="noopener noreferrer" data-github-star-link>前往 GitHub 确认 Star ↗</a>
      <p class="tennis-star-card__status" role="status" aria-live="polite" data-github-star-status>正在读取 GitHub 的公开 Star 数量…</p>
    </div>`;
  signalStrip.insertAdjacentElement('afterend', section);

  const nav = document.querySelector('[data-pixel-nav]');
  const feedbackLink = nav?.querySelector('a[href="#feedback"]');
  if (nav && !nav.querySelector('a[href="#star"]')) {
    const starNavLink = document.createElement('a');
    starNavLink.href = '#star';
    starNavLink.textContent = 'Star';
    nav.insertBefore(starNavLink, feedbackLink || null);
  }

  const count = section.querySelector('[data-github-star-count]');
  const status = section.querySelector('[data-github-star-status]');
  const link = section.querySelector('[data-github-star-link]');

  const refreshStarCount = async () => {
    try {
      const response = await fetch(repositoryApiUrl, {
        headers: { Accept: 'application/vnd.github+json' },
        cache: 'no-store',
      });
      if (!response.ok) throw new Error(`GitHub API ${response.status}`);
      const repository = await response.json();
      const stars = Number(repository.stargazers_count);
      if (!Number.isFinite(stars)) throw new Error('Missing stargazers_count');
      count.textContent = new Intl.NumberFormat('zh-CN').format(stars);
      status.textContent = '数量来自 GitHub 官方公开 API。登录 GitHub 后即可确认 Star。';
    } catch (error) {
      count.textContent = new Intl.NumberFormat('zh-CN').format(publishedStarSnapshot);
      status.textContent = 'GitHub 匿名 API 暂时限流，当前显示网站发布时的数量快照；按钮仍可正常使用。';
    }
  };

  link.addEventListener('click', () => {
    status.textContent = 'GitHub 已在新标签页打开。完成 Star 后返回这里，数量会自动刷新。';
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refreshStarCount();
  });

  refreshStarCount();
})();
