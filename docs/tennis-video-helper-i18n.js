(() => {
  const storageKey = 'tvh-language';
  const exact = new Map(Object.entries({
    'Tennis Video Helper · 网球回合自动精选': 'Tennis Video Helper · Automatic Rally Selection',
    'Tennis Video Helper：首页': 'Tennis Video Helper Home',
    'Tennis Video Helper 首页': 'Tennis Video Helper Home',
    'Tennis Video Helper：自动识别网球长回合、逐段预览击球点并安全导出精选视频的 Windows 桌面工具。': 'Tennis Video Helper is a Windows desktop app that automatically discovers tennis rallies, lets you review hit points clip by clip, and safely exports selected highlights.',
    '声音、骨架与球拍检测共同确认击球，自动筛选值得保留的网球回合。': 'Audio, pose, and racket detection work together to confirm hits and find rallies worth keeping.',
    '跟随系统 · 跟随球场：陕北黄土': 'System · Follow court: Shaanbei Loess',
    '跳到主要内容': 'Skip to main content',
    '首页': 'Home', '球场': 'Courts', '功能': 'Features', '架构': 'Architecture',
    '设置': 'Settings', '进度': 'Progress', '安装': 'Install', '文档': 'Docs', '完整文档': 'Full Documentation', '反馈': 'Feedback',
    '主题': 'Theme', '页面主题': 'Page Theme', '明暗模式': 'Color Mode',
    '跟随系统': 'System', '浅色': 'Light', '深色': 'Dark',
    '浅色模式': 'Light mode', '深色模式': 'Dark mode',
    '球场背景主题': 'Court Background Theme', '跟随当前球场': 'Follow Current Court',
    '查看项目仓库': 'View Repository',
    '把长视频里的': 'Find the', '精彩回合': 'best rallies', '挑出来': 'in long videos',
    '声音找到候选，人体骨架确认挥拍，球拍检测过滤走路和摆臂。分析完成后，在软件里逐段预览、查看击球点，再勾选导出。': 'Audio finds candidates, pose tracking confirms swings, and racket detection filters walking and casual arm motion. Review each clip and hit point in the app, then select what to export.',
    '下载 Windows 安装包': 'Download for Windows', '查看安装步骤': 'View Installation Steps',
    '内置运行环境、模型与 FFmpeg，无需另装 Python。': 'Includes the runtime, models, and FFmpeg. No separate Python installation required.',
    '最新版安装包从公开 GitHub Release 下载；GitCode 国内镜像仍可用于获取历史版本。': 'The latest installer is downloaded from the public GitHub Release; the GitCode mirror remains available for older versions.',
    '候选列表 / 视频预览 / 击球时间线 / GPU 状态 / 勾选导出': 'Candidate list / Video preview / Hit timeline / GPU status / Selected export',
    'Tennis Video Helper 候选回合预览、击球点时间线与导出界面': 'Tennis Video Helper candidate preview, hit timeline, and export interface',
    '给独立项目一点助力': 'Support an independent project',
    '喜欢 Tennis Video Helper？点亮一个 Star。': 'Like Tennis Video Helper? Give it a Star.',
    'Star 能让更多网球爱好者找到这个工具。按钮会打开 GitHub 的项目页面；登录后点击右上角 Star 即可，本站不会索取或保存你的 GitHub Token。': 'A Star helps more tennis players discover this tool. The button opens the GitHub repository; sign in and select Star. This site never requests or stores your GitHub token.',
    '当前 Star 数量': 'Current Star count', '前往 GitHub 确认 Star ↗': 'Open GitHub and Star the Project ↗',
    '正在读取 GitHub 的公开 Star 数量…': 'Loading the public GitHub Star count…',
    '数量来自 GitHub 官方公开 API。登录 GitHub 后即可确认 Star。': 'The count comes from GitHub’s public API. Sign in to GitHub to Star the project.',
    'GitHub 匿名 API 暂时限流，当前显示网站发布时的数量快照；按钮仍可正常使用。': 'GitHub’s anonymous API is temporarily rate-limited. The published snapshot is shown and the button still works.',
    'GitHub 已在新标签页打开。完成 Star 后返回这里，数量会自动刷新。': 'GitHub opened in a new tab. Return after starring the project and the count will refresh.',
    '音画融合': 'Audio-Visual Fusion', '声音 + 骨架 + 球拍': 'Audio + Pose + Racket',
    '人工复核': 'Human Review', '逐段播放与击球跳转': 'Clip playback and hit navigation',
    'GPU 加速': 'GPU Acceleration', '源视频只读': 'Read-only Source Video',
    '验证成功后再发布结果': 'Publish only after validation',
    '十五座球场，一次横向巡游': 'Fifteen courts in one horizontal tour',
    '切换你的像素球场': 'Choose Your Pixel Court',
    '世界名场与中国风景在这里并肩出现：真实赛事场馆标注为“真实名场”，敦煌、喜马拉雅、喇荣以及游戏灵感球场则明确标注为“概念创作”。点击按钮、箭头或横向滑动即可巡游。': 'Iconic tournament venues sit beside Chinese landscapes. Real venues are labeled accordingly, while Dunhuang, the Himalayas, Larung Valley, and game-inspired courts are clearly marked as concepts. Use the tabs, arrows, or horizontal scrolling to explore.',
    '概念创作': 'Concept', '真实名场': 'Real Venue', '幻想灵感': 'Fantasy-inspired',
    '陕北黄土': 'Shaanbei Loess', '法网红土': 'Roland-Garros Clay',
    '温网草地': 'Wimbledon Grass', '美网夜场': 'US Open Night', '澳网蓝场': 'Australian Open Blue',
    '上海大师赛': 'Shanghai Masters', '北京钻石': 'Beijing Diamond',
    '马德里魔力盒': 'Madrid Caja Mágica', '里约红土': 'Rio Clay',
    '印第安维尔斯': 'Indian Wells', '敦煌月泉': 'Dunhuang Crescent Lake',
    '喜马拉雅': 'Himalayas', '喇荣山谷': 'Larung Valley',
    '海拉鲁式旷野': 'Hyrule-inspired Wilds', '苇名式山城': 'Ashina-inspired Castle',
    '沙漠花园': 'Desert Garden',
    '陕北风黄土球场': 'Shaanbei Loess Court',
    '法网罗兰加洛斯红土球场': 'Roland-Garros Clay Court',
    '美网纽约夜场硬地球场': 'US Open New York Night Court',
    '澳网墨尔本蓝色硬地球场': 'Australian Open Melbourne Blue Court',
    '北京国家网球中心钻石球场': 'Beijing National Tennis Center Diamond Court',
    '马德里魔力盒红土球场': 'Madrid Caja Mágica Clay Court',
    '里约热内卢赛马会红土球场': 'Rio Jockey Club Clay Court',
    '印第安维尔斯沙漠网球花园': 'Indian Wells Tennis Garden',
    '敦煌鸣沙山月牙泉概念网球场': 'Dunhuang Crescent Lake Concept Court',
    '喜马拉雅山脚概念网球场': 'Himalayan Foothills Concept Court',
    '喇荣山谷概念网球场': 'Larung Valley Concept Court',
    '塞尔达传说海拉鲁式旷野灵感概念网球场': 'Hyrule-inspired Open Wilds Concept Court',
    '只狼苇名式山城灵感概念网球场': 'Ashina-inspired Mountain Castle Concept Court',
    '像素风陕北黄土沟壑、窑洞和暖色夕照中的完整网球场': 'Pixel-art tennis court among Shaanbei loess ravines, cave homes, and warm sunset light',
    '像素风巴黎红土网球场、深绿看台和城市天际线': 'Pixel-art Paris clay court with deep-green stands and a city skyline',
    '像素风伦敦草地网球场、常春藤和英伦建筑': 'Pixel-art London grass court with ivy and British architecture',
    '像素风纽约夜间蓝色硬地网球场和城市天际线': 'Pixel-art New York blue hard court at night with a city skyline',
    '像素风墨尔本日间青蓝色硬地网球场和现代开放式场馆': 'Pixel-art Melbourne cyan-blue hard court in a modern open stadium',
    '像素风上海旗忠网球中心玉兰花瓣屋顶和蓝绿硬地球场': 'Pixel-art Shanghai Qizhong Tennis Center with magnolia-petal roof and blue-green court',
    '像素风北京国家网球中心钻石球场和远处鸟巢天际线': 'Pixel-art Beijing Diamond Court with the distant Bird’s Nest skyline',
    '像素风马德里魔力盒红土球场和可开合几何屋顶': 'Pixel-art Madrid Caja Mágica clay court with a retractable geometric roof',
    '像素风里约赛马会红土球场、棕榈与基督像山景': 'Pixel-art Rio clay court with palms and a mountain skyline',
    '像素风印第安维尔斯蓝色硬地、棕榈和沙漠山脉': 'Pixel-art Indian Wells blue hard court with palms and desert mountains',
    '像素风敦煌沙丘、月牙泉和丝路驿亭旁的概念网球场': 'Pixel-art Dunhuang concept court beside dunes, Crescent Lake, and Silk Road pavilions',
    '像素风喜马拉雅雪山脚下高原谷地中的概念网球场': 'Pixel-art concept court in a Himalayan highland valley',
    '像素风川西高原红色山城景观旁的概念网球场': 'Pixel-art concept court beside a red highland settlement in western Sichuan',
    '像素风海拉鲁式开放旷野、浮空遗迹和古代装置中的概念网球场': 'Pixel-art concept court in Hyrule-inspired open wilds with floating ruins',
    '像素风苇名式战国山城、雪峰和朱桥旁的概念网球场': 'Pixel-art concept court beside an Ashina-inspired mountain castle, snow peaks, and vermilion bridge',
    '黄土沟壑、窑洞院落与暖色夕照围住一座完整球场，木围栏和梯田层次让它拥有独一份的陕北气质。': 'Loess ravines, cave homes, terraced land, and warm sunset light surround a complete court with a distinctly Shaanbei character.',
    '黄土沟壑 / 窑洞 / 暖色夕照': 'Loess ravines / Cave homes / Warm sunset',
    '法网·罗兰加洛斯红土': 'Roland-Garros Clay Court',
    '砖红色红土与深绿看台构成经典对比，远处的巴黎城市轮廓把春日大赛气氛收进像素画面。': 'Brick-red clay and deep-green stands create a classic contrast, with the Paris skyline bringing spring tournament atmosphere into the pixel scene.',
    '红土 / 深绿看台 / 巴黎春日': 'Clay / Deep-green stands / Paris spring',
    '巴黎大满贯红土氛围': 'Paris Grand Slam clay atmosphere',
    '温布尔登草地球场': 'Wimbledon Grass Court',
    '清晰的修剪草纹、底线磨损、常春藤与传统英伦建筑，组成安静而庄重的夏日草地赛场。': 'Mown grass stripes, baseline wear, ivy, and traditional British architecture create a quiet, dignified summer court.',
    '草地 / 常春藤 / 英伦夏日': 'Grass / Ivy / British summer',
    '伦敦传统草地氛围': 'Traditional London grass atmosphere',
    '美网纽约夜场硬地': 'US Open New York Night Court',
    '电光蓝硬地、巨型灯架与霓虹城市天际线，让这一站成为整组球场里最鲜明的夜赛场景。': 'Electric-blue hard court, giant light towers, and a neon skyline make this the collection’s most vivid night-session scene.',
    '蓝色硬地 / 夜赛灯光 / 纽约天际线': 'Blue hard court / Night lights / New York skyline',
    '纽约夏末夜场氛围': 'New York late-summer night atmosphere',
    '澳网墨尔本蓝色硬地': 'Australian Open Melbourne Blue Court',
    '明亮青蓝球场、开放式现代屋顶与桉树绿意，呈现通透、热烈而富有速度感的澳洲盛夏。': 'A bright cyan-blue court, open modern roof, and eucalyptus greenery capture the speed and heat of an Australian summer.',
    '青蓝硬地 / 现代场馆 / 澳洲盛夏': 'Cyan-blue hard court / Modern venue / Australian summer',
    '墨尔本盛夏蓝场氛围': 'Melbourne midsummer blue-court atmosphere',
    '上海大师赛·旗忠网球中心': 'Shanghai Masters · Qizhong Tennis Center',
    '玉兰花瓣般展开的可开合屋顶俯瞰蓝绿硬地，把上海秋日的速度感与现代建筑气质收进同一幅像素画。': 'Qizhong’s retractable magnolia-petal roof overlooks a blue-green court, blending Shanghai autumn speed with modern architecture.',
    '蓝绿硬地 / 玉兰屋顶 / 上海秋日': 'Blue-green hard court / Magnolia roof / Shanghai autumn',
    '上海大师赛旗忠网球中心': 'Shanghai Masters Qizhong Tennis Center',
    '北京国家网球中心·钻石球场': 'Beijing National Tennis Center · Diamond Court',
    '紫蓝硬地嵌进钻石切面的现代场馆，远处借鸟巢天际线点出北京坐标；这里是国家网球中心，不把球场误写进鸟巢内部。': 'A purple-blue court sits inside the faceted Diamond Court, with the distant Bird’s Nest marking Beijing without confusing the two venues.',
    '紫蓝硬地 / 钻石球场 / 鸟巢远景': 'Purple-blue hard court / Diamond Court / Distant Bird’s Nest',
    '北京国家网球中心': 'Beijing National Tennis Center',
    '马德里·魔力盒红土': 'Madrid · Caja Mágica Clay',
    '砖红红土与黑灰钢结构形成强烈反差，可开合的几何屋顶让西班牙首都这座球场拥有近乎舞台装置般的辨识度。': 'Brick-red clay contrasts with black steel, while the retractable geometric roof gives Madrid’s venue a theatrical identity.',
    '红土 / 几何屋顶 / 马德里暮色': 'Clay / Geometric roof / Madrid dusk',
    '马德里魔力盒球场': 'Madrid Caja Mágica Court',
    '里约·赛马会红土': 'Rio · Jockey Club Clay',
    '橙红球场被棕榈、殖民风建筑与热带山景包围，远处基督像剪影把南美阳光和城市节奏带进比赛现场。': 'An orange-red court is surrounded by palms, colonial architecture, and tropical mountains, with Rio’s skyline in the distance.',
    '红土 / 热带绿意 / 里约山景': 'Clay / Tropical greenery / Rio mountains',
    '里约赛马会球场': 'Rio Jockey Club Court',
    '印第安维尔斯·沙漠花园': 'Indian Wells · Tennis Garden',
    '蓝色硬地、成排棕榈与科切拉谷山脉在夕阳中相遇，球场像一块被精心灌溉出来的沙漠绿洲。': 'A blue hard court, rows of palms, and Coachella Valley mountains meet at sunset like a carefully cultivated desert oasis.',
    '蓝色硬地 / 棕榈 / 沙漠山脉': 'Blue hard court / Palms / Desert mountains',
    '印第安维尔斯网球花园': 'Indian Wells Tennis Garden',
    '敦煌·鸣沙月泉概念场': 'Dunhuang · Crescent Lake Concept Court',
    '琥珀色沙丘托起赭红球场，月牙泉、丝路驿亭和一弯新月留在远处。这是一幅风景化想象，不对应现实场馆。': 'Amber dunes hold an ochre court, with Crescent Lake and Silk Road pavilions in the distance. This is a landscape concept, not a real venue.',
    '概念创作 / 鸣沙山 / 月牙泉': 'Concept / Singing Sand Dunes / Crescent Lake',
    '敦煌风景概念球场': 'Dunhuang landscape concept court',
    '喜马拉雅山脚概念场': 'Himalayan Foothills Concept Court',
    '深青球场落在高原谷地，雪峰、冰川、晨光与薄雾构成安静而巨大的背景，强调人与自然尺度之间的反差。': 'A deep-teal court rests in a highland valley beneath snow peaks, glaciers, morning light, and mist.',
    '概念创作 / 雪峰 / 高原晨光': 'Concept / Snow peaks / Highland dawn',
    '喜马拉雅山脚概念球场': 'Himalayan foothills concept court',
    '喇荣山谷概念球场': 'Larung Valley Concept Court',
    '受喇荣五明佛学院所在山谷的红色木屋景观启发，球场设置在开阔谷地而非宗教建筑内部，以克制方式保留高原聚落的视觉震撼。': 'Inspired by the valley’s red wooden homes, the court is placed in open terrain rather than inside religious buildings.',
    '概念创作 / 红色山城 / 川西高原': 'Concept / Red mountain settlement / Western Sichuan plateau',
    '喇荣山谷景观灵感': 'Larung Valley landscape inspiration',
    '《塞尔达传说》灵感·海拉鲁式旷野': 'Hyrule-inspired Open Wilds',
    '翠绿草原、漂浮岛屿、古代石塔与蓝色能量装置围住一片草地球场，保留开放世界冒险感，但不使用角色、Logo 或具体关卡复制。': 'Green plains, floating islands, ancient towers, and blue-energy structures surround a grass court, evoking open-world adventure without copying characters, logos, or levels.',
    '幻想灵感 / 开放旷野 / 浮空遗迹': 'Fantasy-inspired / Open wilds / Floating ruins',
    '海拉鲁式旷野灵感': 'Hyrule-inspired wilds',
    '《只狼》灵感·苇名式山城': 'Ashina-inspired Mountain Castle',
    '深灰球场嵌在险峻战国山城庭院，天守、雪峰、枯松与朱桥营造肃穆压迫感，同样不使用角色、Logo 或具体关卡复制。': 'A dark-gray court sits in a steep Sengoku mountain courtyard with a keep, snow peaks, pines, and a vermilion bridge—without copying characters, logos, or levels.',
    '幻想灵感 / 战国山城 / 雪峰薄雾': 'Fantasy-inspired / Sengoku castle / Snowy mist',
    '苇名式山城灵感': 'Ashina-inspired mountain castle',
    '← 横向滚动查看更多球场 →': '← Scroll horizontally to explore more courts →',
    '少翻进度条，多看真正的回合': 'Spend less time scrubbing, more time watching real rallies',
    '训练视频很长，值得保留的回合却很分散。': 'Training videos are long. The rallies worth keeping are scattered.',
    'Tennis Video Helper 把“自动发现”和“人工决定”分开：模型负责找候选，人负责最后确认。它不会替你删除源视频，也不会把一次声音或一次摆臂直接当成完整回合。': 'Tennis Video Helper separates automatic discovery from human decisions: the model proposes candidates and you make the final call. It never deletes source videos or treats one sound or arm movement as a complete rally.',
    '从整段素材到精选片段': 'From full footage to selected clips',
    '四步完成一次网球视频精选': 'Select Tennis Highlights in Four Steps',
    '先听见可能的击球': 'Detect possible hits in the audio',
    '音频瞬态快速扫描整段视频，只负责提出候选时间窗。脚步声、邻场击球和孤立噪声不能独立开始或延长回合。': 'Audio transients scan the full video and only propose candidate windows. Footsteps, adjacent-court hits, and isolated noise cannot start or extend a rally by themselves.',
    '再确认挥拍和球拍': 'Confirm swings and rackets visually',
    '近端球员的手腕、肘部和躯干轨迹共同判断挥拍；球拍检测进一步排除走路持拍、普通摆臂和靠近镜头的无关动作。': 'Wrist, elbow, and torso motion identify swings; racket detection further filters walking, casual arm movement, and unrelated foreground motion.',
    '在时间线上逐点击球复核': 'Review hit points on the timeline',
    '每个候选片段都能直接播放；绿色方块显示模型确认的击球点，点击时间线即可跳转，0.25× 至 4.00× 倍速自由检查。': 'Every candidate can be played directly. Green markers show confirmed hit points; click the timeline to jump and review at 0.25×–4.00× speed.',
    '只导出你勾选的片段': 'Export only the clips you select',
    '默认最高 1080p 并保留原始帧率关系，也可以选择原画质。覆盖同名旧结果时，会先完整生成并验证新结果，成功后再替换。': 'The default output is up to 1080p while preserving frame-rate relationships, with original-quality export available. Existing results are replaced only after the new result is generated and verified.',
    '从视频输入到安全输出': 'From video input to safe output',
    'Tennis Video Helper 数据处理流程': 'Tennis Video Helper data processing flow',
    '并行分析分支': 'Parallel analysis branches',
    '项目是怎样工作的？': 'How Does the Project Work?',
    '这不是一个只靠声音剪视频的工具。声音负责快速缩小搜索范围，骨架与球拍负责确认真正的挥拍，多路证据融合后才形成候选回合；最终是否保留，仍由用户决定。': 'This is not an audio-only video cutter. Audio narrows the search, pose and racket evidence confirm real swings, and fused evidence forms candidate rallies. You still decide what to keep.',
    '原始训练视频': 'Original Training Video', 'MOV / MP4 · 源文件只读': 'MOV / MP4 · Source is read-only',
    '声音候选': 'Audio Candidates', '击球瞬态只负责提出可能的时间窗': 'Hit-like transients only propose possible time windows',
    '骨架与球拍确认': 'Pose & Racket Confirmation', '识别挥拍时序，过滤走路、捡球和普通摆臂': 'Recognize swing timing and filter walking, ball pickup, and casual arm motion',
    '证据按时间对齐': 'Evidence aligned in time', '音画融合与回合状态机': 'Audio-visual fusion & rally state machine',
    '确认击球点，按节奏、最短时长和击球数量组合候选回合': 'Confirm hit points and form candidate rallies using rhythm, duration, and hit count',
    '候选片段与人工复核': 'Candidate Clips & Human Review', '生成临时候选，在 GUI 中播放、查看击球点并勾选': 'Generate temporary candidates, play them in the GUI, inspect hit points, and select clips',
    '验证后安全发布': 'Safe Publication After Validation', 'NVENC / FFmpeg 导出，验证新片段成功后再替换同名旧结果': 'Export with NVENC / FFmpeg and replace previous results only after validation',
    '主要入口': 'Primary entry', '适合贡献': 'Good contribution areas', '验证位置': 'Tests',
    '声音候选：用低成本扫描缩小搜索范围': 'Audio candidates: narrow the search with a low-cost scan',
    '提取音轨后寻找类似击球的瞬态峰值。邻场击球、脚步声和孤立噪声即使进入候选，也不能单独被判定为真实击球。': 'Extract the audio track and locate hit-like transient peaks. Adjacent-court hits, footsteps, and isolated noise may enter the candidate set but cannot confirm a real hit alone.',
    '噪声过滤、击球声特征、不同球场录音回归': 'Noise filtering, hit-sound features, and regression across court recordings',
    'Issue → 分支 → 测试 → Pull Request': 'Issue → Branch → Test → Pull Request',
    'Tennis Video Helper 参数设置界面': 'Tennis Video Helper settings interface',
    'PARAMETER DECK // 所有关键设置均可在桌面界面内完成': 'PARAMETER DECK // All key settings are available in the desktop interface',
    '想贡献代码？先从一个可以复现的问题开始。': 'Want to contribute? Start with a reproducible issue.',
    '使用项目本地的 uv 环境，修改对应模块，补充最小回归测试，再提交 Pull Request。识别算法的改动请同时说明真实视频样本、预期击球点和误检变化。': 'Use the project-local uv environment, update the relevant module, add a minimal regression test, and submit a pull request. Detection changes should document real samples, expected hits, and false-positive changes.',
    '阅读贡献指南': 'Read the Contribution Guide', '浏览可参与的问题 →': 'Browse open issues →',
    '普通用户也能看懂的设置': 'Settings Anyone Can Understand',
    '保留更长回合，还是寻找更多短回合，由你决定。': 'Choose whether to keep longer rallies or find more short ones.',
    '参数页把识别、性能和导出设置放在同一个像素工作台中，每项都说明“调大”和“调小”会发生什么。': 'The settings page puts detection, performance, and export controls in one pixel workbench, with clear explanations of every adjustment.',
    '最短回合': 'Minimum Rally', '默认 10 秒': 'Default: 10 sec', '最少击球': 'Minimum Hits', '默认 3 次': 'Default: 3 hits',
    '前置 / 后置保留': 'Pre-roll / Post-roll', '2 秒 / 3 秒': '2 sec / 3 sec',
    '声音 / 动作灵敏度': 'Audio / Motion Sensitivity', '分别调节召回与误检': 'Balance recall and false positives independently',
    'GPU 后端': 'GPU Backend', '自动、ONNX、TensorRT、PyTorch CUDA': 'Auto, ONNX, TensorRT, PyTorch CUDA',
    '输出策略': 'Output Strategy', '1080p、原画质、覆盖同名旧结果': '1080p, original quality, safe replacement',
    '研发进度': 'Development Progress', 'v0.1.4 已发布，支持分批复核导出与文件夹快捷打开': 'v0.1.4 adds incremental review exports and folder shortcuts',
    '进度按“已经验证”“当前发布”“下一步计划”区分；性能数字来自固定真实素材回归，不把一次偶然结果写成承诺。': 'Progress separates verified work, current releases, and future plans. Performance figures come from repeatable real-footage regressions, not one-off promises.',
    '多模态识别基线': 'Multimodal Detection Baseline', '复核工作台与安全覆盖': 'Review Workbench & Safe Replacement',
    '分批导出与目录快捷操作': 'Incremental Exports & Folder Shortcuts', '导出后继续保留未读、未选择的候选；输入和输出路径旁可直接打开对应文件夹。': 'Unread and unselected candidates remain after export, and the input and output paths can open their folders directly.', '声音聚焦性能回归': 'Audio-guided Performance Regression',
    '公开下载与发行可信度': 'Public Downloads & Release Trust',
    '下载，校验，安装。三步开始筛选。': 'Download, Verify, Install. Start in Three Steps.',
    '当前安装包没有数字签名，Windows SmartScreen 可能显示未知发布者。只从本页固定版本链接下载，并在安装前核对 SHA-256。': 'The installer is currently unsigned, so Windows SmartScreen may show an unknown publisher. Download only from this fixed-version link and verify SHA-256 before installation.',
    '下载 TennisVideoHelper-Setup-0.1.4.exe': 'Download TennisVideoHelper-Setup-0.1.4.exe', '查看 GitHub Release →': 'View the GitHub Release →', 'GitCode 历史镜像 →': 'GitCode historical mirror →',
    '下载安装包': 'Download the installer', '文件名应为': 'The filename should be', '，大小约 220.4 MiB。': ', approximately 220.4 MiB.',
    '核对 SHA-256': 'Verify SHA-256', 'PowerShell 运行': 'Run in PowerShell', '完成安装': 'Complete installation',
    '确认哈希一致后双击安装；若 SmartScreen 出现提示，选择“更多信息”查看文件名后再决定运行。': 'After verifying the hash, double-click the installer. If SmartScreen appears, choose More info and verify the filename before running it.',
    '复制哈希': 'Copy Hash', '用于确认下载文件与发布资产完全一致。': 'Use this to confirm the download exactly matches the release asset.',
    '你的体验会进入研发清单': 'Your Experience Shapes the Roadmap',
    '遇到问题，或者想到更好的做法？直接在这里告诉我。': 'Found a problem or have a better idea? Tell us here.',
    '不需要自己研究 Issue 格式。填写窗口会在本地整理标题、使用环境和详细说明，再打开已经预填好的 GitHub Issue 页面。': 'You do not need to learn the Issue format. The form organizes the title, environment, and details locally, then opens a prefilled GitHub Issue page.',
    '打开意见反馈窗口': 'Open Feedback Form', '熟悉 GitHub？直接使用 Issue 表单 →': 'Comfortable with GitHub? Use the Issue form directly →',
    '填写反馈': 'Describe Your Feedback', '选择类型，写下现象、建议和使用环境。': 'Choose a type and describe the behavior, suggestion, and environment.',
    '自动整理': 'Organize Automatically', '网页在本地生成结构清楚的 Issue 标题和正文。': 'The site creates a clear Issue title and body locally.',
    '确认提交': 'Review & Submit', '跳转 GitHub 后检查内容，点击一次即可正式创建。': 'Review the content on GitHub, then create the Issue with one click.',
    '安装与使用边界': 'Installation & Usage Boundaries', '开始之前，先确认这几件事': 'Confirm these details before you begin',
    '安装版还需要 Python 或 FFmpeg 吗？': 'Does the installed app require Python or FFmpeg?',
    '不需要。安装包已经内置应用运行环境、模型以及程序使用的 FFmpeg 与 ffprobe。': 'No. The installer includes the application runtime, models, FFmpeg, and ffprobe.',
    '一定要 NVIDIA 显卡吗？': 'Is an NVIDIA GPU required?',
    '轻量安装版可以使用 ONNX GPU 路径；NVIDIA 显卡还能启用 NVDEC / NVENC，并在支持的环境中使用 CUDA 或 TensorRT。不可用时软件会明确显示回退状态。': 'The Light edition can use the ONNX GPU path. NVIDIA GPUs can also enable NVDEC / NVENC and, when supported, CUDA or TensorRT. The app clearly reports any fallback.',
    '程序会删除我的原视频吗？': 'Will the app delete my source videos?',
    '不会。源视频始终只读；软件只向你选择的输出目录写入候选和最终片段。': 'No. Source videos remain read-only; the app writes candidates and final clips only to your chosen output folder.',
    '为什么安装包下载很慢或打不开？': 'Why is the installer slow or unavailable?',
    '最新版安装包托管在公开 GitHub Release。网络连接不稳定时可以进入 Release 页面重试；GitCode 国内镜像目前保留历史版本。': 'The latest installer is hosted on the public GitHub Release. Retry from the Release page if the connection is unstable; the GitCode mirror currently keeps older versions.',
    '网页填写反馈后会立刻公开吗？': 'Does feedback become public immediately?',
    '不会。内容只在你的浏览器里整理；跳转 GitHub 后仍需要你检查并确认提交。Issue 创建后会公开显示，请勿填写手机号、邮箱、私人视频地址或其他敏感信息。': 'No. The content is prepared only in your browser. You must still review and submit it on GitHub. Created Issues are public, so do not include phone numbers, email addresses, private video links, or other sensitive data.',
    '内容在浏览器本地整理': 'Content is prepared locally in your browser', '提交用户意见': 'Submit Feedback',
    '填写完成后会前往 GitHub 的最终确认页面；如果尚未登录，会先显示登录页，登录后继续。本站不会保存你的输入，也不会在网页中使用 GitHub Token。': 'After completing the form, you will go to GitHub for final review. If needed, sign in and continue. This site does not store your input or use a GitHub token.',
    '反馈类型': 'Feedback Type', '使用问题': 'Usage Problem', '识别效果': 'Detection Quality', '安装或更新': 'Installation or Update',
    '功能建议': 'Feature Request', '其他反馈': 'Other Feedback', '软件版本': 'App Version', '不确定': 'Not sure',
    '一句话标题（必填）': 'Short Title (required)', '详细说明（必填）': 'Details (required)', '使用环境': 'Environment',
    'Windows 版本不确定': 'Windows version unknown', '显卡信息（选填）': 'GPU (optional)', '视频规格（选填）': 'Video Format (optional)',
    '我知道 GitHub Issue 创建后会公开显示，并已移除手机号、邮箱、私人视频链接等敏感信息。': 'I understand that GitHub Issues are public and have removed phone numbers, email addresses, private video links, and other sensitive information.',
    '整理并前往 GitHub 提交': 'Prepare and Continue to GitHub', '复制反馈内容': 'Copy Feedback',
    '填写内容后，选择提交或复制备用文本。': 'Complete the form, then submit or copy the backup text.',
    'GitHub 没有自动打开？点击这里继续提交 →': 'GitHub did not open automatically? Continue here →',
    '让模型负责寻找，让你决定什么值得保留。': 'Let the model search. You decide what is worth keeping.',
    '原理与架构': 'How It Works', '下载与安装': 'Download & Install', '用户反馈': 'User Feedback', 'GitHub 项目仓库': 'GitHub Repository',
    'Windows 安装版 · 2026-08-12': 'Windows Installer · 2026-08-12',
    '例如：分析结束后找不到导出按钮': 'Example: I cannot find the export button after analysis',
    '发生了什么？你原本希望看到什么？如果可以，请写下复现步骤。': 'What happened, and what did you expect? Include reproduction steps if possible.',
    '例如：NVIDIA RTX 3070 8GB': 'Example: NVIDIA RTX 3070 8GB', '例如：4K / 60fps / MOV': 'Example: 4K / 60fps / MOV',
    '页面导航': 'Page navigation', '页面主题设置': 'Page theme settings', '关闭主题设置': 'Close theme settings',
    '选择页面明暗模式': 'Choose page color mode', '当前球场背景预览': 'Current court background preview',
    '软件能力概览': 'Software capability overview', '选择像素球场风格': 'Choose a pixel court style',
    '球场切换': 'Court navigation', '上一个球场': 'Previous court', '下一个球场': 'Next court',
    '像素球场横向画廊': 'Horizontal pixel court gallery', '页脚导航': 'Footer navigation',
    '关闭意见反馈窗口': 'Close feedback form',
  }));

  const fragments = [
    ['跟随系统', 'System'], ['深色', 'Dark'], ['浅色', 'Light'],
    ['陕北黄土', 'Shaanbei Loess'], ['法网红土', 'Roland-Garros Clay'],
    ['温网草地', 'Wimbledon Grass'], ['美网夜场', 'US Open Night'],
    ['澳网蓝场', 'Australian Open Blue'], ['上海大师赛', 'Shanghai Masters'],
    ['北京钻石', 'Beijing Diamond'], ['马德里魔力盒', 'Madrid Caja Mágica'],
    ['里约红土', 'Rio Clay'], ['印第安维尔斯', 'Indian Wells'],
    ['敦煌月泉', 'Dunhuang Crescent Lake'], ['喜马拉雅', 'Himalayas'],
    ['喇荣山谷', 'Larung Valley'], ['海拉鲁式旷野', 'Hyrule-inspired Wilds'],
    ['苇名式山城', 'Ashina-inspired Castle'],
    ['跟随球场：', 'Follow court: '], ['（当前', ' (currently '], ['）', ')'],
    ['球场背景预览', ' court background preview'],
    ['当前可能不是 Windows；安装包仅支持 Windows 10 / 11 x64。', 'This device may not be running Windows. The installer supports Windows 10 / 11 x64 only.'],
    ['已复制', 'Copied'], ['SHA-256 已复制到剪贴板。', 'SHA-256 copied to the clipboard.'],
    ['复制失败，请手动选择：', 'Copy failed. Select manually: '],
    ['请先填写一句话标题和详细说明，并勾选公开信息确认。', 'Enter a short title and details, then confirm the public-information checkbox.'],
    ['反馈内容已复制。你可以将它粘贴到聊天、邮件或 GitHub Issue 中。', 'Feedback copied. Paste it into chat, email, or a GitHub Issue.'],
    ['复制失败，请保持窗口打开并手动选择输入内容。', 'Copy failed. Keep the window open and select the content manually.'],
    ['反馈内容较长', 'Your feedback is long'], ['未填写', 'Not provided'],
    ['操作系统：', 'Operating system: '], ['显卡：', 'GPU: '], ['视频规格：', 'Video format: '],
    ['问题或建议', 'Problem or suggestion'], ['由 Tennis Video Helper 官网反馈窗口整理。', 'Prepared by the Tennis Video Helper website feedback form.'],
  ];

  const language = () => {
    try { return localStorage.getItem(storageKey) === 'en' ? 'en' : 'zh-CN'; }
    catch { return 'zh-CN'; }
  };
  const translate = (value) => {
    if (language() !== 'en' || !value) return value;
    if (exact.has(value)) return exact.get(value);
    let result = value;
    for (const [source, target] of fragments) result = result.replaceAll(source, target);
    return result;
  };

  const originalText = new WeakMap();
  const originalAttrs = new WeakMap();
  const translateNode = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const raw = originalText.get(node) ?? node.nodeValue;
      originalText.set(node, raw);
      const leading = raw.match(/^\s*/)?.[0] || '';
      const trailing = raw.match(/\s*$/)?.[0] || '';
      const core = raw.trim();
      if (core) node.nodeValue = `${leading}${translate(core)}${trailing}`;
      return;
    }
    if (!(node instanceof Element)) return;
    let attrs = originalAttrs.get(node);
    if (!attrs) {
      attrs = {};
      for (const name of ['aria-label', 'alt', 'placeholder', 'title', 'content']) {
        if (node.hasAttribute(name)) attrs[name] = node.getAttribute(name);
      }
      originalAttrs.set(node, attrs);
    }
    for (const [name, raw] of Object.entries(attrs)) node.setAttribute(name, translate(raw));
    for (const child of node.childNodes) translateNode(child);
  };

  const applyLanguage = () => {
    const current = language();
    document.documentElement.lang = current;
    translateNode(document.documentElement);
    const button = document.querySelector('[data-language-toggle]');
    if (button) {
      button.querySelector('span').textContent = current === 'en' ? '中' : 'EN';
      button.querySelector('strong').textContent = current === 'en' ? '简体中文' : 'English';
      button.setAttribute('aria-label', current === 'en' ? '切换网站语言为简体中文' : 'Switch website language to English');
    }
    document.dispatchEvent(new CustomEvent('tvh:language-changed', { detail: { language: current } }));
  };

  document.querySelector('[data-language-toggle]')?.addEventListener('click', () => {
    const next = language() === 'en' ? 'zh-CN' : 'en';
    try { localStorage.setItem(storageKey, next); } catch { /* Language still applies for this page load. */ }
    location.reload();
  });

  const observer = new MutationObserver((records) => {
    if (language() !== 'en') return;
    observer.disconnect();
    for (const record of records) {
      if (record.type === 'characterData') {
        originalText.set(record.target, record.target.nodeValue);
        translateNode(record.target);
      }
      for (const node of record.addedNodes) translateNode(node);
    }
    observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  });
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });

  window.tvhI18n = { language, translate, applyLanguage };
  applyLanguage();
})();
