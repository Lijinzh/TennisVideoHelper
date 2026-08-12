(() => {
  const release = {
    version: '0.1.2',
    filename: 'TennisVideoHelper-Setup-0.1.2.exe',
    size: '220.4 MiB',
    sha256: '2D77CA3175F8D7090D515FBB25C024289C378F057574EB99842BA6E38E00B58D',
    url: 'https://github.com/Lijinzh/TennisVideoHelper/releases/download/v0.1.2/TennisVideoHelper-Setup-0.1.2.exe',
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

  const root = document.documentElement;
  const themeColorMeta = document.querySelector('meta[name="theme-color"]');
  const themeOpenButton = document.querySelector('[data-theme-open]');
  const themeCloseButton = document.querySelector('[data-theme-close]');
  const themePanel = document.querySelector('[data-theme-panel]');
  const modeButtons = [...document.querySelectorAll('button[data-color-mode]')];
  const paletteSelect = document.querySelector('select[data-theme-palette-select]');
  const themeStatus = document.querySelector('[data-theme-status]');
  const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
  const storageKeys = {
    mode: 'tvh-color-mode',
    palette: 'tvh-palette-choice',
    court: 'tvh-active-court',
  };
  const validModes = new Set(['system', 'light', 'dark']);
  const paletteLabels = {
    default: '默认像素配色',
    follow: '跟随当前球场',
    loess: '陕北黄土',
    clay: '法网红土',
    grass: '温网草地',
    night: '美网夜场',
    australia: '澳网蓝场',
    shanghai: '上海大师赛',
    beijing: '北京钻石',
    madrid: '马德里魔力盒',
    rio: '里约红土',
    'desert-hard': '印第安维尔斯',
    dunhuang: '敦煌月泉',
    himalaya: '喜马拉雅',
    larung: '喇荣山谷',
    hyrule: '海拉鲁式旷野',
    ashina: '苇名式山城',
  };
  const validPalettes = new Set(Object.keys(paletteLabels));
  const modeLabels = { system: '跟随系统', light: '浅色模式', dark: '深色模式' };

  const readStorage = (key, fallback) => {
    try {
      return localStorage.getItem(key) || fallback;
    } catch {
      return fallback;
    }
  };

  const writeStorage = (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Theme switching still works when storage is unavailable.
    }
  };

  let colorMode = readStorage(storageKeys.mode, root.dataset.colorMode || 'system');
  let paletteChoice = readStorage(storageKeys.palette, root.dataset.paletteChoice || 'default');
  let activeCourtTheme = readStorage(storageKeys.court, 'loess');
  if (!validModes.has(colorMode)) colorMode = 'system';
  if (!validPalettes.has(paletteChoice)) paletteChoice = 'default';
  if (!validPalettes.has(activeCourtTheme) || activeCourtTheme === 'default' || activeCourtTheme === 'follow') activeCourtTheme = 'loess';

  const updateThemeStatus = () => {
    if (!themeStatus) return;
    const resolvedMode = colorMode === 'system' ? (systemTheme.matches ? '深色' : '浅色') : '';
    const paletteLabel = paletteChoice === 'follow' ? `跟随球场：${paletteLabels[activeCourtTheme]}` : paletteLabels[paletteChoice];
    themeStatus.textContent = `${modeLabels[colorMode]}${resolvedMode ? `（当前${resolvedMode}）` : ''} · ${paletteLabel}`;
  };

  const applyTheme = () => {
    const resolvedTheme = colorMode === 'system' ? (systemTheme.matches ? 'dark' : 'light') : colorMode;
    const sitePalette = paletteChoice === 'follow' ? activeCourtTheme : paletteChoice;
    root.dataset.colorMode = colorMode;
    root.dataset.resolvedTheme = resolvedTheme;
    root.dataset.paletteChoice = paletteChoice;
    root.dataset.sitePalette = sitePalette;
    root.style.colorScheme = resolvedTheme;
    modeButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.colorMode === colorMode));
    });
    if (paletteSelect) paletteSelect.value = paletteChoice;
    if (themeColorMeta) {
      const backgroundColor = getComputedStyle(document.body).backgroundColor;
      themeColorMeta.content = backgroundColor || (resolvedTheme === 'dark' ? '#11161d' : '#f4ead4');
    }
    updateThemeStatus();
  };

  const openThemePanel = () => {
    if (!themePanel || !themeOpenButton) return;
    themePanel.hidden = false;
    themeOpenButton.setAttribute('aria-expanded', 'true');
    themePanel.querySelector('button[aria-pressed="true"], select, button')?.focus();
  };

  const closeThemePanel = (restoreFocus = true) => {
    if (!themePanel || !themeOpenButton) return;
    themePanel.hidden = true;
    themeOpenButton.setAttribute('aria-expanded', 'false');
    if (restoreFocus) themeOpenButton.focus();
  };

  themeOpenButton?.addEventListener('click', () => {
    if (themePanel?.hidden) openThemePanel();
    else closeThemePanel();
  });
  themeCloseButton?.addEventListener('click', () => closeThemePanel());
  modeButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const nextMode = button.dataset.colorMode;
      if (!validModes.has(nextMode)) return;
      colorMode = nextMode;
      writeStorage(storageKeys.mode, colorMode);
      applyTheme();
    });
  });
  paletteSelect?.addEventListener('change', () => {
    const nextPalette = paletteSelect.value;
    if (!validPalettes.has(nextPalette)) return;
    paletteChoice = nextPalette;
    writeStorage(storageKeys.palette, paletteChoice);
    applyTheme();
  });
  systemTheme.addEventListener?.('change', () => {
    if (colorMode === 'system') applyTheme();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && themePanel && !themePanel.hidden) closeThemePanel();
  });
  document.addEventListener('click', (event) => {
    if (!themePanel || themePanel.hidden || !themeOpenButton) return;
    if (themePanel.contains(event.target) || themeOpenButton.contains(event.target)) return;
    closeThemePanel(false);
  });
  applyTheme();

  const courtGallery = document.querySelector('[data-court-gallery]');
  if (courtGallery) {
    const viewport = courtGallery.querySelector('[data-court-viewport]');
    const slides = [...courtGallery.querySelectorAll('[data-court-slide]')];
    const tabs = [...courtGallery.querySelectorAll('[data-court-tab]')];
    const previousButton = courtGallery.querySelector('[data-court-previous]');
    const nextButton = courtGallery.querySelector('[data-court-next]');
    const position = courtGallery.querySelector('[data-court-position]');
    let activeIndex = 0;
    let scrollFrame = 0;

    const setActiveCourt = (index, shouldScroll = false) => {
      activeIndex = (index + slides.length) % slides.length;
      slides.forEach((slide, slideIndex) => {
        slide.classList.toggle('is-active', slideIndex === activeIndex);
      });
      tabs.forEach((tab, tabIndex) => {
        tab.setAttribute('aria-selected', String(tabIndex === activeIndex));
        tab.tabIndex = tabIndex === activeIndex ? 0 : -1;
      });
      if (position) {
        position.textContent = `${String(activeIndex + 1).padStart(2, '0')} / ${String(slides.length).padStart(2, '0')}`;
      }
      activeCourtTheme = slides[activeIndex].dataset.courtTheme || 'loess';
      writeStorage(storageKeys.court, activeCourtTheme);
      if (paletteChoice === 'follow') applyTheme();
      if (shouldScroll && viewport) {
        const slide = slides[activeIndex];
        const left = slide.offsetLeft - (viewport.clientWidth - slide.clientWidth) / 2;
        viewport.scrollTo({ left, behavior: 'smooth' });
      }
    };

    const updateFromScroll = () => {
      cancelAnimationFrame(scrollFrame);
      scrollFrame = requestAnimationFrame(() => {
        if (!viewport) return;
        const center = viewport.getBoundingClientRect().left + viewport.clientWidth / 2;
        const distances = slides.map((slide) => {
          const rect = slide.getBoundingClientRect();
          return Math.abs(rect.left + rect.width / 2 - center);
        });
        const closestIndex = distances.indexOf(Math.min(...distances));
        if (closestIndex !== activeIndex) setActiveCourt(closestIndex);
      });
    };

    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => setActiveCourt(index, true));
      tab.addEventListener('keydown', (event) => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        const direction = event.key === 'ArrowRight' ? 1 : -1;
        const nextIndex = (index + direction + tabs.length) % tabs.length;
        tabs[nextIndex].focus();
        setActiveCourt(nextIndex, true);
      });
    });
    previousButton?.addEventListener('click', () => setActiveCourt(activeIndex - 1, true));
    nextButton?.addEventListener('click', () => setActiveCourt(activeIndex + 1, true));
    viewport?.addEventListener('scroll', updateFromScroll, { passive: true });
    viewport?.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      setActiveCourt(activeIndex + (event.key === 'ArrowRight' ? 1 : -1), true);
    });
    const savedCourtIndex = slides.findIndex((slide) => slide.dataset.courtTheme === activeCourtTheme);
    setActiveCourt(savedCourtIndex >= 0 ? savedCourtIndex : 0);
  }

  const architectureMap = document.querySelector('[data-architecture-map]');
  if (architectureMap) {
    const architectureNodes = [...architectureMap.querySelectorAll('[data-architecture-node]')];
    const architectureDetail = architectureMap.querySelector('[data-architecture-detail]');
    const architectureContent = {
      audio: {
        index: '01 / AUDIO',
        title: '声音候选：用低成本扫描缩小搜索范围',
        copy: '提取音轨后寻找类似击球的瞬态峰值。邻场击球、脚步声和孤立噪声即使进入候选，也不能单独被判定为真实击球。',
        files: 'src/tennis_video_helper/detection/audio.py',
        contribution: '噪声过滤、击球声特征、不同球场录音回归',
        tests: 'tests/detection/',
      },
      vision: {
        index: '02 / VISION',
        title: '视觉确认：判断画面里是否真的发生挥拍',
        copy: '视觉分析跟踪近端球员的骨架、手臂运动和身体姿态，再用球拍证据过滤走路持拍、低头捡球、站着讲话以及普通摆臂。',
        files: 'src/tennis_video_helper/detection/vision/',
        contribution: '骨架时序、球拍检测、左右手与不同机位适配',
        tests: 'tests/detection/vision/',
      },
      fusion: {
        index: '03 / FUSION',
        title: '音画融合：只有对齐的证据才能组成击球与回合',
        copy: '声音和视觉事件按时间对齐并计算可信度。状态机会应用最少击球数、最短回合、前后保留时间和结束静默等规则，避免一次孤立动作形成完整片段。',
        files: 'src/tennis_video_helper/detection/fusion.py',
        contribution: '融合阈值、回合边界、误检与漏检回归',
        tests: 'tests/detection/test_fusion.py',
      },
      review: {
        index: '04 / REVIEW',
        title: '人工复核：模型提出候选，用户拥有最终决定权',
        copy: '管线先在隐藏临时目录生成经过媒体验证的候选。GUI 读取复核清单，播放每段视频、显示击球时间线，并记录用户勾选结果。',
        files: 'src/tennis_video_helper/review/ + ui/',
        contribution: '候选清单、播放器交互、时间线与可访问性',
        tests: 'tests/review/ + tests/ui/',
      },
      publish: {
        index: '05 / EXPORT',
        title: '安全发布：先完整生成和验证，再替换旧结果',
        copy: '导出层按照 1080p 或原画质策略调用 FFmpeg / NVENC。新片段、报告和目录全部验证成功后，publication 模块才会替换同名旧结果；失败或停止时保留旧文件。',
        files: 'src/tennis_video_helper/media/exporter.py + publication.py',
        contribution: '编码兼容、HDR/音频格式、验证与 Windows 文件锁',
        tests: 'tests/media/ + tests/app/test_pipeline.py',
      },
    };

    const updateArchitectureDetail = (key) => {
      const content = architectureContent[key];
      if (!content || !architectureDetail) return;
      architectureNodes.forEach((node) => {
        const isActive = node.dataset.architectureNode === key;
        node.classList.toggle('is-active', isActive);
        node.setAttribute('aria-pressed', String(isActive));
      });
      architectureDetail.querySelector('[data-architecture-index]').textContent = content.index;
      architectureDetail.querySelector('[data-architecture-title]').textContent = content.title;
      architectureDetail.querySelector('[data-architecture-copy]').textContent = content.copy;
      architectureDetail.querySelector('[data-architecture-files]').innerHTML = `<code>${content.files}</code>`;
      architectureDetail.querySelector('[data-architecture-contribution]').textContent = content.contribution;
      architectureDetail.querySelector('[data-architecture-tests]').innerHTML = `<code>${content.tests}</code>`;
    };

    architectureNodes.forEach((node) => {
      node.addEventListener('click', () => updateArchitectureDetail(node.dataset.architectureNode));
    });
    updateArchitectureDetail('audio');
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
  const feedbackFallback = document.querySelector('[data-feedback-fallback]');

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
    const environment = String(values.get('environment') || 'Windows 版本不确定').trim();
    const gpu = String(values.get('gpu') || '').trim() || '未填写';
    const videoSpec = String(values.get('videoSpec') || '').trim() || '未填写';
    const body = [
      '## 反馈类型',
      category,
      '',
      '## 问题或建议',
      details,
      '',
      '## 使用环境',
      `- 操作系统：${environment}`,
      `- 显卡：${gpu}`,
      `- 视频规格：${videoSpec}`,
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
    const validateFeedback = () => {
      if (feedbackForm.checkValidity()) return true;
      feedbackStatus.textContent = '请先填写一句话标题和详细说明，并勾选公开信息确认。';
      feedbackForm.reportValidity();
      return false;
    };

    feedbackForm.addEventListener('submit', (event) => {
      event.preventDefault();
      if (!validateFeedback()) return;
      const prepared = buildFeedback();
      if (!prepared) return;
      if (feedbackFallback) {
        feedbackFallback.href = prepared.issueUrl;
        feedbackFallback.hidden = false;
      }
      feedbackStatus.textContent = 'GitHub 提交页已尝试在新标签页打开。如果没有看到新页面，请点击下方备用链接。';
      feedbackFallback?.click();
    });

    const feedbackCopyButton = document.querySelector('[data-feedback-copy]');
    feedbackCopyButton?.addEventListener('click', async () => {
      if (!validateFeedback()) return;
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
