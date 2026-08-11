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
})();
