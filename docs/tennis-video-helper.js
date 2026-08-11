(() => {
  const release = {
    version: '0.1.0',
    filename: 'TennisVideoHelper-Setup-0.1.0.exe',
    size: '156.2 MiB',
    sha256: '1D5101A6F1341D1AF6BAEC17A15FBBB68A94895EB0E1F2ABEF40FAD85D255B37',
    url: 'https://github.com/Lijinzh/TennisVideoHelper/releases/download/v0.1.0/TennisVideoHelper-Setup-0.1.0.exe',
  };

  for (const link of document.querySelectorAll('[data-tv-download]')) {
    link.href = release.url;
    link.setAttribute('download', release.filename);
  }

  const downloadStatus = document.querySelector('[data-download-status]');
  if (downloadStatus) {
    const isWindows = /Windows/i.test(navigator.userAgent || navigator.platform || '');
    downloadStatus.querySelector('span').textContent = `v${release.version}`;
    downloadStatus.querySelector('strong').textContent = release.size;
    if (!isWindows) {
      downloadStatus.querySelector('small').textContent = '检测到当前可能不是 Windows；安装包仅支持 Windows 10 / 11 x64。';
    }
  }

  const copyButton = document.querySelector('[data-copy-sha]');
  const copyStatus = document.querySelector('[data-copy-status]');
  if (copyButton && copyStatus) {
    copyButton.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(release.sha256);
        copyButton.textContent = '已复制';
        copyStatus.textContent = 'SHA-256 已复制到剪贴板。';
      } catch {
        copyStatus.textContent = `复制失败，请手动选择：${release.sha256}`;
      }
    });
  }

  const feedback = {
    issueUrl: 'https://github.com/Lijinzh/TennisVideoHelper/issues/new',
    label: 'user feedback',
  };
  const feedbackDialog = document.querySelector('[data-feedback-dialog]');
  const feedbackForm = document.querySelector('[data-feedback-form]');
  const feedbackStatus = document.querySelector('[data-feedback-status]');
  const feedbackDetails = document.querySelector('[data-feedback-details]');
  const feedbackCount = document.querySelector('[data-feedback-count]');

  const openFeedback = () => {
    if (!feedbackDialog) return;
    if (typeof feedbackDialog.showModal === 'function') feedbackDialog.showModal();
    else feedbackDialog.setAttribute('open', '');
  };

  const closeFeedback = () => {
    if (!feedbackDialog) return;
    if (typeof feedbackDialog.close === 'function') feedbackDialog.close();
    else feedbackDialog.removeAttribute('open');
  };

  const buildFeedback = () => {
    if (!feedbackForm) return null;
    const values = new FormData(feedbackForm);
    const category = String(values.get('category') || '其他反馈').trim();
    const version = String(values.get('version') || '不确定').trim();
    const summary = String(values.get('summary') || '').trim();
    const details = String(values.get('details') || '').trim();
    const environment = String(values.get('environment') || '').trim() || '未填写';
    const body = [
      '## 反馈类型',
      category,
      '',
      '## 问题或建议',
      details,
      '',
      '## 使用环境',
      environment,
      '',
      '## 软件版本',
      version,
      '',
      '---',
      '由 Tennis Video Helper 官网反馈窗口整理。',
    ].join('\n');
    const issueUrl = new URL(feedback.issueUrl);
    issueUrl.searchParams.set('title', `[${category}] ${summary}`);
    issueUrl.searchParams.set('body', body);
    issueUrl.searchParams.set('labels', feedback.label);
    return { body, issueUrl: issueUrl.toString() };
  };

  for (const button of document.querySelectorAll('[data-feedback-open]')) {
    button.addEventListener('click', openFeedback);
  }
  for (const button of document.querySelectorAll('[data-feedback-close]')) {
    button.addEventListener('click', closeFeedback);
  }

  if (feedbackDialog) {
    feedbackDialog.addEventListener('click', (event) => {
      if (event.target === feedbackDialog) closeFeedback();
    });
  }

  if (feedbackDetails && feedbackCount) {
    const updateCount = () => { feedbackCount.textContent = String(feedbackDetails.value.length); };
    feedbackDetails.addEventListener('input', updateCount);
    updateCount();
  }

  if (feedbackForm && feedbackStatus) {
    feedbackForm.addEventListener('submit', (event) => {
      event.preventDefault();
      if (!feedbackForm.reportValidity()) return;
      const prepared = buildFeedback();
      if (!prepared) return;
      feedbackStatus.textContent = '反馈已整理，正在打开 GitHub 最终确认页。';
      window.location.assign(prepared.issueUrl);
    });

    const feedbackCopyButton = document.querySelector('[data-feedback-copy]');
    feedbackCopyButton?.addEventListener('click', async () => {
      if (!feedbackForm.reportValidity()) return;
      const prepared = buildFeedback();
      if (!prepared) return;
      try {
        await navigator.clipboard.writeText(prepared.body);
        feedbackStatus.textContent = '反馈内容已复制。你可以将它粘贴到聊天、邮件或 GitHub Issue 中。';
      } catch {
        feedbackStatus.textContent = '复制失败，请保持窗口打开并手动选择输入内容。';
      }
    });
  }
})();
