/* 手机出图 · 中英文切换
 *
 * 只翻译界面文案，不改用户输入 / 提示词 / 文件名。
 * 中文原文保存在节点上，切回中文时恢复。
 */
(function () {
  'use strict';

  var KEY = 'mg_lang';
  var lang = 'zh';
  try { lang = localStorage.getItem(KEY) === 'en' ? 'en' : 'zh'; } catch (e) {}

  var EN = {
    /* ---------- 通用 ---------- */
    '手机出图': 'Mobile Studio',
    '本地 · ComfyUI': 'Local · ComfyUI',
    '接口星图': 'API Star Map',
    'NEXUS · 手机出图接口星图': 'NEXUS · Mobile Studio API Map',
    '账号': 'Account',
    '密码': 'Password',
    '进入': 'Sign in',
    '退出登录': 'Sign out',
    '关闭': 'Close',
    '取消': 'Cancel',
    '刷新': 'Refresh',
    '保存': 'Save',
    '删除': 'Delete',
    '完成': 'Done',
    '失败': 'Failed',
    '开始': 'Start',
    '停止': 'Stop',
    '全部': 'All',
    '收藏': 'Favorite',
    '统计': 'Stats',
    '设置': 'Settings',
    '加载更多': 'Load more',
    '正在读取…': 'Loading…',
    '正在读取模型…': 'Loading models…',
    '正在读取 LoRA 列表…': 'Loading LoRA list…',
    '还没有日志': 'No logs yet',
    '这里还没有图片': 'No images here yet',
    '已提交': 'Submitted',
    '提交': 'Submit',
    '采样': 'Sampling',
    '等待第一帧': 'Waiting for first frame',
    '打开原图 / 视频': 'Open image / video',
    '再来一张': 'Generate again',
    '生成': 'Generate',
    '生成舱': 'Generation Deck',
    '停止当前生成': 'Stop current job',
    '展开生成舱': 'Open deck',
    '新图': 'New image',
    '保存图库': 'Saved to gallery',
    '重置视角': 'Reset view',
    '重置布置': 'Reset layout',
    '布置': 'Layout',
    '布置模式': 'Layout mode',
    '拖动星球调整位置，松手自动保存': 'Drag planets to arrange; release to save',
    '自转 ON': 'Auto-rotate ON',
    '负载': 'Load',
    '显存': 'VRAM',
    '内存': 'RAM',
    '连接中': 'Connecting',
    '生图已自动暂停': 'Generation paused',
    '检测到电脑占用较高': 'High system load detected',
    '生成主线 · 点步骤看细节': 'Main flow · click a step for details',
    '拖拽旋转 · 滚轮 / 双指缩放 · 单击看详情 · 双击进功能 · R 重置 · 空格暂停自转':
      'Drag to rotate · wheel/pinch to zoom · click for details · double-click to open · R reset · Space pause',
    '点星球看详情 · 双击进功能 · 双指缩放 · 拖拽旋转':
      'Click a planet for details · double-click to open · pinch to zoom · drag to rotate',
    '搜索功能 / 接口，例如：图生视频、/api/gallery':
      'Search features / APIs, e.g. video, /api/gallery',
    '实时活动连接': 'Live activity connection',

    /* ---------- 登录页 ---------- */
    '需要登录 · 手机出图': 'Sign in · Mobile Studio',
    '输入账号和密码后进入。': 'Sign in with your account and password.',
    '管理员和普通账号看到的图库、配额是分开的。':
      'Admin and normal accounts have separate galleries and quotas.',
    '账号由管理员在「3D 星图 → 安全网关 → 用户管理」里创建。':
      'Accounts are created by the admin in 3D Star Map → Security → Users.',
    '连续输错 5 次会锁定 10 分钟。':
      'Five failed attempts will lock the IP for 10 minutes.',
    '输入账号': 'Enter account',
    '输入密码': 'Enter password',
    '用户名或密码不对': 'Incorrect username or password',
    '登录成功，正在进入…': 'Signed in, opening…',
    '连不上服务：': 'Cannot reach the server: ',
    '登录失败': 'Sign-in failed',
    '权限不够': 'Permission denied',
    '需要登录': 'Sign-in required',

    /* ---------- 主页面：导航与模式 ---------- */
    '出 图': 'Generate',
    '图 库': 'Gallery',
    '日 志': 'Logs',
    '插 件': 'Plugins',
    '插件中心': 'Plugin center',
    '刷新插件': 'Refresh plugins',
    '我的插件包': 'My plugin packs',
    '下载示例': 'Download example',
    '插件包 JSON': 'Plugin JSON',
    '导入插件包': 'Import pack',
    '代码插件': 'Code plugins',
    '插件 ZIP（≤20MB）': 'Plugin ZIP (≤20MB)',
    '提交审批': 'Submit for review',
    '我的提交': 'My submissions',
    '管理员审批': 'Admin review',
    '禁用全部第三方插件': 'Disable all third-party plugins',
    '已重启 ComfyUI': 'ComfyUI restarted',
    '全部安全插件包': 'All safe packs',
    '安装安全插件': 'Safe plugin packs',
    '提交代码插件': 'Submit code plugins',
    '文生图': 'Text to Image',
    '图生图': 'Image to Image',
    '局部重绘': 'Inpaint',
    '文生视频': 'Text to Video',
    '图生视频': 'Image to Video',
    '凭空画': 'From text',
    '照着改': 'Redraw',
    '让它动': 'Animate',
    '图变动': 'Animate image',
    '提示词': 'Prompt',
    '画面比例': 'Aspect',
    '底模': 'Model',
    '画风': 'Style',
    '小工具': 'Tools',
    '负面提示词': 'Negative prompt',
    '采样器': 'Sampler',
    '采样质量': 'Sampling quality',
    '步数': 'Steps',
    '重绘幅度': 'Denoise',
    '种子': 'Seed',
    '出图数量': 'Count',
    '时长': 'Duration',
    '张数': 'Count',
    '模式': 'Mode',
    '画幅': 'Size',
    '视频': 'Video',
    '生成器': 'Builder',
    '随机灵感': 'Random idea',
    '看译文': 'Preview',
    '历史': 'History',
    '双模型对比': 'Compare models',
    '更多 ▾': 'More ▾',
    '更多': 'More',
    '极速（8 步）': 'Turbo (8 steps)',
    '正常（30 步）': 'Normal (30 steps)',
    'Anima 极速': 'Anima Turbo',
    '画质增强 PAG': 'PAG quality boost',
    '高清修复': 'Hires fix',
    'LoRA 叠加': 'LoRA stack',
    '锁定': 'Locked',
    '随机': 'Random',
    '开启': 'On',
    '关闭': 'Off',
    '自定义': 'Custom',
    '自定义…': 'Custom…',
    '4 秒（可能爆显存）': '4s (may run out of VRAM)',
    '应用尺寸': 'Apply size',
    '应用时长': 'Apply duration',
    '宽': 'Width',
    '高': 'Height',
    '宽度': 'Width',
    '高度': 'Height',

    /* ---------- 主页面：提示与说明 ---------- */
    '中文直接写就行，会自动翻译成英文标签。首次出图要加载模型，慢一些。':
      'Write in Chinese; it is translated into English tags automatically. The first generation loads the model and takes longer.',
    '中文直接写，自动翻成英文': 'Write in Chinese · auto-translated',
    '决定画布长什么样': 'Choose the canvas shape',
    '用哪个模型来画': 'Choose the model',
    '给画面加一层风格': 'Add a visual style',
    '写实': 'Photoreal',
    '动漫': 'Anime',
    '竖图': 'Portrait',
    '横图': 'Landscape',
    '方图': 'Square',
    '小竖': 'Small portrait',
    '小横': 'Small landscape',
    '小方': 'Small square',
    '方 480': 'Square 480p',
    '竖 480': 'Portrait 480p',
    '横 480': 'Landscape 480p',
    '竖图适合人物立绘；横图适合风景；方图适合头像或对称构图。':
      'Portrait suits characters; landscape suits scenery; square suits avatars or symmetrical compositions.',
    '画幅跟着底模走，也能自己填': 'Sizes follow the model; custom is allowed',
    '选中底模后，这里会列出它擅长的画幅；手填超过模型上限时会自动等比缩小。':
      'Sizes suited to the selected model are listed here; custom sizes above the model limit are scaled down automatically.',
    '按填写的宽高生成；不是 16 的倍数会自动对齐':
      'Generate at the entered width and height; values snap to multiples of 16.',
    '8GB 显存上很可能失败，只建议试一次':
      'Likely to fail on 8GB VRAM; try it only once.',
    '视频时长（秒）': 'Video duration (seconds)',
    '这个底模的推荐画幅': 'Recommended size for this model',
    'Wan 1.3B 原生是 480p，可选多种画幅；像素量太大会自动等比缩小。时长越长约容易爆显存。':
      'Wan 1.3B is native 480p with several aspect choices; oversized frames are scaled down. Longer clips are more likely to run out of VRAM.',
    '1~2 秒最稳；4 秒以上可能爆显存':
      '1–2s is safest; 4s and above may run out of VRAM',
    'Wan 视频按 8fps 计帧；自定义会向上取到偶数帧。4 秒以上在 8GB 上很可能失败。':
      'Wan video counts frames at 8 fps; custom durations snap to an even frame count. Above 4s on 8GB is likely to fail.',
    '0.5~6 秒，按 8fps 换算帧数': '0.5–6s, converted to frames at 8 fps',
    '新手不用纠结：动漫先用 Anima 2B 或 Illustrious，写实先用 RealVis；选中模型后上面会显示推荐画幅、步数和注意事项。':
      'Not sure where to start? Try Anima 2B or Illustrious for anime, RealVis for photoreal. Selecting a model shows its recommended size, steps and cautions above.',
    '选一个模型；不同模型擅长的东西不一样。':
      'Pick a model; each one is good at different things.',
    '安全插件包直接导入；代码插件先隔离，管理员审批后才安装，原功能不受影响。':
      'Safe packs install directly; code plugins are quarantined and only installed after admin approval. Existing features stay untouched.',
    'JSON 格式，不执行代码；可以添加风格、提示词模板和出图参数预设。':
      'JSON only, no code execution: add styles, prompt templates and generation presets.',
    '已审批的 ComfyUI 自定义节点；安装、禁用、回滚都只动 custom_nodes。':
      'Approved ComfyUI custom nodes; install, disable and rollback only touch custom_nodes.',
    '提交后只进入隔离区，不会自动执行；管理员能看到文件清单、依赖和静态风险扫描结果。':
      'Submissions go to quarantine and never run automatically; the admin sees files, dependencies and static risk hints.',
    '待审批、已通过、已拒绝的代码插件。':
      'Pending, approved and rejected code plugin submissions.',
    '高危插件必须显式强制批准；安装前自动备份旧版本，可一键回滚。':
      'High-risk plugins need explicit force approval; the previous version is backed up for rollback.',
    '管理员可以查看所有账号导入的 JSON 插件包并删除。':
      'Admins can inspect and delete JSON packs imported by any account.',
    '安全插件包只含风格、提示词模板和参数预设，不执行代码，只影响当前账号的界面。':
      'Safe packs contain only styles, prompt templates and presets; they never run code and only affect your own UI.',
    '代码插件会进入隔离区，静态扫描只做风险提示；只有管理员审批后才写入 custom_nodes，并要求重启 ComfyUI。':
      'Code plugins are quarantined; static scanning is only a hint. They are written to custom_nodes only after admin approval, and need a ComfyUI restart.',
    '这个模型不能使用当前 LoRA 目录里的 SDXL LoRA。':
      'This model cannot use the SDXL LoRAs in the current LoRA folder.',
    '这个模型没有验证 PAG，开关已自动关闭。':
      'PAG is not validated for this model, so the switch was turned off.',
    '这个模型不使用负面提示词':
      'This model does not use negative prompts',
    '当前模型没有兼容的 LoRA':
      'No LoRA is compatible with this model',
    '已隐藏': 'Hidden',
    '个不兼容的 LoRA': 'incompatible LoRAs',
    '每步多算一次扰动注意力，线条、蕾丝、花瓣更利落；每张多花约 20 秒，赶时间可关。':
      'Adds perturbed-attention guidance each step for cleaner lines, lace and petals; costs about 20s per image, so turn it off when in a hurry.',
    '确认没问题就点下方「出图」；生成过程中可以点「取消」。':
      'When ready, tap Generate below. You can cancel while it is running.',
    '左边写好提示词，点底部「出图」': 'Write a prompt on the left, then tap Generate',
    '出图结果显示在这里': 'Results appear here',
    '点这里选一张参考图': 'Tap to choose a reference image',
    '移除参考图': 'Remove reference',
    '或把图片拖进这个框': 'or drag an image into this box',
    '保存到手机': 'Save to phone',
    '长按或点这里保存到手机': 'Long-press or tap to save to your phone',
    '已存入图库，切到上方「图 库」滑动浏览全部历史。':
      'Saved to the gallery. Switch to Gallery to browse everything.',
    '图片存在电脑上，点开可左右滑动浏览，不会存到手机。':
      'Images are stored on the computer. Tap to browse; nothing is saved to your phone automatically.',
    '多选 / 删除': 'Select / Delete',
    '多选 / 删除：批量管理图片 · 统计：看画了多少张 · 刷新：重新读取图库':
      'Select/Delete: batch manage · Stats: image counts · Refresh: reload gallery',
    '删图三种方式：① 长按缩略图；② 点「多选 / 删除」勾选后删；③ 点开图片用底部「删除这张」。':
      'Three ways to delete: long-press a thumbnail, use Select/Delete, or open an image and tap Delete this image.',
    '全选': 'Select all',
    '全选本页': 'Select this page',
    '取消选择': 'Clear selection',
    '删除选中': 'Delete selected',
    '拼成一张图': 'Make collage',
    '已选 0 张': '0 selected',
    '收藏的提示词': 'Favorite prompts',
    '最近写过的 · 点 ☆ 收藏': 'Recent prompts · tap ☆ to favorite',
    '清空历史记录': 'Clear history',
    '清空': 'Clear',
    '清空涂抹': 'Clear mask',
    '开始重绘': 'Start inpaint',
    '涂抹重绘': 'Paint to inpaint',
    '涂抹要重画的区域': 'Paint the area to redraw',
    '笔刷': 'Brush',
    '轻微调整 ·': 'Subtle ·',
    '大改': 'Big change',
    '换风格换背景 ·': 'Change style/background ·',
    '重绘一遍，更细但更慢': 'Redraw for more detail, slower',
    '放大重绘一遍，更细但更慢': 'Upscale and redraw for more detail, slower',
    '整图重画': 'Redraw whole image',
    '同参数再出': 'Generate same settings',
    '复刻提示词': 'Reuse prompt',
    '刻参数导出': 'Export parameters',
    '删除这张': 'Delete this image',
    '同种子下细节更清楚': 'More detail with the same seed',
    '开启后每张多花 30~60 秒，细节更锐利，显存也更紧张。':
      'Adds 30–60s per image, with sharper details and higher VRAM use.',
    '让线条、蕾丝、花瓣这些细节更清楚；每张多花约 20 秒，赶时间可关。':
      'Sharpens lines, lace and petals; adds about 20s per image. Turn off when in a hurry.',
    '用官方 Turbo LoRA：8 步 / CFG 1，画面略简单，但一张只要十几秒。':
      'Official Turbo LoRA: 8 steps / CFG 1; slightly simpler image, but only seconds per image.',
    '8 步出图，快一倍多': '8-step generation, more than 2× faster',
    'LoRA 是给模型加画风/角色的小补丁，只有 SDXL 模型能用，Anima 用不了。':
      'LoRA adds styles/characters; SDXL models only, not available for Anima.',
    '· 作用于所有选中的 LoRA': '· Applies to all selected LoRAs',
    '· 同一个种子 + 同一句提示词 = 同一张图':
      '· Same seed + same prompt = same image',
    '· 多听提示词的程度；6 左右最稳，太高会发灰':
      '· Prompt adherence; around 6 is safest, higher can wash out colors',
    '· 每一步都在细化画面；20 步够用，调低更快':
      '· Each step refines the image; 20 steps is usually enough',
    '· 点文字填入': '· Tap text to fill',
    '· 越小越像原图': '· Lower means closer to the original',
    '· 越长越慢，4 秒以上容易爆显存':
      '· Longer is slower; over 4s can run out of VRAM',
    '不知道选啥就用 Euler a；DPM++ 更细但更慢':
      'Use Euler a if unsure; DPM++ is finer but slower',
    '越大越细，也越慢': 'Higher is finer and slower',
    '一次画几张': 'Images per run',
    '一次画多张会排队；张数越多，总时间越长。':
      'Multiple images run in a queue; more images take longer.',
    '可多选，不选就是全部': 'Multi-select; leave empty for all',
    '不想出现的东西': 'Things to avoid',
    '这里写你不想要的东西，比如「模糊、水印、多余的手指」；留空就用默认负面词。':
      'List things to avoid, e.g. blur, watermark, extra fingers; leave empty for defaults.',
    '会追加到提示词末尾': 'Appended to the end of the prompt',
    '点一个加一层画风，再点「无风格」取消。风景照片一般不用加画风。':
      'Tap a style to add it; tap None to remove. Landscape photos usually need no style.',
    '点选下面的词，拼成一整段提示词':
      'Tap words below to build a complete prompt',
    '点选词语拼成一段提示词，纯前端，不调用接口。':
      'Tap words to build a prompt locally; no API call.',
    '从内置词库随机抽一个完整画面点子，纯前端。':
      'Draw a random scene idea from the local library; no API call.',
    '选好种类和风格，点「随机一条」': 'Choose a type and style, then tap Random',
    '选好张数和间隔，点「开始挂机」自动连着出；随时可以点「停止挂机」。':
      'Set count and interval, then Start auto-run; stop anytime.',
    '打开 3D 接口星图': 'Open 3D API Star Map',
    '3D 展示所有功能和 API': 'Explore all features and APIs in 3D',
    '独立页面：宇宙里的星球代表功能，光线代表调用关系；点击星球看它对应的接口和参数。':
      'Standalone page: planets are features, links are calls; click a planet for its API and parameters.',
    '生成器：点词拼句子 · 随机灵感：抽一个完整点子 · 看译文：检查模型收到的英文 · 历史：找回以前写过的 · 双模型对比：同一句话画两张 · 更多：步数、CFG、LoRA 等高级设置':
      'Builder: tap words · Random idea: full scene · Preview: model input · History: past prompts · Compare: two models · More: steps, CFG, LoRA and more',
    '内置 6700+ 角色名 + 3800+ 作品名：写「初音未来」「雷电将军」「芙莉莲」会自动换成模型认识的英文标签，画指定角色时很有用。':
      'Includes 6,700+ character names and 3,800+ series aliases; Chinese names are replaced with Danbooru tags the model knows.',
    '用户活动：登录、出图、图库操作、挂机、放大；安全日志：登录失败、权限拦截、账号管理。日志存在电脑 logs 目录，默认保留 30 天。':
      'Activity: sign-in, generation, gallery, auto-run and upscale. Security: failed logins, permission blocks and account management. Logs are kept for 30 days.',
    '安全日志': 'Security log',
    '用户活动': 'User activity',
    '本机已登录': 'Signed in locally',
    '正在读取…': 'Loading…',
    '正在出图…': 'Generating…',
    '正在重绘涂抹的区域…': 'Inpainting the masked area…',
    '已取消': 'Cancelled',
    '已提交，正在出图…': 'Submitted, generating…',
    '正在恢复上次的任务…': 'Restoring the previous job…',
    '等太久了，放弃了': 'Timed out',
    '取消任务': 'Cancel job',
    '任务不存在': 'Job not found',

    /* ---------- 星图分类 / 功能名 ---------- */
    '自动化编排': 'Automation',
    '监控中心': 'Monitoring',
    '素材知识库': 'Library',
    '图像生成': 'Image generation',
    '模型星系': 'Models',
    '提示词工坊': 'Prompt studio',
    '视频工坊': 'Video studio',
    '任务控制': 'Task control',
    '素材画廊': 'Gallery',
    '安全网关': 'Security',
    '系统内核': 'System core',
    'ComfyUI 节点': 'ComfyUI nodes',
    '核心': 'Core',
    '挂机造图': 'Auto-run',
    '多任务队列': 'Task queue',
    '参数模板': 'Presets',
    '定时任务': 'Schedule',
    '完成通知': 'Done alerts',
    '负载总览': 'System load',
    '任务统计': 'Job stats',
    '错误记录': 'Errors',
    '存储占用': 'Storage',
    '智能让路': 'Load guard',
    '实时活动': 'Live activity',
    '健康总览': 'Health overview',
    '告警中心': 'Alert center',
    '一键诊断': 'Diagnostics',
    '任务时间线': 'Job timeline',
    '趋势': 'Trends',
    '容量预测': 'Capacity forecast',
    '磁盘清理': 'Disk cleanup',
    '一键体检报告': 'Health report',
    '模型导入 / 删除': 'Model import / delete',
    '异常聚焦': 'Abnormal focus',
    '用户活动日志': 'Activity log',
    '账号消耗统计': 'Account usage',
    '词典搜索': 'Dictionary',
    '提示词历史': 'Prompt history',
    '提示词模板': 'Prompt templates',
    '参考图库': 'Reference library',
    '高清修复': 'Hires fix',
    '画质增强 PAG': 'PAG boost',
    'LoRA 叠加': 'LoRA stack',
    'Anima 极速': 'Anima Turbo',
    '采样参数': 'Sampling',
    '种子 / 复现': 'Seed / reproduce',
    '张数 / 批量': 'Count / batch',
    'Wan 模型': 'Wan model',
    '时长 / 画幅': 'Duration / size',
    '可选画幅跟随底模（如 832×1216、1216×832、1024×1024），也能手填宽高；图生图由参考图决定画幅。':
      'Available sizes follow the model (e.g. 832×1216, 1216×832, 1024×1024), and custom width/height is supported; img2img uses the reference image size.',
    '写一句话生成 0.5~4 秒小视频，Wan 2.1 T2V 1.3B，uni_pc / 20 步 / CFG 6。':
      'Generate a 0.5–4s clip from text with Wan 2.1 T2V 1.3B, uni_pc / 20 steps / CFG 6.',
    '480p 多档画幅，时长 0.5~4 秒；帧数必须是 4n+1，4 秒在 8GB 上可能爆显存。':
      'Several 480p aspect choices, 0.5–4s; frame count must be 4n+1, and 4s may run out of VRAM on 8GB.',
    '视频支持 480p 多画幅 / 0.5–4 秒；2 秒约 3 分钟，4 秒在 8GB 上可能爆显存。':
      'Video supports several 480p sizes and 0.5–4s; 2s takes about 3 minutes, and 4s may run out of VRAM on 8GB.',
    '视频编码 / 输出': 'Video encoding / output',
    'Anima 2B': 'Anima 2B',
    'NoobAI Vpred': 'NoobAI Vpred',
    'Juggernaut XI': 'Juggernaut XI',
    'Illustrious': 'Illustrious',
    'RealVis Lightning': 'RealVis Lightning',
    '4x-UltraSharp': '4x-UltraSharp',
    '文本编码器 / VAE': 'Text encoder / VAE',
    '模型预设': 'Model presets',
    '就绪检查': 'Readiness check',
    '中文翻译': 'Chinese translation',
    '看译文': 'Preview English',
    '角色 / 作品词典': 'Character / series dictionary',
    '画风库': 'Style library',
    '提示词生成器': 'Prompt builder',
    '随机灵感': 'Random idea',
    '双模型对比': 'Model comparison',
    '负面提示': 'Negative prompt',
    '出图任务': 'Generation job',
    '状态轮询': 'Status polling',
    '任务列表': 'Job list',
    '取消任务': 'Cancel job',
    '实时预览': 'Live preview',
    '进度 / 剩余时间': 'Progress / ETA',
    '失败 / 取消': 'Error / cancel',
    '画廊': 'Gallery',
    '原图 / 视频': 'Image / video',
    '缩略图': 'Thumbnail',
    '收藏': 'Favorite',
    '删除': 'Delete',
    '拼图': 'Collage',
    '导出': 'Export',
    '拼图 / 导出': 'Collage / Export',
    '调用中': 'Calling',
    '导出参数': 'Export parameters',
    '统计': 'Stats',
    '视频播放': 'Video playback',
    '元数据 / 隐私': 'Metadata / privacy',
    '登录': 'Sign in',
    '会话': 'Session',
    '退出': 'Sign out',
    '限流 / 哈希': 'Rate limit / hashing',
    '网络绑定': 'Network binding',
    '单实例保护': 'Single instance',
    '请求体 / 上传限制': 'Body / upload limits',
    '用户管理': 'User management',
    '安全日志': 'Security log',
    '任务调度': 'Task scheduling',
    '节点 / 模型扫描': 'Node / model scan',
    '系统状态': 'System status',
    '实时进度': 'Live progress',

    /* ---------- 星图面板 / 流程 ---------- */
    '正在使用': 'In use',
    '当前没有用户在这里操作。': 'No user is currently using this.',
    '进入相关功能：': 'Open related feature: ',
    '生成流程 · ': 'Flow · ',
    '生成支线 · ': 'Branch · ',
    '从「': 'From "',
    '」分叉': '"',
    '回到文生图主线 →': 'Back to main flow →',
    '对应接口': 'APIs',
    '参数': 'Parameters',
    '相关功能': 'Related features',
    '星球贴图库': 'Planet textures',
    '实时数据': 'Live data',
    '刷新数据': 'Refresh data',
    '查看功能': 'Open feature',
    '打开对应的功能界面': 'Open the related screen',
    '在星图里定位负载面板': 'Locate the load panel',
    '在星图里定位实时活动': 'Locate live activity',
    '在当前星图里打开': 'Open in this star map',
    '规划中': 'Planned',
    '内部机制': 'Internal',
    '管理员': 'Admin',
    '普通': 'User',
    '启用': 'Enabled',
    '已禁用': 'Disabled',
    '不变': 'Unchanged',
    '将应用到选中的账号': 'Applies to the selected accounts',
    '当前': 'Current',
    '模型': 'Model',
    '运行中': 'Running',
    '已完成': 'Done',
    '进行中': 'Running',
    '排队中': 'Queued',
    '未知': 'Unknown',
    '错误记录': 'Errors',
    '最近没有失败或取消的任务。': 'No recent failed or cancelled jobs.',
    '还没有任务记录。': 'No jobs yet.',
    '45 秒内没有新事件。': 'No events in the last 45 seconds.',
    '当前空闲': 'Idle',
    '个任务运行中': 'job(s) running',
    '个账号': 'account(s)',
    '张': 'images',
    '条': 'records',
    '模型与预设': 'Models and presets',
    '个底模': 'base models',
    '视频就绪': 'video ready',
    '视频未就绪': 'video not ready',
    '在生成舱使用': 'Use in deck',
    '图库统计': 'Gallery stats',
    '图片': 'Images',
    '占用': 'Storage',
    '平均耗时': 'Avg. time',
    '隔离区': 'Quarantine',
    '类型': 'Types',
    '按模型': 'By model',
    '隔离文件': 'Quarantined files',
    '待处理': 'pending',
    '提示词历史': 'Prompt history',
    '本机浏览器': 'this browser',
    '还没有写过的提示词；去主页面出图后会自动记在这里。':
      'No prompts yet. Prompts are recorded automatically after you generate.',
    '填入生成舱': 'Fill deck',
    '已填入提示词，可以直接生成。': 'Prompt filled; ready to generate.',
    '中文翻译': 'Chinese translation',
    'Argos 离线翻译 · 不离开星图': 'Offline Argos translation · stay in the star map',
    '输入中文提示词，例如：雨后的青石巷，少女撑伞回头':
      'Enter Chinese text, e.g. a girl with an umbrella after the rain',
    '翻译': 'Translate',
    '翻译结果会显示在这里。': 'The translation will appear here.',
    '先写点中文。': 'Enter some Chinese first.',
    '翻译中…': 'Translating…',
    '翻译失败：': 'Translation failed: ',
    '没有返回结果': 'No result returned',
    '还没有账号数据。': 'No account data yet.',
    '模型与预设': 'Models and presets',
    '文本编码 / VAE': 'Text encoder / VAE',
    '采样器': 'Samplers',
    '放大模型': 'Upscalers',
    '刷新数据': 'Refresh data',
    '用户活动日志': 'Activity log',
    '安全日志': 'Security log',
    '全部账号': 'All accounts',
    '仅自己': 'Only me',
    '未登录': 'Not signed in',
    '服务启动': 'Server start',
    '系统': 'System',
    '登录成功': 'Signed in',
    '登录失败': 'Sign-in failed',
    '登录锁定': 'Login locked',
    '未登录访问': 'Unauthenticated access',
    '权限拦截': 'Permission blocked',
    '任务完成': 'Job done',
    '任务失败': 'Job failed',
    '开始挂机': 'Auto-run started',
    '停止挂机': 'Auto-run stopped',
    '取消任务': 'Job cancelled',
    '删除图片': 'Delete images',
    '导出参数': 'Export parameters',
    '创建账号': 'Create account',
    '修改账号': 'Update account',
    '删除账号': 'Delete account',
    '失败': 'Failed',
    '成功': 'OK',
    '条记录': 'records',
    '当前没有用户在这里操作。': 'No user is currently using this.',
    '正在读取…': 'Loading…',
    '正在读取模型…': 'Loading models…',
    '正在生成…': 'Generating…',
    '正在出图…': 'Generating…',
    '已完成': 'Done',
    '已取消': 'Cancelled',
    '已提交': 'Submitted',
    '采样中': 'Sampling',
    '等待第一帧': 'Waiting for first frame',
    '预计剩余': 'ETA',
    '预计': 'ETA',
    '提交失败：': 'Submit failed: ',
    '生成失败：': 'Generation failed: ',
    '生成完成': 'Generation complete',
    '用时': 'in',
    '秒': 's',
    '张图': 'images',
    '共': 'total',
    '已同步到另一个界面发起的任务，进度会在这里持续更新。':
      'Synced a job started in the other view; progress updates here.',
    '已同步另一个界面完成的任务': 'Synced a finished job from the other view',
    '可打开原图或再来一张。': 'Open the image or generate again.',
    '图库已经更新。': 'Gallery updated.',
    '生成中': 'Generating',
    '查看结果': 'View result',
    '重试生成': 'Retry',
    '停止': 'Stop',
    '已取消：': 'Cancelled: ',
    '生成失败：': 'Generation failed: ',
    '当前没有用户在这里操作。': 'No user is currently using this.'
  };

  Object.assign(EN, {
    '本地 · ComfyUI · 管理员': 'Local · ComfyUI · Admin',
    '常用：': 'Common:',
    '不会写提示词也能用': 'No prompt writing needed',
    '换个提示词': 'New prompt',
    '种类': 'Category',
    '风格': 'Style',
    '随机一条': 'Random one',
    '拼成提示词': 'Build prompt',
    '翻译预览 · 模型实际收到的英文': 'Translation preview · what the model receives',
    '点上面的「看译文」开始': 'Tap Preview above to start',
    '未安装中文翻译组件（Argos/MiniSBD），请直接用英文提示词':
      'Chinese translation (Argos/MiniSBD) is not installed; use English prompts.',
    '这台机器没有安装中文翻译组件（Argos/MiniSBD）。请直接用英文提示词。':
      'This machine does not have the Chinese translator (Argos/MiniSBD). Use English prompts.',
    '还没收藏，在下面的历史里点 ☆': 'No favorites yet; tap ☆ in history',
    '8GB 显存，别贪长': '8 GB VRAM; keep it short',
    '给模型加画风或角色': 'Add a style or character to the model',
    '普通 LoRA 都是 SDXL 的，Anima 用不了；想加速用下面「极速模式」。':
      'Standard LoRAs are SDXL-only; Anima cannot use them. Use Turbo below for speed.',
    '强度': 'Strength',
    '开启 ×1.3': 'On ×1.3',
    'Anima 暂不支持 PAG，这个开关对它无效。':
      'Anima does not support PAG; this switch has no effect.',
    '自动连着出': 'Run automatically',
    '间隔': 'Interval',
    '实时预览 · 还在生成中': 'Live preview · generating',
    '全部模型': 'All models',
    '全部用户': 'All users',
    'Wan 视频': 'Wan video',
    '今天': 'Today',
    '昨天': 'Yesterday',
    '☆ 收藏': '☆ Favorite',
    '放大 2×': 'Upscale 2×',
    '放大 4×': 'Upscale 4×',
    '横向没有隐藏按钮，全部在上面 · 删除有二次确认':
      'No hidden buttons; everything is above · deletion asks for confirmation',
    '视频只有 480p 三档：显存小，画面别贪大；1~3 秒最稳。':
      'Video offers three 480p sizes only; keep clips short (1–3s) for 8 GB VRAM.',
    '当前：': 'Current: ',
    '管理员视图：显示所有账号最近的 100 条记录。':
      'Admin view: latest 100 records from all accounts.',
    '当前只显示你自己的活动；安全日志只有管理员能看。':
      'Only your own activity is shown; security logs are admin-only.',
    '用户活动': 'User activity',
    '安全日志': 'Security log',
    '动漫 · Anima 2B（2026）': 'Anime · Anima 2B (2026)',
    '动漫 · NoobAI Vpred': 'Anime · NoobAI Vpred',
    '写实 · Juggernaut XI 风景': 'Photo · Juggernaut XI landscape',
    '动漫 · Illustrious': 'Anime · Illustrious',
    '写实 · RealVis Lightning': 'Photo · RealVis Lightning',
    '动漫 · Counterfeit（旧）': 'Anime · Counterfeit (legacy)',
    '最懂你的描述，动漫首选。用不了 SDXL 的 LoRA 和 PAG；「更多」里可开 8 步极速。':
      'Best at natural descriptions; the anime default. SDXL LoRA/PAG do not apply; enable 8-step Turbo in More.',
    '无风格': 'No style',
    '水彩': 'Watercolor',
    '油画': 'Oil painting',
    '像素': 'Pixel art',
    '水墨': 'Ink wash',
    '吉卜力': 'Ghibli',
    '赛博': 'Cyberpunk',
    '3D': '3D',
    '胶片': 'Film',
    '厚涂': 'Impasto',
    '线稿': 'Line art',
    '国漫淡彩': 'Chinese animation · light color',
    '国漫水墨': 'Chinese animation · ink',
    '主体': 'Subject',
    '场景': 'Scene',
    '光线': 'Lighting',
    '画质': 'Quality',
    '氛围': 'Mood',
    '节点 ·': 'nodes ·',
    '连线 ·': 'links ·',
    '星系分类': 'Categories',
    '星系概览': 'Overview',
    '手机出图 · 核心。本地 ComfyUI + 移动端网页控制台，负责调度模型、任务队列、图库与安全网关；所有功能都从这里向外延伸。':
      'Mobile Studio core. Local ComfyUI + mobile web console for models, job queue, gallery and security; everything extends from here.',
    '深海蓝': 'Deep ocean',
    '紫云带': 'Violet cloud',
    '玫瑰岩': 'Rose rock',
    '青冰': 'Cyan ice',
    '金气态': 'Golden gas',
    '翡翠海': 'Emerald sea',
    '熔岩橙': 'Lava orange',
    '蓝冰': 'Blue ice',
    '恒星金': 'Stellar gold',
    '森林': 'Forest',
    '琥珀岩': 'Amber rock',
    '青气态': 'Teal gas',
    '点一张给这颗星球换贴图，会自动记住；新出现的 ComfyUI 节点会自动领一张。':
      'Tap a texture to apply it to this planet; it is remembered. New ComfyUI nodes get one automatically.',
    '流程': 'Flow',
    '图库': 'Gallery',
    '输入': 'Input',
    '理解': 'Understand',
    '任务': 'Task',
    '输出': 'Output',
    '支线': 'Branches',
    '写提示词': 'Write prompt',
    '角色词典': 'Character dictionary',
    '极速 / LoRA': 'Turbo / LoRA',
    '任务队列': 'Job queue',
    '进度轮询': 'Status polling',
    '放大': 'Upscale',
    '负载中': 'Busy',
    '空闲': 'Idle',
    '轻载': 'Light load',
    '高负载': 'Heavy load',
    '读取中': 'Loading',
    '提示': 'Prompt',
    '安全': 'Security',
    '自动化': 'Automation',
    '监控': 'Monitoring',
    '素材': 'Library',
    '加载 UNet': 'Load UNet',
    '加载文本编码器': 'Load text encoder',
    '加载 VAE': 'Load VAE',
    '空 Latent': 'Empty latent',
    '极速 LoRA': 'Turbo LoRA',
    '文本编码': 'Text encoding',
    'VAE 解码': 'VAE decode',
    '保存图片': 'Save image',
    '竖 832×1216': 'Portrait 832×1216',
    '横 1216×832': 'Landscape 1216×832',
    '方 1024×1024': 'Square 1024×1024',
    '长竖 768×1344': 'Tall 768×1344',
    '长横 1344×768': 'Wide 1344×768',
    'PAG 画质增强': 'PAG quality boost',
    '开始生成': 'Start generation',
    '生成流程': 'Generation flow',
    '接口': 'APIs',
    '提交后会自动收起，回到星图看任务流过各个节点；左下角「生成」随时展开实时预览。':
      'Closes automatically after submitting; watch the task flow through the map. Tap Generate anytime for live preview.',
    '所有功能': 'All features',
    '全部功能': 'All features',
    '模型星系 · 调用中': 'Models · calling',
    '👤 人物': '👤 People',
    '🏔 风景': '🏔 Scenery',
    '🐾 动物': '🐾 Animals',
    '🤖 机甲': '🤖 Mecha',
    '✨ 幻想': '✨ Fantasy',
    '☕ 日常': '☕ Daily life',
    '随机灵感': 'Random idea',
    '提示词生成器': 'Prompt builder',
    '当前范围可组合出约 ': 'About ',
    ' 条不同提示词。': ' possible prompts in this scope.',
    '先选几个词': 'Pick a few words first',
    '已拼成提示词，点「出图」开始': 'Prompt built; tap Generate to start',
    '先写上提示词': 'Write a prompt first',
    '（译不出来，可能是纯英文提示词）':
      '(No translation; the prompt may already be English)',
    '翻译中…': 'Translating…',
    '翻译失败：': 'Translation failed: ',
    '出图': 'Generate',
    '停止挂机': 'Stop auto-run',
    '开始挂机': 'Start auto-run',
    '蓝色': 'Blue',
    '请选择一张图片': 'Choose an image',
    '这张图没有可导出的参数信息': 'This image has no exportable parameters',
    '没有可用的图片': 'No usable images',
    '已取消': 'Cancelled',
    '正在取消当前任务…': 'Cancelling the current job…',
    '完成但没有找到图片': 'Finished but no image was found',
    '生成失败': 'Generation failed',
    '任务状态读取失败': 'Could not read job status',
    '你的电脑正被大量占用，生图已暂停；占用降下来后会自动恢复。':
      'Your computer is under heavy load; generation is paused until it settles.',
    '先写点想画的内容吧。': 'Describe what you want to draw first.',
    '提交失败：': 'Submit failed: ',
    '正在提交任务…': 'Submitting job…',
    '任务已提交 · 已回到星图看节点流动；点左下角「生成中」可回来看实时进度。':
      'Job submitted · back to the star map; tap Generating to see progress.',
    '已生成，点「查看结果」打开。': 'Done; tap View result.',
    '生成完成': 'Generation complete',
    '可打开原图或再来一张。': 'Open the image or generate again.',
    '共': 'Total',
    '张，已显示第 1 张': 'images; showing #1',
    '预计剩余': 'ETA',
    '采样中': 'Sampling',
    '已提交': 'Submitted',
    '等待第一帧': 'Waiting for first frame',
    '实时预览': 'Live preview',
    '停止': 'Stop',
    '查看结果': 'View result',
    '重试生成': 'Retry',
    '生成中': 'Generating',
    '当前没有用户在这里操作。': 'No user is currently using this.'
  });

  Object.assign(EN, {
    /* 星图面板 · 功能入口与分支 */
    '包含功能': 'Included features',
    '查看任务状态': 'View job status',
    '去任务面板取消': 'Go to the task panel to cancel',
    '查看进度': 'View progress',
    '查看失败任务': 'View failed jobs',
    '进入图库看原图': 'Open the original in Gallery',
    '去图库管理图片': 'Manage images in Gallery',
    '去图库选图拼图': 'Choose images for a collage',
    '去图库导出参数': 'Export parameters in Gallery',
    '去图库看视频': 'Watch the video in Gallery',
    '去图库查看元数据': 'View metadata in Gallery',
    '去图库选图放大': 'Choose an image to upscale',
    '去图库选图涂抹重绘': 'Choose an image to inpaint',
    '去提示词写角色名': 'Add the character to the prompt',
    '打开 LoRA 设置': 'Open LoRA settings',
    '打开种子设置': 'Open seed settings',
    '打开张数设置': 'Open count settings',
    '打开视频参数': 'Open video settings',
    '进入模型选择': 'Open model selection',
    '客户端本地': 'Client-side only',
    '纯前端功能，不调用后端接口。': 'Client-side only; no backend API is called.',
    '模型收到的英文': 'English the model receives',

    /* 星图面板 · 模型 / 就绪 */
    '视频模型': 'Video model',
    '模型就绪检查': 'Model readiness check',
    '就绪': 'ready',
    '未就绪': 'not ready',
    '（强制）': '(forced)',
    'Anima 用 Qwen3 + Qwen VAE；SDXL 用底模自带 CLIP / VAE。':
      'Anima uses Qwen3 + Qwen VAE; SDXL uses the CLIP / VAE bundled with the checkpoint.',
    '两次': 'Two runs',
    'PyAV 抽帧': 'PyAV frame extraction',
    '抽帧': 'frame extraction',
    '初音未来': 'Hatsune Miku',
    '内部机制': 'internal',
    '规划中 presets.json': 'planned presets.json',
    '规划中 cron / 每日': 'planned cron / daily',
    '规划中 webhook / IM': 'planned webhook / IM',

    /* 星图面板 · 账号 / 限额 / 日志 */
    '账号列表': 'Accounts',
    '普通账号': 'Normal account',
    '禁用': 'Disable',
    '重置密码': 'Reset password',
    '保存限额': 'Save limits',
    '限额设置（管理员不受限）': 'Limits (admin unrestricted)',
    '限额设置': 'Limits',
    '游客': 'Guest',
    '临时游客': 'Guest',
    '功能：全部开放': 'Features: all enabled',
    '全部开放': 'All enabled',
    '角色': 'Role',
    '每日 不限': 'Daily: unlimited',
    '图库 不限': 'Gallery: unlimited',
    '存储 不限': 'Storage: unlimited',
    '流量/日 不限': 'Traffic/day: unlimited',
    '流量/月 不限': 'Traffic/month: unlimited',
    '每日': 'Daily',
    '本月': 'This month',
    '请求': 'Requests',
    '运行': 'Running',
    '今日': 'Today',
    '存储': 'Storage',
    '流量': 'Traffic',
    '功能': 'Features',
    '不限': 'Unlimited',
    '状态': 'Status',
    '方法': 'Method',
    '被这些功能调用': 'Used by',
    '工作流': 'Workflow',
    '节点类型': 'Node type',
    '工作流来源': 'Workflow source',
    'ComfyUI 最近执行': 'ComfyUI latest run',
    '立即刷新': 'Refresh now',
    '系统负载': 'System load',
    '服务启动': 'Server start',
    '登录成功': 'Signed in',
    '登录失败': 'Sign-in failed',
    '删除账号': 'Delete account',
    '修改账号': 'Update account',
    '创建账号': 'Create account',
    '重置密码': 'Reset password',
    '生成游客': 'Create guest',
    '游客过期': 'Guest expired',
    '打包下载': 'Create archive',
    '下载打包': 'Download archive',
    '删除模型': 'Delete model',
    '恢复模型': 'Restore model',
    '彻底删除模型': 'Permanently delete model',
    '清空模型回收站': 'Empty model trash',
    '导入模型': 'Import model',
    '上传模型': 'Upload model',
    '自动清理': 'Automatic cleanup',
    '清理磁盘': 'Run disk cleanup',
    '清理设置': 'Cleanup settings',
    '生成体检报告': 'Generate health report',
    '系统诊断': 'System diagnostics',
    '监控设置': 'Monitoring settings',
    '修改密码': 'Change password',
    '修改密码被拒': 'Password change denied',
    '激活授权': 'Activate license',
    '翻译设置': 'Translation settings',
    '任务重试': 'Job retry',
    'LoRA 不兼容': 'Incompatible LoRA',
    '备份数据': 'Back up data',
    '恢复数据': 'Restore data',
    '重置系统': 'Reset system',
    '节点接入': 'Node joined',
    '节点接入被拒': 'Node join denied',
    '生成接入码': 'Create join code',
    '节点认证失败': 'Node authentication failed',
    '节点协议不符': 'Node protocol mismatch',
    '节点上线': 'Node online',
    '节点离线': 'Node offline',
    '节点设置': 'Node settings',
    '暂停节点': 'Pause node',
    '恢复节点': 'Resume node',
    '移除节点': 'Remove node',
    '刷新节点': 'Refresh node',
    '轮换节点密钥': 'Rotate node secret',
    '节点主人暂停': 'Node owner paused',
    '节点主人恢复': 'Node owner resumed',
    '批准节点': 'Approve node',
    '修改节点': 'Update node',
    '生成节点包': 'Create node bundle',

    /* 星图面板 · 监控 */
    '读取模型…': 'Loading models…',
    '收起生成舱': 'Close deck',
    '描述你想画的画面……中文即可，例如：国漫淡彩，雨后的青石巷，少女撑伞回头':
      'Describe the scene… Chinese is fine, e.g. Chinese light-color style, a girl with an umbrella after the rain',
    '留空使用模型默认值': 'Leave empty for the model default',
    '自动': 'Auto',
    '会中断 ComfyUI 当前正在跑的任务':
      'This will interrupt the job currently running in ComfyUI.',
    '负载面板': 'load panel',
    '智能让路状态': 'load guard status',
    'HTTPS 关闭': 'HTTPS off',
    'HTTPS 开启': 'HTTPS on',
    '用户名（2~32 位字母数字._-）': 'Username (2–32 letters, digits, ._-)',
    '密码（至少 6 位）': 'Password (at least 6 characters)',
    '显示名（可选）': 'Display name (optional)',
    '每日张数（0=不限）': 'Images/day (0 = unlimited)',
    '图库上限（0=不限）': 'Gallery limit (0 = unlimited)',
    '存储上限 MB（0=不限）': 'Storage limit MB (0 = unlimited)',
    '上传上限 MB': 'Upload limit MB',
    '最大像素（万）': 'Max pixels (10k)',
    '最大步数': 'Max steps',
    '单次张数': 'Images per run',
    '同时任务': 'Concurrent jobs',
    '每日流量 MB（0=不限）': 'Traffic/day MB (0 = unlimited)',
    '每月流量 MB（0=不限）': 'Traffic/month MB (0 = unlimited)',
    '功能开关（取消勾选=暂时关闭）':
      'Feature switches (uncheck to disable temporarily)',
    '可用模型（留空=全部，逗号分隔文件名）':
      'Allowed models (empty = all; comma-separated filenames)',
    '（管理员不受限）': ' (admin unrestricted)',
    '操作失败：': 'Operation failed: ',
    'ComfyUI 串行执行任务；多账号按公平队列轮流放行，任务列表能看到排队位置和预计等待。':
      'ComfyUI runs jobs serially; multiple accounts take turns in a fair queue, and the job list shows queue position and ETA.',
    '等待 GPU': 'Waiting for GPU',
    '排队超时或已取消': 'Queue timed out or cancelled',
    '没有可取消的任务': 'No cancellable jobs',
    '打开原图': 'Open original',
    '当前底模不在管理员允许的模型列表里。':
      'The current model is not in the administrator-allowed list.',
    '至少要保留一个管理员': 'At least one admin must remain',
    '不能删除当前登录的账号': 'Cannot delete the signed-in account',
    '账号不存在': 'Account not found',
    '用户名已经存在': 'Username already exists',
    '密码至少 6 位': 'Password must be at least 6 characters',
    '用户名只能 2~32 位字母、数字、点、下划线或短横线':
      'Username must be 2–32 letters, digits, dots, underscores or hyphens',
    '不能操作当前登录账号': 'Cannot operate on the signed-in account',
    '未知操作': 'Unknown action',
    '未知批量操作': 'Unknown bulk operation',
    '请选择账号': 'Select accounts',
    '没有要修改的字段': 'No fields to change',
    '至少要保留一个启用的管理员': 'At least one enabled admin must remain',
    '只有管理员可以连接': 'Only admins can connect',
    '只有管理员能看安全日志': 'Only admins can view the security log',
    '只有管理员可以管理账号': 'Only admins can manage accounts',
    '只有管理员可以批量操作': 'Only admins can run bulk actions',
    '没有权限': 'Permission denied',
    '请求格式错误': 'Invalid request',
    '请求体太大': 'Request too large',
    'Content-Length 无效': 'Invalid Content-Length',
    'Content-Length 不合法': 'Invalid Content-Length',
    '需要 WebSocket 升级': 'WebSocket upgrade required',
    '提示词是空的': 'Prompt is empty',
    'ComfyUI 没在运行': 'ComfyUI is not running',
    '电脑上的 ComfyUI 没在运行，先双击启动 ComfyUI.bat。':
      'ComfyUI is not running on this computer. Start ComfyUI first.',
    '缺少图片名': 'Missing image name',
    '请选择一张图片（视频不能放大）':
      'Choose an image (videos cannot be upscaled)',
    '找不到这张图片': 'Image not found',
    '没装放大模型（ComfyUI/models/upscale_models）':
      'No upscale model installed (ComfyUI/models/upscale_models)',
    '图生视频要先选一张参考图':
      'Choose a reference image for image-to-video first',
    '不是你启动的挂机任务': 'This auto-run job was not started by you',
    '管理员关闭了你的挂机造图权限。':
      'The administrator has disabled auto-run for your account.',
    '另一个账号正在挂机，等它结束再开':
      'Another account is running auto mode; wait for it to finish.',
    '已经在挂机了，先停掉再开':
      'Auto mode is already running; stop it before starting again.',
    '图生视频模型还没装好：缺 wan2.1_vace_1.3B_fp16.safetensors。':
      'Image-to-video model is not installed: missing wan2.1_vace_1.3B_fp16.safetensors.',
    '视频模型还没装好：需要 Wan 的 UNet / 文本编码器 / VAE 三个文件。':
      'Video model is not installed: Wan UNet, text encoder and VAE are required.',
    '没有可用的放大模型': 'No upscale model available',
    '完成但没找到输出图片': 'Finished but no output image was found',
    '超时（15 分钟）': 'Timed out (15 minutes)',
    '账号已停用': 'Account disabled',
    '电脑占用较高': 'High computer load',
    '出图失败': 'Generation failed',
    '显存不足。把画幅改小、视频时长改短，或把张数改成 1 张再试。':
      'Out of VRAM. Use a smaller size, a shorter video, or one image per run.',
    '底模加载失败。去 ComfyUI 窗口看看模型文件是否完整。':
      'Failed to load the model. Check the model file in the ComfyUI window.',
    '你还没有操作记录': 'You have no activity yet',
    '日志读取失败': 'Could not load logs',
    '连不上日志服务': 'Cannot reach the log service',
    '不是有效的图片': 'Not a valid image',
    '只接受 PNG / JPEG / WebP': 'Only PNG / JPEG / WebP are accepted',
    '图片是空的': 'The image is empty',
    '图片编码损坏': 'The image encoding is corrupted',
    '图片尺寸无效': 'Invalid image dimensions',
    '图片已损坏或不是真正的图片': 'The image is corrupted or not a real image',
    '图片单边太长（最多 12000 像素）': 'Image side is too long (max 12000 px)',
    '图片像素太大（最多 4000 万像素）':
      'Image has too many pixels (max 40 megapixels)',
    '账号已删除': 'Account deleted',
    '算力节点已被移除': 'The compute node was removed',
    '算力节点失联': 'The compute node disconnected',
    '算力节点重启或任务丢失': 'The compute node restarted or lost the job',
    '远端任务超时（15 分钟）': 'Remote job timed out (15 minutes)',
    '远端执行失败': 'Remote execution failed',
    '远端结果没有可用图片': 'The remote result had no usable image',
    '完成但没有输出图片': 'Finished but no output image was found',
    '本机 ComfyUI 没在运行，也没有可用的算力节点。':
      'Local ComfyUI is not running and no compute node is available.',
    '图生图 / 局部重绘需要先上传参考图':
      'Image-to-image and inpainting need a reference image.',
    '局部重绘需要涂抹蒙版': 'Inpainting needs a painted mask.',
    '放大只能在本机执行；本机接单已关闭。':
      'Upscale runs on this PC only, and local accepting is disabled.',
    '保存的工作流': 'Saved workflow',
    '未分类': 'Uncategorized',
    '（无）': '(none)',
    '（带参数导出）': ' (with parameters)',
    '负面:': 'Negative:',
    '排队生图': 'Generation queue',
    '任务队列': 'Task queue',
    '队列控制': 'Queue control',
    '按 GPU 成本公平排队；可暂停接单、设置维护窗口和账号优先级。运行中的任务不会被中断。':
      'Fair queue weighted by GPU cost; pause intake, set maintenance windows and account priority. Running jobs are not interrupted.',
    '刷新队列': 'Refresh queue',
    '立即派发': 'Dispatch now',
    '暂停新的出图任务': 'Pause new generation jobs',
    '原因': 'Reason',
    '例如：临时维护': 'e.g. temporary maintenance',
    '保存暂停': 'Save pause',
    '最长等待（分钟，0=不限）': 'Max wait (minutes, 0 = unlimited)',
    '保存等待': 'Save max wait',
    '维护窗口': 'Maintenance window',
    '开始': 'Start',
    '结束': 'End',
    '周一': 'Mon',
    '周二': 'Tue',
    '周三': 'Wed',
    '周四': 'Thu',
    '周五': 'Fri',
    '周六': 'Sat',
    '周日': 'Sun',
    '保存维护窗口': 'Save maintenance window',
    '维护窗口生效中': 'Maintenance active',
    '全局暂停中': 'Globally paused',
    '还没有账号。': 'No accounts yet.',
    '队列暂停': 'Queue paused',
    '优先级加成 0~100': 'Priority boost 0-100',
    '保存优先级': 'Save priority',
    '恢复队列': 'Resume queue',
    '暂停队列': 'Pause queue',
    '取消排队': 'Cancel queued',
    '取消这个账号所有排队中的任务？运行中的任务不会被打断。':
      'Cancel all queued jobs for this account? Running jobs are not interrupted.',
    '队列设置已保存': 'Queue settings saved',
    '队列操作失败：': 'Queue action failed: ',
    '队列读取失败：': 'Queue load failed: ',
    '管理员暂停账号队列': 'Paused by admin',
    '每日 GPU 秒（0=不限）': 'GPU seconds/day (0 = unlimited)',
    '每月 GPU 秒（0=不限）': 'GPU seconds/month (0 = unlimited)',
    '管理员暂停了这个账号的队列': 'The administrator paused this account queue',
    '处于维护窗口，任务会保留到窗口结束':
      'Maintenance window; jobs are kept until it ends',
    '管理员暂停了新的出图任务': 'The administrator paused new generation jobs',
    '等待可用的模型或算力节点': 'Waiting for an available model or worker',
    '展开 / 收起排队窗口': 'Expand / collapse queue window',
    '任务完成': 'Task complete',
    '批量管理': 'Bulk admin',
    '修改偏好': 'Update preference',
    '超限拒绝': 'Limit denied',
    '功能关闭': 'Feature denied',
    '账号操作失败': 'Account action failed',
    '操作': 'Action',
    '后 台': 'Admin',
    '管理员后台': 'Admin console',
    '系统设置': 'System settings',
    '监控告警': 'Monitoring alerts',
    '信息': 'Info',
    '健康': 'Healthy',
    '注意': 'Attention',
    '异常': 'Degraded',
    '严重': 'Critical',
    'GPU 被其他程序占用': 'GPU busy outside this app',
    'GPU 温度过高': 'GPU temperature high',
    '任务队列积压': 'Job queue backlog',
    'ComfyUI 不在线': 'ComfyUI offline',
    '算力节点离线': 'Compute node offline',
    '算力节点心跳变慢': 'Compute node heartbeat late',
    '任务运行时间过长': 'Job running too long',
    '任务失败率偏高': 'High job failure rate',
    '磁盘空间不足': 'Low disk space',
    'HTTPS 证书即将过期': 'HTTPS certificate expiring',
    '警告': 'Warning',
    '错误': 'Errors',
    '排队': 'Queue',
    '派发 / 准备': 'Dispatch / prepare',
    '采样 / 执行': 'Sampling / execute',
    '>10 年': '>10 years',
    '通过': 'Passed',
    '检查项': 'Checks',
    '检查结果': 'Results',
    '活动告警': 'Active alerts',
    '最近历史': 'Recent history',
    '目前没有活动告警。': 'No active alerts.',
    '还没有告警历史。': 'No alert history yet.',
    '最近任务': 'Recent jobs',
    '还没有任务。': 'No jobs yet.',
    '最近 24 小时': 'Last 24 hours',
    '最近 7 天': 'Last 7 days',
    '运行 / 排队': 'Running / queued',
    '节点在线': 'Workers online',
    '磁盘剩余': 'Disk free',
    '证书剩余': 'Certificate',
    '当前告警': 'Current alerts',
    '没有活动告警。': 'No active alerts.',
    '最近 12 小时出图': 'Images in the last 12 hours',
    '刷新监控': 'Refresh monitor',
    '没有发现明显问题': 'No obvious problems',
    '每日增长': 'Daily growth',
    '预计可用': 'Estimated runway',
    '最近 7 天增长': '7-day growth',
    '占用最多的账号': 'Top accounts',
    '节点遥测': 'Worker telemetry',
    '还没有局域网节点。': 'No LAN workers yet.',
    '还没有局域网节点。管理员后台生成接入码后，在另一台机器运行 worker_agent。':
      'No LAN workers yet. Generate an access code in the admin console, then run worker_agent on the other PC.',
    '刷新遥测': 'Refresh telemetry',
    '确认': 'Acknowledge',
    '已恢复': 'Resolved',
    '触发': 'Triggered',
    '刷新告警': 'Refresh alerts',
    '重新诊断': 'Run diagnostics again',
    '刷新趋势': 'Refresh trends',
    '查看时间线': 'View timeline',
    '总耗时': 'Total time',
    '尝试': 'Attempt',
    '重试': 'Retries',
    '温度': 'Temp',
    '最近耗时': 'Recent durations',
    '最近没有失败或取消的任务。': 'No recent failed or cancelled jobs.',
    '没有错误信息': 'No error details',
    '还没有任务记录。': 'No job records yet.',
    '45 秒内没有新事件。': 'No new events in the last 45 seconds.',
    '重新统计': 'Recount',
    '只做预测，不会自动删除文件。需要连图片备份请用备份数据.bat。':
      'Forecast only; files are not deleted automatically. For full backups, run 备份数据.bat.',
    '阈值和 Webhook 在平面端「后台 → 系统设置 → 监控告警」。':
      'Thresholds and webhook are under "Admin → System settings → Monitoring alerts" in the main app.',
    'ComfyUI 连接': 'ComfyUI connection',
    '底模文件': 'Checkpoint files',
    'Anima 三件套': 'Anima components',
    'Wan 视频模型': 'Wan video models',
    '自定义节点': 'Custom nodes',
    '磁盘空间': 'Disk space',
    'HTTPS 证书': 'HTTPS certificate',
    '临时上传文件': 'Temporary uploads',
    '翻译组件': 'Translation components',
    'ComfyUI 版本': 'ComfyUI version',
    '正常': 'OK',
    '告警阈值、Webhook 和 Prometheus 指标；星图告警中心会读取这些设置。':
      'Alert thresholds, webhook and Prometheus metrics used by the star map alert center.',
    '启用告警': 'Enable alerts',
    'GPU 告警 %': 'GPU alert %',
    'GPU 温度 °C': 'GPU temp °C',
    '队列积压': 'Queue backlog',
    '节点离线秒数': 'Worker offline seconds',
    '节点严重离线秒数': 'Worker critical offline seconds',
    '失败率 %': 'Error rate %',
    '最少任务数': 'Minimum jobs',
    '磁盘剩余 GB': 'Disk free GB',
    '证书剩余天数': 'Certificate days left',
    '任务卡住分钟': 'Stuck job minutes',
    'Webhook 冷却秒': 'Webhook cooldown seconds',
    '启用 Webhook': 'Enable webhook',
    'Webhook 地址': 'Webhook URL',
    '测试 Webhook': 'Test webhook',
    '启用 Prometheus': 'Enable Prometheus',
    'Metrics Token': 'Metrics token',
    '生成新 Token': 'Generate new token',
    '清除 Token': 'Clear token',
    '保存监控设置': 'Save monitoring settings',
    '告警只发送状态信息，不含提示词或图片。Webhook 和 Metrics 都是可选的。':
      'Alerts contain status only, never prompts or images. Webhook and metrics are optional.',
    '告警只发送状态信息，不含提示词或图片。':
      'Alerts contain status only, never prompts or images.',
    '留空不修改': 'Leave blank to keep',
    '2~32 位字母数字._-': '2–32 letters, digits, . _ -',
    '至少 6 位': 'At least 6 characters',
    'D:\\下载\\model.safetensors': 'D:\\Downloads\\model.safetensors',
    '商用授权': 'Commercial license',
    '商用版绑定机器码；分享版不需要激活。授权到期前可以在这里打开激活页续期。':
      'The Commercial edition is bound to a machine code; the Share edition needs no activation. Open the activation page here to renew before expiry.',
    '激活 / 续期': 'Activate / renew',
    '一键体检': 'Health report',
    '自动磁盘清理': 'Automatic disk cleanup',
    '默认关闭。开启后只清理超过保留天数、且没有被收藏的旧图库文件；磁盘剩余低于阈值才动手。':
      'Off by default. When enabled, only old non-favorited gallery files beyond the retention period are removed, and only when free space drops below the threshold.',
    '启用自动清理': 'Enable automatic cleanup',
    '保留天数': 'Retention days',
    '低于剩余 GB 时触发': 'Trigger below free GB',
    '清理到剩余 GB': 'Clean up to free GB',
    '单次最多文件': 'Max files per run',
    '包含视频': 'Include videos',
    '同时清理 ComfyUI/output 原始输出':
      'Also clean raw output in ComfyUI/output',
    '保存清理设置': 'Save cleanup settings',
    '立即清理一次': 'Clean up now',
    '收藏的图片永远不会被自动清理。':
      'Favorited images are never removed automatically.',
    '模型管理': 'Model management',
    '查看已装模型；支持浏览器上传、从服务器路径导入，删除先放进回收站。':
      'View installed models; upload from the browser, import from a server path, or move deleted files to trash.',
    '刷新模型': 'Refresh models',
    '分类': 'Category',
    '选择模型文件（可多选）': 'Choose model files (multiple allowed)',
    '上传到本机': 'Upload to this PC',
    '服务器路径': 'Server path',
    '移动源文件（不勾选则复制）':
      'Move source file (copy if unchecked)',
    '从路径导入': 'Import from path',
    '模型文件不会经过 ComfyUI 下载器；导入后刷新页面即可在出图模型里选择。正在被任务使用的模型不能删除；如果 ComfyUI 仍列着已删除的模型，重启 ComfyUI 后刷新。':
      'Models bypass the ComfyUI downloader; refresh the page after import to use them. Models in use by a job cannot be deleted; restart ComfyUI if a deleted model still appears.',
    '要搬到另一台电脑：运行安装目录的「打包到U盘.bat」，或在「模型下载.bat」里选择「另一台电脑」。':
      'To move to another PC, run "Build USB bundle.bat" in the install folder, or choose "another PC" in the model downloader.',
    '模型回收站': 'Model trash',
    '删除的模型先放这里，7 天内可恢复；恢复前不会重新下载。':
      'Deleted models stay here for 7 days and can be restored without downloading again.',
    '清空回收站': 'Empty trash',
    '这个分类还没有模型': 'No models in this category',
    '使用中': 'In use',
    '删除': 'Delete',
    '恢复': 'Restore',
    '彻底删除': 'Delete forever',
    '回收站是空的': 'Trash is empty',
    '打包下载': 'Download ZIP',
    '已设置，留空不修改': 'Set; leave blank to keep it',
    '还没设置': 'Not set',
    '监控设置已保存': 'Monitoring settings saved',
    '正在发送测试…': 'Sending test…',
    '测试消息已发送': 'Test message sent',
    '发送失败：': 'Send failed: ',
    '新 Token 已生成，请现在复制：': 'New token generated; copy it now: ',
    'Metrics Token 已清除': 'Metrics token cleared',
    '用户名': 'Username',
    '本地翻译模型与系统维护': 'Local translation and system maintenance',
    '商用授权、本地翻译与系统维护':
      'Commercial license, local translation and system maintenance',
    '账号管理': 'Account management',
    '创建普通账号或 24 小时游客；下方可搜索、勾选并批量修改限额。':
      'Create normal or 24-hour guest accounts; search, select and bulk-edit limits below.',
    '普通账号可以由管理员继续调整限额和功能':
      'Admins can adjust limits and features after creation',
    '正在创建…': 'Creating…',
    '请填写用户名和密码': 'Enter username and password',
    '账号已创建：': 'Account created: ',
    '创建': 'Create',
    '算力节点': 'Compute nodes',
    '本机 + 局域网 worker；管理员逐台审批，普通账号只能使用可信且在白名单里的节点。':
      'This PC plus LAN workers. Admins approve each worker; normal accounts can only use trusted allowlisted nodes.',
    '刷新节点': 'Refresh nodes',
    '生成接入码': 'Create join code',
    '生成节点部署包': 'Build worker bundle',
    '正在扫描模型和节点，生成部署包…': 'Scanning models and nodes; building bundle…',
    '部署包已生成，已开始下载。': 'Bundle generated; download started.',
    '生成失败：': 'Build failed: ',
    '启用远程算力': 'Enable remote compute',
    '本机接单': 'Local accepting',
    '默认关闭远程，先审批节点再打开。':
      'Remote is off by default; approve a node before enabling it.',
    '还没有算力节点。点「生成接入码」，在另一台机器上运行 worker_agent。':
      'No compute nodes yet. Create a join code and run worker_agent on another machine.',
    '接入算力节点': 'Join a compute node',
    '接入码无效': 'Invalid join code',
    '接入码已过期': 'Join code expired',
    '接入码已经被使用': 'Join code already used',
    '接入码一次性有效，15 分钟内使用':
      'The join code is single-use and valid for 15 minutes',
    '复制命令': 'Copy command',
    '命令已复制': 'Command copied',
    '我的算力节点': 'My compute nodes',
    '暂停后不再接收新任务，当前任务会继续跑完。':
      'Paused nodes take no new jobs; the current job finishes.',
    '审批算力节点': 'Approve worker',
    '编辑算力节点': 'Edit worker',
    '审批后才会接单': 'The worker only takes jobs after approval',
    '节点名称': 'Node name',
    '所有者': 'Owner',
    '可信节点': 'Trusted node',
    '普通账号的提示词可以被发送到这台机器':
      'Prompts from normal accounts may be sent to this machine',
    '允许使用这台节点的账号': 'Accounts allowed to use this node',
    '管理员始终可以使用；普通账号需要“可信 + 在白名单内”。':
      'Admins always have access; normal accounts need Trusted plus the allowlist.',
    '保存并批准': 'Save and approve',
    '还没有普通账号。管理员始终可以使用。':
      'No normal accounts yet. Admins always have access.',
    '本机槽位': 'Local slot',
    '本机接单中': 'Local accepting',
    '本机已停用': 'Local disabled',
    '停用': 'Disabled',
    'ComfyUI 未运行': 'ComfyUI offline',
    '待审批': 'Pending',
    '已拒绝': 'Rejected',
    '已撤销': 'Revoked',
    '已暂停': 'Paused',
    '离线': 'Offline',
    '忙碌': 'Busy',
    '未就绪': 'Not ready',
    '可信': 'Trusted',
    '所有者暂停': 'Owner paused',
    '当前任务：': 'Current job: ',
    '上次错误：': 'Last error: ',
    '模型清单与中央一致': 'Models match central',
    '缺模型：': 'Missing models: ',
    '节点已保存': 'Worker saved',
    '节点已移除': 'Worker removed',
    '已请求刷新模型清单': 'Inventory refresh requested',
    '节点已暂停': 'Worker paused',
    '节点已恢复': 'Worker resumed',
    '节点': 'Node',
    '在线': 'Online',
    '暂停': 'Paused',
    '已停用': 'Disabled',
    '本机': 'This PC',
    '接单中': 'Accepting',
    '远程算力': 'Remote compute',
    '已启用': 'Enabled',
    '已关闭': 'Off',
    'ComfyUI 在线': 'ComfyUI online',
    'ComfyUI 离线': 'ComfyUI offline',
    '节点权限': 'Node permissions',
    '节点模型清单': 'Node model inventory',
    '本机 + 局域网 worker；管理员逐台审批，显示在线、GPU、模型清单和当前任务。普通账号看不到管理面板。':
      'This PC plus LAN workers. Admins approve each node and see online state, GPU, models and current job; normal accounts cannot open this panel.',
    '每台节点有 owner、可信开关和账号白名单；普通账号只能使用“可信 + 白名单内”的节点，管理员不受限。':
      'Each node has an owner, trusted switch and account allowlist. Normal accounts can only use trusted allowlisted nodes; admins are unrestricted.',
    'worker 上报本机 ComfyUI 的底模、LoRA、VAE 和节点类；中央按文件名匹配，缺模型/缺节点不会派过去。':
      'Workers report their ComfyUI checkpoints, LoRAs, VAEs and node classes. Central matches by filename and will not dispatch jobs to a node missing models or nodes.',
    '算力节点面板仅管理员可看。普通账号只能在自己的任务详情里看到节点名称。':
      'The compute node panel is admin-only. Normal accounts only see the node name on their own jobs.',
    '还没有局域网节点。管理员后台生成接入码后，在另一台机器运行 worker_agent。':
      'No LAN nodes yet. Create a join code in the admin console and run worker_agent on another machine.',
    '管理员算力节点：本机 + 局域网 worker，包含审批、可信、白名单、暂停、模型清单和当前任务。':
      'Admin compute nodes: this PC plus LAN workers, including approval, trust, allowlist, pause, model inventory and current job.',
    '节点所有者查看/暂停自己的算力节点；不能管理别人的节点。':
      'Node owners can view and pause their own nodes; they cannot manage other owners’ nodes.',
    'worker 接入前探测中央协议、HTTPS 和证书指纹；只允许本机 + 热点网段。':
      'A worker probes central protocol, HTTPS and certificate fingerprint before joining; only loopback and the hotspot subnet are allowed.',
    'worker 用一次性接入码注册，返回 worker_id 和 secret；待管理员审批。':
      'A worker registers with a one-time join code and receives a worker_id and secret, then waits for admin approval.',
    'worker 心跳：在线状态、GPU/模型清单、当前任务和取消指令。':
      'Worker heartbeat: online state, GPU/model inventory, current job and cancel commands.',
    'worker 长轮询领取图片任务；中央只把任务派给已批准、可信且模型匹配的节点。':
      'Workers long-poll for image jobs; central only dispatches to approved, trusted nodes with matching models.',
    '节点数据读取失败：': 'Worker data failed: ',
    '移除这个算力节点？正在跑的任务会失败。':
      'Remove this worker? Its current job will fail.',
    '管理员后台：统计数据和批量操作': 'Admin console: stats and bulk actions',
    '账号、图片、流量、GPU 和任务队列一览；勾选账号后可批量操作。':
      'Accounts, images, traffic, GPU and jobs at a glance; select accounts for bulk actions.',
    '搜索账号 / 显示名…': 'Search accounts / display name…',
    '清除选择': 'Clear selection',
    '启用选中': 'Enable selected',
    '禁用选中': 'Disable selected',
    '删除选中': 'Delete selected',
    '批量限额 / 功能': 'Bulk limits / features',
    '功能开关': 'Feature switches',
    '应用到选中': 'Apply to selected',
    '没有匹配的账号。': 'No matching accounts.',
    '「批量限额 / 功能」里留空的字段不会修改；功能可以分别选择「不变 / 开启 / 关闭」。':
      'Empty fields in Bulk limits / features are left unchanged; each feature can be set to Unchanged / On / Off.',
    '当前登录账号不能被批量禁用或删除。':
      'The signed-in account cannot be bulk-disabled or deleted.',
    '个人设置': 'Personal settings',
    '账户偏好': 'Account preference',
    '默认主页': 'Default home',
    '传统平面工作台': 'Flat Dashboard',
    '沉浸式 3D 星图': 'Immersive 3D Star Map',
    '熟悉的工作台，适合新手': 'Familiar dashboard, friendly for new users',
    '登录后直接进入星图': 'Go straight to the star map after login',
    '保存后，下次登录会自动进入这里。新账号默认进入平面工作台。':
      'After saving, you will land here on your next login. New accounts start on the flat dashboard.',
    '提示词翻译': 'Prompt translation',
    'Argos 离线翻译': 'Argos offline translation',
    '轻量、稳定，默认方式': 'Light, stable and the default',
    '本地大模型翻译': 'Local LLM translation',
    '需要管理员先配置本地模型': 'The admin must configure a local model first',
    '中文提示词会按这里选择的方式翻成英文。':
      'Chinese prompts are translated to English using this choice.',
    '本地翻译未启用；中文提示词仍使用 Argos。':
      'Local translation is off; Chinese prompts still use Argos.',
    '管理员还没有启用本地翻译模型': 'The admin has not enabled a local translation model',
    '本地翻译模型': 'Local translation model',
    '接入 Ollama 或 OpenAI 兼容的本地小模型；普通账号可在个人设置里自己选择是否使用。':
      'Connect an Ollama or OpenAI-compatible local model; normal accounts can opt in from personal settings.',
    '启用本地翻译': 'Enable local translation',
    '接口': 'API type',
    'OpenAI 兼容（LM Studio / llama.cpp / vLLM）':
      'OpenAI-compatible (LM Studio / llama.cpp / vLLM)',
    '地址': 'Address',
    '模型名': 'Model name',
    'API Key（可选）': 'API key (optional)',
    '留空表示不修改': 'Leave blank to keep it',
    '超时秒数': 'Timeout (seconds)',
    '清除已保存密钥': 'Clear saved key',
    '保存并测试': 'Save and test',
    '只允许本机或内网地址，避免把提示词发到公网。':
      'Only loopback or LAN addresses are allowed, so prompts are not sent to the public internet.',
    '已保存': 'Saved',
    '正在保存…': 'Saving…',
    '连接成功：': 'Connected: ',
    '连接失败：': 'Connection failed: ',
    '已启用 · 用户可在个人设置中选择':
      'Enabled · users can opt in from personal settings',
    '尚未启用；用户继续使用 Argos':
      'Not enabled; users keep using Argos',
    '可选': 'Optional',
    '已保存，留空不修改': 'Saved; leave blank to keep it',
    '系统维护': 'System maintenance',
    '一键生成配置还原点；回滚只恢复账号、节点、用量、任务状态和翻译设置，不动图片、模型和证书。':
      'Create a config restore point; rollback only restores accounts, nodes, usage, job state and translation settings, never images, models or certificates.',
    '创建还原点': 'Create restore point',
    '系统重置': 'System reset',
    '还没有还原点。建议在改账号/限额前先创建一个。':
      'No restore points yet. Create one before changing accounts or limits.',
    '回滚到这个点': 'Roll back to this point',
    '正在创建还原点…': 'Creating restore point…',
    '还原点已创建': 'Restore point created',
    '正在回滚…': 'Rolling back…',
    '已回滚到还原点': 'Rolled back',
    '已回滚，当前账号不再有效，请重新登录。':
      'Rolled back; the current account is no longer valid. Please sign in again.',
    '保留当前管理员和图片，清空其他账号、任务、用量和算力节点':
      'Keep the current admin and images; clear other accounts, jobs, usage and compute nodes',
    '重置前会自动创建还原点，可以在「系统维护」里一键回滚。图片、模型、证书和日志不会被删除。':
      'A restore point is created automatically before reset. Images, models, certificates and logs are not deleted. You can roll back from System maintenance.',
    '输入 RESET 确认': 'Type RESET to confirm',
    '确认重置': 'Confirm reset',
    '请输入 RESET 确认': 'Type RESET to confirm',
    '正在重置…': 'Resetting…',
    '系统已重置；图片和当前管理员保留。':
      'System reset; images and the current admin are kept.',
    '生成 24 小时游客': 'Create 24h guest',
    '24 小时游客账号': '24-hour guest account',
    '只显示一次，请现在复制给访客': 'Shown once; copy it to the guest now',
    '到期': 'Expires',
    '游客默认每天 60 张、不能视频/放大/挂机；到期自动禁用并踢下线，图片保留。':
      'Guests get 60 images/day and no video, upscale or auto-run. Expired guests are disabled and signed out; their images are kept.',
    '复制账号密码': 'Copy username and password',
    '游客账号已创建': 'Guest account created',
    '游客账号已续期 24 小时': 'Guest renewed for 24 hours',
    '已复制': 'Copied',
    '续期 24h': 'Renew 24h',
    '当前没有可用的中文翻译方式。请直接用英文提示词，或让管理员启用本地翻译模型。':
      'No Chinese translation is available. Use English prompts or ask the admin to enable a local translation model.',
    '负面提示词是中文，但当前账号没有可用的翻译方式。请改用英文，或在个人设置里选择本地翻译模型。':
      'The negative prompt is Chinese and no translation method is available. Use English or choose a local model in personal settings.',
    '这台机器没有安装中文翻译组件，也没有启用本地翻译模型。请直接用英文提示词。':
      'This machine has neither Argos nor a local translation model. Please use English prompts.',
    '只有管理员可以设置翻译模型': 'Only admins can configure the translation model',
    '只有管理员可以进行系统维护': 'Only admins can perform system maintenance',
    '本地翻译模型未启用或未配置': 'The local translation model is not enabled or configured',
    '修改密码': 'Change password',
    '当前密码': 'Current password',
    '新密码（至少 8 位）': 'New password (at least 8 characters)',
    '再输一次新密码': 'Repeat new password',
    '修改后当前登录保持有效；其他设备下次登录要用新密码。':
      'This session stays signed in; other devices must use the new password next time.',
    '请填写当前密码和新密码': 'Enter the current and new password',
    '新密码至少 8 位': 'New password must be at least 8 characters',
    '两次新密码不一致': 'New passwords do not match',
    '密码已修改': 'Password changed',
    '修改失败：': 'Change failed: ',
    '当前密码不对': 'Current password is incorrect',
    '新密码不能和当前密码一样': 'New password must differ from the current one',
    '出图完成提醒': 'Completion notifications',
    '开启浏览器通知': 'Enable browser notifications',
    '通知已开启 · 点此关闭': 'Notifications on · tap to disable',
    '这个浏览器不支持通知': 'Notifications are not supported',
    '开启后，页面在后台时出图完成会弹系统通知。':
      'When enabled, a system notification appears if generation finishes while the page is in the background.',
    '出图完成': 'Image ready',
    '可以回来看结果了。': 'Open the page to see the result.',
    '关闭窗口': 'Close window',
    '关 闭': 'Close',
    '出图完成，可以查看结果。': 'Your image is ready.',
    '还有 ': 'More: ',
    ' 个任务': ' jobs',
    '实时活动已连接': 'Live activity connected',
    '实时活动未连接': 'Live activity disconnected',
    '缩小': 'Zoom out',
    '放大视图': 'Zoom in',
    '暂停 / 继续自动旋转': 'Pause / resume auto-rotate',
    '开启后拖动星球调整位置': 'Enable to drag planets and arrange them',
    '在星图里输入提示词并生成': 'Enter a prompt and generate in the star map',
    '生成预览': 'Generation preview',
    '生成结果': 'Generation result',
    '按生成顺序看：输入 → 理解 → 模型 → 生成 → 任务 → 输出；图生图 / 视频 / 放大单独标成支线':
      'View in generation order: Input → Understand → Model → Generate → Task → Output; image-to-image, video and upscale are separate branches.',
    '旁支': 'Branch',
    '切换到中文': 'Switch to Chinese',
    '写提示词、调参数、生成图片': 'Write prompts, tune parameters, generate images',
    '看历史作品、收藏、删除': 'Browse history, favorites and deletion',
    '查看谁在用、做了什么、安全事件': 'See who is online, what they did, and security events',
    '只写文字，凭空生成一张图': 'Text only; generate an image from scratch',
    '传一张图，照着它的构图和风格改': 'Upload an image and redraw its composition/style',
    '写一句话，生成 1~3 秒的小视频': 'Write a prompt to generate a 1–3s video',
    '写一句话，生成 1~3s的小视频': 'Write a prompt to generate a 1–3s video',
    '传一张图，让它动起来': 'Upload an image and animate it',
    '用中文描述你想画的画面...': 'Describe the scene… Chinese is fine',
    'Tag 知识最全，冷门角色/画师最准。v-pred 模型，只用 Euler，30 步 / CFG 4.5。':
      'Best tag knowledge; most accurate for obscure characters/artists. v-pred model; Euler only, 30 steps / CFG 4.5.',
    'XI v11：手、脸、构图和提示词都更强。自动横图，DPM++ 2M，30 步 / CFG 5。':
      'XI v11: stronger hands, faces, composition and prompt adherence. Auto landscape, DPM++ 2M, 30 steps / CFG 5.',
    '老牌动漫模型，SDXL 的 LoRA 最多；想加 LoRA 就用它。':
      'Classic anime model with the largest SDXL LoRA ecosystem; use it when adding LoRAs.',
    '写实人像和照片，8 步就出图，速度最快。':
      'Photoreal portraits and photos; 8 steps, fastest.',
    '很老的 SD1.5 模型，现在基本用不到，可以删掉腾空间。':
      'Very old SD1.5 model; rarely useful now, can be deleted to free space.',
    '点选词语，拼成一段提示词': 'Tap words to build a prompt',
    '随机抽一个完整的画面点子': 'Draw a complete random scene idea',
    '查看模型实际收到的英文': 'See the English the model actually receives',
    '从历史里随机换一条提示词': 'Swap in a random prompt from history',
    '找回以前写过的提示词': 'Recover prompts you wrote before',
    '同一句提示词，两个模型各画一张': 'Draw the same prompt with two models',
    '步数、CFG、LoRA、高清修复等高级设置':
      'Steps, CFG, LoRA, hires fix and other advanced settings',
    '留空自动生成': 'Leave empty to randomize',
    '留空用 Anima 默认负面词（worst quality, score_1/2/3 …）':
      'Leave empty to use Anima default negatives (worst quality, score_1/2/3 …)',
    '留空用默认': 'Leave empty for default',
    '搜索提示词关键词…': 'Search prompt keywords…',
    '搜索用户 / 动作 / 模型 / IP…': 'Search user / action / model / IP…',
    '输入中文名或英文标签，例如 初音未来':
      'Enter a Chinese name or English tag, e.g. Hatsune Miku',
    '视频生成': 'Video generation',
    '上传参考图': 'Upload reference',
    '图库浏览': 'Browse gallery',
    '团队与共享': 'Teams and sharing',
    '共享图库视图和提示词库；默认仍按账号隔离':
      'Shared gallery view and prompt library; account isolation stays the default.',
    '新团队名称': 'New team name',
    '创建团队': 'Create team',
    '团队管理': 'Teams',
    '个人图库': 'Personal',
    '所有者': 'Owner',
    '编辑者': 'Editor',
    '只读': 'Viewer',
    '成员': 'Members',
    '添加成员': 'Add member',
    '移除': 'Remove',
    '共享提示词': 'Shared prompts',
    '还没有共享提示词。': 'No shared prompts yet.',
    '使用': 'Use',
    '删除': 'Delete',
    '写一条团队共享提示词…': 'Write a shared prompt…',
    '添加共享提示词': 'Add shared prompt',
    '查看团队图库': 'Open team gallery',
    '删除团队': 'Delete team',
    '还没有团队。创建一个团队后，可以把成员的个人图库聚合到这里。':
      'No teams yet. Create one to aggregate members\' personal galleries.',
    '账号名': 'Username',
    '团队读取失败：': 'Team load failed: ',
    '共享提示词读取失败：': 'Shared prompts failed: ',
    '先写团队名称': 'Enter a team name',
    '删除这个团队？图片仍保留在各自账号里。':
      'Delete this team? Images stay in each account.',
    '登录设备': 'Signed-in devices',
    '正在读取登录设备…': 'Loading devices…',
    '刷新设备': 'Refresh devices',
    '退出其他设备': 'Sign out other devices',
    '当前设备': 'This device',
    '退出': 'Sign out',
    '未知设备': 'Unknown device',
    '手机': 'Mobile',
    '桌面': 'Desktop',
    '没有登录记录。': 'No sessions.',
    '登录设备读取失败：': 'Session load failed: ',
    '退出这个设备？': 'Sign this device out?',
    '退出除当前设备外的所有登录？': 'Sign out all other devices?',
    '导出用量 CSV': 'Export usage CSV',
    '任务状态通知': 'Job status notifications',
    '自定义节点': 'Custom nodes',
    '导入 ComfyUI 自定义节点 ZIP 或服务器目录；只保存和检查，重启 ComfyUI 后才会加载。':
      'Import a custom node ZIP or server folder; it is only stored and checked until ComfyUI restarts.',
    '刷新节点': 'Refresh nodes',
    '体检节点': 'Check nodes',
    '节点 ZIP': 'Node ZIP',
    '上传并导入': 'Upload and import',
    '覆盖同名节点（旧版本移到回收站）':
      'Replace same-name node (old version moves to trash)',
    '从路径导入': 'Import from path',
    '工作流库': 'Workflow library',
    '导入 ComfyUI 工作流 JSON（UI 或 API prompt 格式），检查缺失节点、缺失模型、断链和循环依赖。':
      'Import ComfyUI workflow JSON (UI or API prompt) and check missing nodes, models, links and cycles.',
    '刷新工作流': 'Refresh workflows',
    '体检工作流': 'Check workflows',
    '工作流 JSON（可多选）': 'Workflow JSON (multiple)',
    '导入文件': 'Import files',
    '正常': 'OK',
    '未体检': 'Not checked',
    '体检': 'Check',
    '下载': 'Download',
    '缺少依赖：': 'Missing deps: ',
    '语法错误：': 'Syntax errors: ',
    '缺少 __init__.py': 'Missing __init__.py',
    '没有找到 NODE_CLASS_MAPPINGS': 'No NODE_CLASS_MAPPINGS found',
    '删除这个自定义节点？会移到 _node_trash，重启 ComfyUI 后不再加载。':
      'Delete this custom node? It moves to _node_trash and stops loading after restart.',
    '节点已移入回收站，重启 ComfyUI 后生效。':
      'Node moved to trash; restart ComfyUI.',
    '工作流库还是空的。': 'The workflow library is empty.',
    '还没有自定义节点。到平面端后台 → 自定义节点导入。':
      'No custom nodes yet. Import one in Admin → Custom nodes.',
    '工作流库还是空的。到平面端后台 → 工作流库导入。':
      'The workflow library is empty. Import one in Admin → Workflow library.',
    '重新体检': 'Check again',
    '连线': 'links',
    '缺节点 ': 'Missing nodes ',
    '缺模型 ': 'Missing models ',
    '断链 ': 'Broken links ',
    '语法错误：': 'Syntax errors: ',
    '条连线': 'links',
    '缺少节点：': 'Missing nodes: ',
    '缺少模型：': 'Missing models: ',
    '断链：': 'Broken links: ',
    '删除这个工作流条目？原始文件不会被改。':
      'Delete this workflow entry? The source file is untouched.',
    '已删除': 'Deleted',
    '体检完成': 'Check complete',
    '体检完成：正常 ': 'Check complete: OK ',
    '正在上传…': 'Uploading…',
    '正在上传… ': 'Uploading… ',
    '导入完成，重启 ComfyUI 后生效。': 'Imported; restart ComfyUI.',
    '节点已导入，重启 ComfyUI 后生效。': 'Node imported; restart ComfyUI.',
    '工作流已导入并完成体检。': 'Workflow imported and checked.',
    '导入完成：': 'Imported: ',
    'ZIP 文件数超过上限': 'ZIP has too many files',
    'ZIP 包含绝对路径': 'ZIP contains an absolute path',
    'ZIP 包含路径穿越': 'ZIP contains path traversal',
    'ZIP 包含符号链接': 'ZIP contains a symlink',
    'ZIP 包含加密文件': 'ZIP contains an encrypted file',
    'ZIP 解压后体积超过上限': 'ZIP expands beyond the size limit',
    'ZIP 是空的': 'ZIP is empty',
    'ZIP 文件不存在': 'ZIP file not found',
    'ZIP 大小超出限制（最大 200MB）': 'ZIP exceeds the 200 MB limit',
    '没有找到 __init__.py；请上传 ComfyUI 自定义节点目录或 ZIP':
      'No __init__.py found; upload a ComfyUI custom node folder or ZIP',
    'custom_nodes 里已经有同名节点': 'A node with the same name already exists',
    '源路径不存在': 'Source path not found',
    '只支持目录或 ZIP 文件': 'Only a folder or ZIP is supported',
    '源路径不是目录': 'Source path is not a folder',
    '节点不存在': 'Node not found',
    '节点名称不合法': 'Invalid node name',
    '节点目录体积超过上限': 'Node folder exceeds the size limit',
    '节点目录体积或文件数超过上限': 'Node folder exceeds the size/file limit',
    '节点目录包含符号链接': 'Node folder contains a symlink',
    '上传未完成': 'Upload is incomplete',
    '数据块顺序不对，请重新上传': 'Chunk order is wrong; upload again',
    '工作流文件超过 8MB': 'Workflow file exceeds 8 MB',
    '工作流不存在': 'Workflow not found',
    '工作流没有节点': 'Workflow has no nodes',
    '节点数量超过上限': 'Too many nodes',
    'ComfyUI 不在线，节点类型未校验':
      'ComfyUI is offline; node types were not checked',
    '开始时通知': 'Notify on start',
    '完成时通知': 'Notify on completion',
    '失败时通知': 'Notify on failure',
    '队列状态': 'Queue status',
    '槽位': 'Slots',
    '最长等待': 'Max wait',
    '正常接单': 'Accepting jobs',
    '账号队列': 'Account queues',
    '暂停接单': 'Pause intake',
    '恢复接单': 'Resume intake',
    '团队 / 项目': 'Teams / projects',
    '个团队': 'teams',
    '名成员': 'members',
    '条共享提示词': 'shared prompts',
    '还没有团队。到平面端图库 → 团队管理创建。':
      'No teams yet. Create one in Gallery → Teams.',
    '个会话': 'sessions',
    '团队不存在': 'Team not found',
    '你不在这个团队里': 'You are not in this team',
    '只有团队所有者可以管理': 'Only the team owner can manage this',
    '只读成员不能添加提示词': 'Viewers cannot add prompts',
    '没有权限查看这个团队': 'No permission to view this team',
    '没有权限访问这个团队': 'No permission to access this team',
    '团队名称不能为空': 'Team name cannot be empty',
    '团队数量到上限了': 'Team limit reached',
    '团队成员到上限了': 'Member limit reached',
    '共享提示词到上限了': 'Shared prompt limit reached',
    '提示词不能为空': 'Prompt cannot be empty',
    '只能删除自己添加的提示词': 'You can only delete your own prompts',
    '提示词不存在': 'Prompt not found',
    '成员不存在': 'Member not found',
    '所有者角色不能修改': 'The owner role cannot be changed',
    '不能移除团队所有者': 'The team owner cannot be removed',
    '只能查看自己的登录设备': 'You can only view your own devices',
    '只能导出自己的用量': 'You can only export your own usage',
    '队列操作失败：': 'Queue action failed: ',
    '删除图片': 'Delete images',
    '拼图 / 导出': 'Collage / export',
    '提示词已填入': 'Prompt filled',
    '历史已清空（收藏保留）': 'History cleared (favorites kept)',
    '参考图太大（限 15MB）': 'Reference image too large (15MB max)',
    '参考图已就位，出图会以它为底': 'Reference image ready; generation will use it',
    '已移除参考图': 'Reference image removed',
    '连不上电脑上的服务：': 'Cannot reach the local service: ',
    '任务失败': 'Job failed',
    '提示词已填回出图页': 'Prompt filled back on the Generate page',
    '用同样的参数重新出…': 'Regenerating with the same settings…',
    '失败：': 'Failed: ',
    '先在出图页写上「想画成什么」，再回来涂抹重绘':
      'Write what you want on the Generate page, then return to inpaint',
    '读取原图失败': 'Could not read the original image',
    '正在重绘涂抹的区域…': 'Inpainting the masked area…',
    '正在恢复上次的任务…': 'Restoring the previous job…',
    '只有一种底模，没法对比': 'Only one model is available; cannot compare',
    '正在用两种模型各出一张…': 'Generating one image with each model…',
    '两种模型出图完成': 'Model comparison finished',
    '对比失败：': 'Comparison failed: ',
    '还没有选中图片': 'No images selected',
    '至少选 2 张才能拼图': 'Select at least 2 images to make a collage',
    '正在拼图…': 'Making collage…',
    '拼图失败：': 'Collage failed: ',
    '启动失败：': 'Start failed: ',
    '正在导出带参数的图片…': 'Exporting image with parameters…',
    '导出失败：': 'Export failed: ',
    '这个文件不是图片': 'This file is not an image',
    '参考图已就位。写上「想改成什么样」，点出图。':
      'Reference ready. Describe the change and tap Generate.',
    '已把这张图设为参考图。改改提示词，就能照着它重画。':
      'This image is now the reference. Edit the prompt and regenerate.',
    '读取图片失败：': 'Could not read the image: ',
    '加载底模': 'Load checkpoint',
    'CLIP 跳过层': 'CLIP skip layer',
    'v-pred 采样': 'v-pred sampling',
    'CFG 缩放': 'CFG rescale',
    'PAG 增强': 'PAG boost',
    '一个少女': 'A girl',
    '一只白猫': 'A white cat',
    '一位旅人': 'A traveler',
    '机甲战士': 'Mecha warrior',
    '空无一人的街道': 'Empty street',
    '一栋老房子': 'An old house',
    '樱花树下': 'Under cherry blossoms',
    '雨夜街道': 'Rainy night street',
    '雪山之巅': 'Snowy mountain peak',
    '古老图书馆': 'Ancient library',
    '海边小镇': 'Seaside town',
    '废弃车站': 'Abandoned station',
    '柔和的晨光': 'Soft morning light',
    '黄昏逆光': 'Golden-hour backlight',
    '霓虹灯光': 'Neon lights',
    '皎洁月光': 'Bright moonlight',
    '温暖的烛光': 'Warm candlelight',
    '杰作，最高画质': 'Masterpiece, best quality',
    '精细的背景': 'Detailed background',
    '电影级构图': 'Cinematic composition',
    '超精细细节': 'Ultra-detailed',
    '宁静': 'Calm',
    '神秘': 'Mysterious',
    '温暖': 'Warm',
    '忧郁': 'Melancholy',
    '史诗感': 'Epic',
    '更多设置 ▴': 'More settings ▴',
    '收起 ▴': 'Collapse ▴',
    '· 越长越慢，4s以上容易爆显存': '· Longer is slower; above 4s can run out of VRAM',
    '越长越慢，4 秒以上容易爆显存': 'Longer is slower; above 4s can run out of VRAM',
    '越长越慢，4s以上容易爆显存': 'Longer is slower; above 4s can run out of VRAM',
    '批量勾选、删除或拼图': 'Select, delete or collage images',
    '看一共画了多少张': 'See how many images you have made',
    '重新读取图库': 'Reload the gallery',
    '暂时连不上 ComfyUI 工作流接口，稍后自动重试。':
      'Cannot reach the ComfyUI workflow endpoint; retrying later.',
    '静态预览：从 /universe 打开才能读取 ComfyUI 的实时工作流。':
      'Static preview: open /universe to read the live ComfyUI workflow.',
    '两次 mode=txt': 'Two runs of mode=txt',
    'cron / 每日': 'cron / daily',
    '正常放行': 'Allowed',
    '没有检测到重负载': 'no heavy load detected',
    'GPU 温度': 'GPU temp',
    'GPU 功耗': 'GPU power',
    '显卡': 'GPU',
    '正常放行 没有检测到重负载': 'Allowed · no heavy load detected',
    '1.5s 刷新': 'Refreshes every 1.5s',
    '总任务': 'Total jobs',
    '图库数量': 'Gallery images',
    '占用空间': 'Storage used',
    '模型数': 'Models',
    '分类': 'Categories',
    '临时输入图': 'temporary input files',
    '闲时应为 0': 'should be 0 when idle',
    '旧上传': 'legacy uploads',

    /* 星图面板 · 词典 / 历史 / 规划 */
    '搜索': 'Search',
    '输入「初音未来」或 hatsune_miku 试试。':
      'Try "Hatsune Miku" or "hatsune_miku".',
    '规划中：这个功能还没有接后端接口和界面，先作为路线图节点展示。':
      'Planned: this feature has no backend endpoint or screen yet; it is shown as a roadmap node.',

    /* 动态单位 / 计数 */
    'records/张': 'images',
    '个任务': 'jobs',
    '个账号': 'accounts',
    '个功能调用': 'callers',
    '个节点': 'nodes',
    '条连线': 'links',
    '个接口': 'APIs',
    '个底模': 'base models',
    '作品': 'works',

    /* 异常恢复 / 守护进程 */
    '异常自动恢复': 'Automatic recovery',
    '守护进程监控 ComfyUI 和网页服务，异常退出自动重启；重启后自动恢复排队任务。':
      'The supervisor watches ComfyUI and the web service, restarts them after a crash, and recovers queued jobs.',
    '启用守护': 'Enable supervisor',
    '自动重启 ComfyUI': 'Restart ComfyUI automatically',
    '自动重启网页服务': 'Restart web service automatically',
    '重启后恢复排队任务': 'Recover queued jobs after restart',
    '重试未提交的运行任务': 'Retry running jobs that were never submitted',
    '每小时最多重启': 'Max restarts per hour',
    '检查间隔秒': 'Check interval (seconds)',
    '保存守护设置': 'Save supervisor settings',
    '守护进程由「一键启动」开启；未开启时这里只保存设置。':
      'The supervisor starts with 一键启动.bat; otherwise these settings are only saved.',
    '守护未运行': 'Supervisor offline',
    '双击「一键启动.bat」会以守护模式运行；设置已保存，下次启动生效。':
      'Start with 一键启动.bat to run in watch mode; saved settings apply next launch.',
    '守护运行中': 'Supervisor running',
    '读取守护状态失败：': 'Could not read supervisor: ',
    '守护设置已保存': 'Supervisor settings saved',
    '本小时重启：ComfyUI ': 'Restarts this hour: ComfyUI ',

    /* 额度提示 */
    '额度已用完': 'Quota reached',
    '现在还不能提交': 'Not ready to submit',
    '暂时不能再提交新任务。': 'You cannot submit a new job right now.',
    '先看看下面的用量，再决定什么时候继续。':
      'Check the usage below before trying again.',
    '去清理图库': 'Open gallery',
    '知道了': 'Got it',
    '今天 24:00 后自动恢复。': 'Resets after midnight tonight.',
    '下个月 1 日后自动恢复。': 'Resets on the 1st of next month.',
    '当前任务结束后自动恢复。': 'Available again when the current job finishes.',
    '可以先清理一些旧图，或联系管理员提高上限。':
      'Delete some old images or ask the admin for a higher limit.',
    '可以把参数调低，或联系管理员提高上限。':
      'Lower the setting or ask the admin for a higher limit.',
    '提示词已清理 ': 'Removed ',
    ' 个不可见字符': ' invisible character(s) from the prompt',
    '提示词超过 ': 'Prompt was truncated to ',
    ' 字，已截断': ' characters',
    '负面提示词已清理 ': 'Removed ',
    '负面提示词超过 ': 'Negative prompt was truncated to '
  });

  /* 动态句子的英文模板（按顺序匹配） */
  var PATTERNS = [
    [/^每日\s*(\d+)\s*张$/, 'Daily $1 images'],
    [/^图库\s*(\d+)\s*张$/, 'Gallery $1 images'],
    [/^存储\s*(\d+)\s*MB$/, 'Storage $1 MB'],
    [/^流量\/日\s*(\d+)\s*MB$/, 'Traffic/day $1 MB'],
    [/^流量\/月\s*(\d+)\s*MB$/, 'Traffic/month $1 MB'],
    [/^游客 · 剩余\s*(\d+)h$/, 'Guest · $1h left'],
    [/^游客 · 已到期$/, 'Guest · expired'],
    [/^1\s*个文件$/, '1 file'],
    [/^1\s*个任务$/, '1 job'],
    [/^1\s*个账号$/, '1 account'],
    [/^1\s*个底模$/, '1 base model'],
    [/^1\s*个节点$/, '1 node'],
    [/^1\s*条连线$/, '1 link'],
    [/^1\s*个接口$/, '1 API'],
    [/^1\s*天$/, '1 day'],
    [/^1\s*条$/, '1 record'],
    [/^目标\s*(.+)$/, 'Target $1'],
    [/^图片\s*(\d+)$/, '$1 images'],
    [/^今日\s*(\d+)$/, '$1 today'],
    [/^存储\s*(.+)$/, 'Storage $1'],
    [/^运行\s*(\d+)$/, '$1 running'],
    [/^本月(?:生成)?\s*(.+?)\s*\/\s*(\d+)\s*个任务$/,
      'This month: $1 / $2 jobs'],
    [/^本月\s*(.+?)\s*\/\s*(\d+)\s*任务$/,
      'This month: $1 / $2 jobs'],
    [/^本月\s*(.+)$/, 'This month $1'],
    [/^请求\s*(\d+)$/, '$1 requests'],
    [/^流量\s*今日\s*([^·]+?)\s*\/\s*本月\s*([^·]+)$/,
      'Traffic today $1 / this month $2'],
    [/^进行中\s*(\d+)$/, '$1 running'],
    [/^旧上传保留\s*(\d+)$/, '$1 legacy uploads kept'],
    [/^临时输入图\s*(\d+)\s*个（闲时应为 0）$/,
      '$1 temporary input files (0 when idle)'],
    [/^最近\s*(\d+)\s*records$/, 'Last $1 records'],
    [/^最多\s*(\d+)\s*records$/, 'Up to $1 records'],
    [/^(\d+)\s*角色$/, '$1 characters'],
    [/^(\d+)\s*作品$/, '$1 works'],
    [/^(\d+)\s*records\/张$/, '$1 images'],
    [/^(\d+)s\s*前$/, '$1s ago'],
    [/^(\d+)\s*个任务$/, '$1 jobs'],
    [/^已选\s*(\d+)\s*个\s*·\s*强度作用于所有选中的 LoRA$/,
      '$1 selected · strength applies to all selected LoRAs'],
    [/^已选\s*(\d+)\s*个\s*·\s*强度作用于所有选中的 LoRA\s*·\s*已隐藏\s*(\d+)\s*个不兼容的 LoRA$/,
      '$1 selected · strength applies to all selected LoRAs · $2 incompatible hidden'],
    [/^已隐藏\s*(\d+)\s*个不属于当前模型家族的 LoRA。$/,
      '$1 LoRAs from other model families are hidden.'],
    [/^GPU\s*(\d+)\s*分\s*(\d+)s$/, 'GPU $1m $2s'],
    [/^GPU\s*(\d+)\s*分$/, 'GPU $1m'],
    [/^排队中\s*(\d+)$/, 'Queued $1'],
    [/^排队第\s*(\d+)\s*位$/, 'Queue #$1'],
    [/^前方\s*(\d+)\s*个任务$/, '$1 jobs ahead'],
    [/^队列\s*(\d+)\s*个任务$/, '$1 jobs in queue'],
    [/^(\d+)s\s*等待$/, '$1s waiting'],
    [/^已等待\s*(\d+)\s*秒$/, '$1s waited'],
    [/^(\d+)\s*个文件$/, '$1 files'],
    [/^排队任务太多了（最多\s*(\d+)\s*个），等前面的跑完再提交。$/,
      'Queue is full ($1 jobs max). Wait for some to finish.'],
    [/^你已经有\s*(\d+)\s*个任务在排队或运行，等完成再提交。$/,
      'You already have $1 queued or running jobs. Wait for one to finish.'],
    [/^没有可取消的任务$/, 'No cancellable jobs'],
    [/^排队超时或已取消$/, 'Queue timed out or cancelled'],
    [/^放大\s*([\d.]+)×$/, 'Upscale $1×'],
    [/^(\d+)\s*条\/张$/, '$1 images'],
    [/^(\d+)\s*个账号$/, '$1 accounts'],
    [/^失败\s*(\d+)\s*个$/, '$1 failed'],
    [/^算力节点缺少模型或工具：(.+)$/,
      'Worker is missing models or tools: $1'],
    [/^任务\s+([0-9A-Za-z_-]+)$/, 'Job $1'],
    [/^远端结果保存失败：(.+)$/, 'Could not save the remote result: $1'],
    [/^参考图读取失败:\s*(.+)$/, 'Could not read the reference image: $1'],
    [/^蒙版读取失败:\s*(.+)$/, 'Could not read the mask: $1'],
    [/^准备参考图失败:\s*(.+)$/, 'Could not prepare the reference image: $1'],
    [/^准备图片失败:\s*(.+)$/, 'Could not prepare the image: $1'],
    [/^节点:\s*(.+)$/, 'Node: $1'],
    [/^节点\s+(.+)$/, 'Node $1'],
    [/^确认告警失败：(.+)$/, 'Could not acknowledge the alert: $1'],
    [/^队列操作失败：(.+)$/, 'Queue action failed: $1'],
    [/^ZIP 包含不允许的文件类型：(.+)$/,
      'ZIP contains a disallowed file type: $1'],
    [/^节点目录包含不允许的文件类型：(.+)$/,
      'Node folder contains a disallowed file type: $1'],
    [/^不是有效的 JSON：(.+)$/, 'Invalid JSON: $1'],
    [/^无法识别工作流格式.*$/, 'Unrecognized workflow format'],
    [/^包含可执行脚本：(.+)$/, 'Executable scripts: $1'],
    [/^缺少 Python 依赖：(.+)$/, 'Missing Python dependencies: $1'],
    [/^缺少依赖：(.+)$/, 'Missing dependencies: $1'],
    [/^缺少节点：(.+)$/, 'Missing nodes: $1'],
    [/^缺少模型：(.+)$/, 'Missing models: $1'],
    [/^断链：(.+)$/, 'Broken links: $1'],
    [/^循环依赖：(.+)$/, 'Cycles: $1'],
    [/^语法错误：(\d+)\s*个文件$/, 'Syntax errors: $1 files'],
    [/^时间线读取失败：(.+)$/, 'Could not load the timeline: $1'],
    [/^翻译失败：(.+)$/, 'Translation failed: $1'],
    [/^GPU 占用\s*(\d+)%$/, 'GPU usage $1%'],
    [/^CPU 占用\s*(\d+)%$/, 'CPU usage $1%'],
    [/^前台程序\s*(.+)\s*占用\s*([\d.]+)%\s*CPU$/,
      'Foreground app $1 is using $2% CPU'],
    [/^检测到你正在大量占用电脑（(.+)），生图已自动暂停。占用降下来后会自动恢复，不用手动设置。$/,
      'Heavy computer load detected ($1). Generation is paused and resumes automatically.'],
    [/^检测到\s*(.+)。新的出图任务会暂时被拦下，占用降下来后自动恢复。$/,
      'Detected $1. New generation jobs are paused until load drops.'],
    [/^图片像素太大（最多\s*(\d+)\s*万像素）$/,
      'Image has too many pixels (max $1 megapixels)'],
    [/^图片单边太长（最多\s*(\d+)\s*像素）$/,
      'Image side is too long (max $1 px)'],
    [/^图片超过\s*(\d+)\s*MB$/, 'Image exceeds $1 MB'],
    [/^管理员暂时关闭了「(.+)」功能。$/,
      'The administrator has disabled "$1" for your account.'],
    [/^种子\s*(.+)$/, 'Seed $1'],
    [/^重绘\s*([\d.]+)$/, 'Denoise $1'],
    [/^时间：(.+)$/, 'Time: $1'],
    [/^绑定\s*(.+)$/, 'Binding $1'],
    [/^端口\s*(\d+)$/, 'Port $1'],
    [/^角色\s*(\S+)$/, 'Role $1'],
    [/^(\d+)\s*个 · 待处理\s*(\d+)$/, '$1 items · $2 pending'],
    [/^(\d+)\s*个底模\s*·\s*视频就绪$/, '$1 base models · video ready'],
    [/^(\d+)\s*个底模\s*·\s*视频未就绪$/, '$1 base models · video not ready'],
    [/^(\d+)\s*步\s*·\s*CFG\s*([\d.]+)\s*·\s*(\S+)$/,
      '$1 steps · CFG $2 · $3'],
    [/^(\d+)\s*步$/, '$1 steps'],
    [/^sampler=(.+?)（强制）$/, 'sampler=$1 (forced)'],
    [/^GET \/system_stats 模型就绪检查$/, 'GET /system_stats model readiness check'],
    [/^already_running\(\)\s*端口\s*(\d+)$/, 'already_running() port $1'],
    [/^([\d.]+)s 刷新$/, 'Refreshes every $1s'],
    [/^(\d+)\s*个账号\s*·\s*本月\s*(.+)$/, '$1 accounts · this month $2'],
    [/^(\d+)\s*个节点\s*(\d+)\s*条连线\s*(\d+)\s*个接口\s*(\d+)\s*个底模\s*·\s*(\d+)\s*个视频模型$/,
      '$1 nodes\n$2 links\n$3 APIs\n$4 base models · $5 video models'],
    [/^([A-Z]+) · (\d+) 个功能调用$/, '$1 · $2 callers'],
    [/^(.+) · 管理员$/, '$1 · Admin'],
    [/^(\d+)\s*个节点$/, '$1 nodes'],
    [/^(\d+)\s*条连线$/, '$1 links'],
    [/^(\d+)\s*个接口$/, '$1 APIs'],
    [/^(\d+)\s*个底模 · (\d+)\s*个视频模型$/,
      '$1 base models · $2 video models'],
    [/^(\d+)\s*节点\s*·$/, '$1 nodes ·'],
    [/^(\d+)\s*连线\s*·$/, '$1 links ·'],
    [/^模型星系\s*·\s*调用中$/, 'Models · calling'],
    [/^本地 · ComfyUI · (.+?) · 管理员$/, 'Local · ComfyUI · $1 · Admin'],
    [/^本地 · ComfyUI · (.+)$/, 'Local · ComfyUI · $1'],
    [/^当前范围可组合出约\s*(.+)\s*条不同提示词。$/,
      'About $1 possible prompts in this scope.'],
    [/^正在出图…\s*([\d.]+)\s*秒$/, 'Generating… $1s'],
    [/^正在出图…\s*([\d.]+)\s*秒\s*·\s*第\s*(\d+)\/(\d+)\s*步$/,
      'Generating… $1s · step $2/$3'],
    [/^出好了，用时\s*([\d.]+)\s*秒$/, 'Done in $1s'],
    [/^已提交，正在出图…$/, 'Submitted, generating…'],
    [/^已同步到正在运行的任务（(.+)）…$/, 'Synced to running job ($1)…'],
    [/^已同步另一个界面完成的任务\s*·\s*用时\s*([\d.]+)s。$/,
      'Synced a job finished in the other view · $1s.'],
    [/^已同步另一个界面完成的任务。$/, 'Synced a job finished in the other view.'],
    [/^生成完成\s*·\s*用时\s*([\d.]+)s。$/, 'Generation complete · $1s.'],
    [/^生成完成，用时\s*([\d.]+)\s*秒$/, 'Generation complete in $1s'],
    [/^生成完成，用时\s*([\d.]+)\s*秒。可打开原图或再来一张。$/,
      'Generation complete in $1s. Open the image or generate again.'],
    [/^预计剩余\s*([\d.]+)s$/, 'ETA $1s'],
    [/^预计\s*([\d.]+)s$/, 'ETA $1s'],
    [/^预计\s*([\d.]+)\s*秒$/, 'ETA $1s'],
    [/^运行中\s*(\d+)%\s*·\s*([\d.]+)s$/, 'Running $1% · $2s'],
    [/^运行中\s*(\d+)%$/, 'Running $1%'],
    [/^生成中\s*(\d+)%$/, 'Generating $1%'],
    [/^生成中\s*(\d+)%$/, 'Generating $1%'],
    [/^第\s*(\d+)\/(\d+)\s*步$/, 'Step $1/$2'],
    [/^共\s*(\d+)\s*张，已显示第\s*1\s*张$/, '$1 images; showing #1'],
    [/^成功\s*(\d+)\s*张$/, '$1 succeeded'],
    [/^失败\s*(\d+)\s*张$/, '$1 failed'],
    [/^已选\s*(\d+)\s*张$/, '$1 selected'],
    [/^(\d+)\s*张$/, '$1 images'],
    [/^(\d+)\s*条$/, '$1 records'],
    [/^告警\s*(\d+)$/, 'Alerts $1'],
    [/^(\d+)\s*天$/, '$1 days'],
    [/^(\d+)\s*个$/, '$1'],
    [/^健康分\s*\/\s*告警\s*\/\s*趋势$/, 'Health / alerts / trends'],
    [/^(\d+)\s*个账号$/, '$1 accounts'],
    [/^(\d+)\s*个任务运行中$/, '$1 jobs running'],
    [/^(\d+)\s*个排队中$/, '$1 queued'],
    [/^排队\s*(\d+)$/, '$1 queued'],
    [/^槽位\s*(\d+)$/, '$1 slots'],
    [/^优先级 \+(\d+)$/, 'priority +$1'],
    [/^全局暂停：(.+)$/, 'Globally paused: $1'],
    [/^1\s*名成员$/, '1 member'],
    [/^1\s*条共享提示词$/, '1 shared prompt'],
    [/^1\s*个团队$/, '1 team'],
    [/^1\s*个会话$/, '1 session'],
    [/^(\d+)\s*名成员$/, '$1 members'],
    [/^(\d+)\s*条共享提示词$/, '$1 shared prompts'],
    [/^(\d+)\s*个团队$/, '$1 teams'],
    [/^(\d+)\s*个会话$/, '$1 sessions'],
    [/^排队超时（超过\s*(\d+)\s*分钟）$/, 'Queue timed out (over $1 minutes)'],
    [/^(\d+)\s*个底模$/, '$1 base models'],
    [/^(\d+)\s*张图$/, '$1 images'],
    [/^(\d+)\s*秒$/, '$1s'],
    [/^管理员暂时关闭了你的「(.+)」功能。$/,
      'The administrator has temporarily disabled "$1" for your account.'],
    [/^今天的流量额度用完了（每天\s*(\d+)\s*MB）。$/,
      'Daily traffic quota used up ($1 MB/day).'],
    [/^本月流量额度用完了（每月\s*(\d+)\s*MB）。$/,
      'Monthly traffic quota used up ($1 MB/month).'],
    [/^今天的 GPU 时间额度用完了（每天\s*(\d+)\s*秒）。$/,
      'Daily GPU time quota used up ($1 seconds/day).'],
    [/^本月的 GPU 时间额度用完了（每月\s*(\d+)\s*秒）。$/,
      'Monthly GPU time quota used up ($1 seconds/month).'],
    [/^今天的出图额度用完了（每天\s*(\d+)\s*张）。$/,
      'Daily image quota used up ($1 images/day).'],
    [/^图库数量到上限了（最多\s*(\d+)\s*张），先删一些旧图。$/,
      'Gallery limit reached ($1 images). Delete some old images first.'],
    [/^占用空间到上限了（最多\s*(\d+)\s*MB），先清理旧图。$/,
      'Storage limit reached ($1 MB). Clean up old images first.'],
    [/^步数超过上限（管理员限制\s*(\d+)\s*步）。$/,
      'Steps exceed the limit ($1).'],
    [/^一次生成张数超过上限（管理员限制\s*(\d+)\s*张）。$/,
      'Image count exceeds the limit ($1).'],
    [/^你已经有\s*(\d+)\s*个任务在跑，等完成再提交。$/,
      'You already have $1 running jobs; wait for one to finish.'],
    [/^本小时重启：ComfyUI\s*(\d+)\s*次\s*·\s*网页\s*(\d+)\s*次$/,
      'Restarts this hour: ComfyUI $1 · web $2'],
    [/^已用\s*([\d.]+)\s*(张|MB|秒|步|个)$/, 'Used $1 $2'],
    [/^上限\s*([\d.]+)\s*(张|MB|秒|步|个)$/, 'Limit $1 $2'],
    [/^提示词已清理\s*(\d+)\s*个不可见字符$/,
      'Removed $1 invisible character(s) from the prompt'],
    [/^提示词超过\s*(\d+)\s*字，已截断$/,
      'Prompt was truncated to $1 characters'],
    [/^负面提示词已清理\s*(\d+)\s*个不可见字符$/,
      'Removed $1 invisible character(s) from the negative prompt'],
    [/^负面提示词超过\s*(\d+)\s*字，已截断$/,
      'Negative prompt was truncated to $1 characters'],
    [/^错误次数太多，(\d+)\s*秒后再试$/, 'Too many attempts; try again in $1s'],
    [/^任务不存在$/, 'Job not found'],
    [/^已取消$/, 'Cancelled']
  ];

  var ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
  var applying = false;

  var SUBST = [
    ['动漫 · Anima 2B（2026）', 'Anime · Anima 2B (2026)'],
    ['动漫 · NoobAI Vpred', 'Anime · NoobAI Vpred'],
    ['写实 · Juggernaut XI 风景', 'Photo · Juggernaut XI landscape'],
    ['动漫 · Illustrious', 'Anime · Illustrious'],
    ['写实 · RealVis Lightning', 'Photo · RealVis Lightning'],
    ['动漫 · Counterfeit（旧）', 'Anime · Counterfeit (legacy)'],
    ['写作 · ', 'Writing · '], ['动漫 · ', 'Anime · '], ['写实 · ', 'Photo · '],
    ['初音未来', 'Hatsune Miku'], ['PyAV 抽帧', 'PyAV frame extraction'],
    ['模型就绪检查', 'model readiness check'], ['（强制）', '(forced)'],
    ['前台', 'foreground']
  ];

  function hasCJK(s) {
    return /[㐀-鿿]/.test(s || '');
  }

  function postTranslate(s) {
    s = s.replace(/([\d.]+)\s*亿/g, function (_, n) {
      return Math.round(parseFloat(n) * 1e8).toLocaleString('en-US');
    }).replace(/([\d.]+)\s*万/g, function (_, n) {
      return Math.round(parseFloat(n) * 1e4).toLocaleString('en-US');
    }).replace(/(\d+)\s*张/g, function (_, n) {
      return n + ' image' + (n === '1' ? '' : 's');
    }).replace(/([\d.]+)\s*秒/g, '$1s')
      .replace(/(\d+)\s*条/g, '$1 records')
      .replace(/\b1 accounts\b/g, '1 account')
      .replace(/\b1 images\b/g, '1 image')
      .replace(/\b1 records\b/g, '1 record');
    SUBST.forEach(function (pair) {
      if (s.indexOf(pair[0]) >= 0) s = s.split(pair[0]).join(pair[1]);
    });
    return s;
  }

  function tr(s) {
    if (typeof s !== 'string' || !s || !hasCJK(s)) return s;
    var raw = s;
    var lead = raw.match(/^\s*/)[0];
    var tail = raw.match(/\s*$/)[0];
    var core = raw.slice(lead.length, raw.length - tail.length);
    if (!core) return s;
    if (core.indexOf('\n') >= 0) {
      var changedLines = false;
      var lineOut = core.split('\n').map(function (line) {
        var q = tr(line);
        if (q !== line) changedLines = true;
        return q;
      });
      if (changedLines) return lead + lineOut.join('\n') + tail;
    }
    var lsep = core.match(/^(\s*·\s*)([\s\S]+)$/);
    if (lsep) {
      var lrest = tr(lsep[2]);
      if (lrest !== lsep[2]) return lead + lsep[1] + lrest + tail;
    }
    if (Object.prototype.hasOwnProperty.call(EN, core)) {
      return lead + postTranslate(EN[core]) + tail;
    }
    var pm = core.match(/^(进入|打开|查看|去|切换到|选择|定位)(.+)$/);
    if (pm) {
      var prefix = { '进入': 'Open ', '打开': 'Open ', '查看': 'View ',
        '去': 'Go to ', '切换到': 'Switch to ', '选择': 'Choose ',
        '定位': 'Locate ' }[pm[1]];
      var rest = tr(pm[2]);
      if (rest !== pm[2] && !hasCJK(rest)) {
        return lead + prefix + rest + tail;
      }
    }
    var am = core.match(/^←\s*(.+)$/);
    if (am) {
      var ar = tr(am[1]);
      if (ar !== am[1]) return lead + '← ' + ar + tail;
    }
    var am2 = core.match(/^(.+?)\s*→$/);
    if (am2) {
      var ar2 = tr(am2[1]);
      if (ar2 !== am2[1]) return lead + ar2 + ' →' + tail;
    }
    var fm = core.match(/^生成流程\s*·\s*(.+)$/);
    if (fm) return lead + 'Flow · ' + tr(fm[1]) + tail;
    var bm = core.match(/^生成支线\s*·\s*(.+)$/);
    if (bm) return lead + 'Branch · ' + tr(bm[1]) + tail;
    var em = core.match(/^进入相关功能：(.+)$/);
    if (em) return lead + 'Open related feature: ' + tr(em[1]) + tail;
    var fd = core.match(/^管理员暂时关闭了你的「(.+)」功能。$/);
    if (fd) return lead + 'The administrator has temporarily disabled "' +
      tr(fd[1]) + '" for your account.' + tail;
    var fd2 = core.match(/^管理员暂时关闭了「(.+)」功能。$/);
    if (fd2) return lead + 'The administrator has temporarily disabled "' +
      tr(fd2[1]) + '" for your account.' + tail;
    var aq = core.match(/^(分享版|商业版)最多 (\d+) 个启用账号（含管理员）。请先停用或删除账号，或升级商业版。$/);
    if (aq) return lead + (aq[1] === '分享版' ? 'Share edition' : 'Commercial edition') +
      ' allows at most ' + aq[2] + ' active accounts (including admin). Disable or delete an account, or upgrade to Commercial.' + tail;
    var wq = core.match(/^(分享版|商业版)最多 (\d+) 台算力节点。请先移除旧节点，或升级商业版。$/);
    if (wq) return lead + (wq[1] === '分享版' ? 'Share edition' : 'Commercial edition') +
      ' allows at most ' + wq[2] + ' worker nodes. Remove an old worker or upgrade to Commercial.' + tail;
    var gd = core.match(/^检测到\s*(.+)。新的出图任务会暂时被拦下，占用降下来后自动恢复。$/);
    if (gd) return lead + 'Detected ' + tr(gd[1]) +
      '. New generation jobs are paused until load drops.' + tail;
    var gd2 = core.match(/^检测到你正在大量占用电脑（(.+)），生图已自动暂停。占用降下来后会自动恢复，不用手动设置。$/);
    if (gd2) return lead + 'Heavy computer load detected (' + tr(gd2[1]) +
      '). Generation is paused and resumes automatically.' + tail;
    var dis = core.match(/^已关闭：(.+)$/);
    if (dis) return lead + 'Disabled: ' +
      dis[1].split(/\s*\/\s*/).map(tr).join(' / ') + tail;
    var bm2 = core.match(/^从「(.+)」分叉$/);
    if (bm2) return lead + 'From "' + tr(bm2[1]) + '"' + tail;
    var jm = core.match(/^汇入「(.+)」→$/);
    if (jm) return lead + 'Joins "' + tr(jm[1]) + '" →' + tail;
    var fsm = core.match(/^第\s*(\d+)\s*步\s*·\s*(.+?)\s*·\s*(.+?)（(.+)）$/);
    if (fsm) return lead + 'Step ' + fsm[1] + ' · ' + tr(fsm[2]) + ' · ' +
      tr(fsm[3]) + ' (' + tr(fsm[4]) + ')' + tail;
    var fsn = core.match(/^第\s*(\d+)\s*步\s*·\s*(.+?)\s*·\s*(.+)$/);
    if (fsn) return lead + 'Step ' + fsn[1] + ' · ' + tr(fsn[2]) + ' · ' +
      tr(fsn[3]) + tail;
    var brm = core.match(/^旁支\s*·\s*(.+?)\s*·\s*(.+?)（(.+)）$/);
    if (brm) return lead + 'Branch · ' + tr(brm[1]) + ' · ' +
      tr(brm[2]) + ' (' + tr(brm[3]) + ')' + tail;
    var brn = core.match(/^旁支\s*·\s*(.+?)\s*·\s*(.+)$/);
    if (brn) return lead + 'Branch · ' + tr(brn[1]) + ' · ' +
      tr(brn[2]) + tail;
    var rnd = core.match(/^换了一条随机提示词 —— 【(.+)】$/);
    if (rnd) return lead + 'Random prompt: 【' + tr(rnd[1]) + '】' + tail;
    var rnd2 = core.match(/^随机好了 —— 【(.+)】，点「出图」开始$/);
    if (rnd2) return lead + 'Random prompt ready: 【' + tr(rnd2[1]) +
      '】. Tap Generate.' + tail;
    var col = core.match(/^拼好了：(.+)（在图库最前面）$/);
    if (col) return lead + 'Collage created: ' + tr(col[1]) +
      ' (at the front of the gallery)' + tail;
    var exp = core.match(/^已导出：(.+)（在图库最前面）$/);
    if (exp) return lead + 'Exported: ' + tr(exp[1]) +
      ' (at the front of the gallery)' + tail;
    var upm = core.match(/^正在放大\s*([\d.]+)×…$/);
    if (upm) return lead + 'Upscaling ' + upm[1] + '×…' + tail;
    var aut = core.match(/^开始挂机，共\s*(\d+)\s*张。切到图库刷新可以看到。$/);
    if (aut) return lead + 'Auto-run started: ' + aut[1] +
      ' images. Check the gallery.' + tail;
    var prefixes = ['连不上电脑上的服务：', '对比失败：', '拼图失败：',
      '导出失败：', '读取图片失败：', '启动失败：', '失败：'];
    for (var pi = 0; pi < prefixes.length; pi++) {
      var pz = prefixes[pi];
      if (core.indexOf(pz) === 0) {
        return lead + EN[pz] + tr(core.slice(pz.length)) + tail;
      }
    }
    for (var i = 0; i < PATTERNS.length; i++) {
      var m = PATTERNS[i];
      if (m[0].test(core)) {
        return lead + postTranslate(core.replace(m[0], m[1])) + tail;
      }
    }
    var nm = core.match(/^(\d+)\s+(.+)$/);
    if (nm) {
      var nr = tr(nm[2]);
      if (nr !== nm[2]) {
        return lead + postTranslate(nm[1] + ' ' + nr) + tail;
      }
    }
    var segs = core.split(' · ');
    if (segs.length > 1) {
      var changed = false;
      var mapped = segs.map(function (seg) {
        var q = tr(seg);
        if (q !== seg) changed = true;
        return q;
      });
      if (changed) return lead + mapped.join(' · ') + tail;
    }
    return postTranslate(s);
  }

  function translateNode(node) {
    if (!node || node.nodeType !== 3 || !node.nodeValue) return;
    var parent = node.parentElement;
    if (!parent) return;
    var tag = parent.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEXTAREA' ||
        tag === 'CODE' || tag === 'PRE' || parent.closest('[data-no-i18n]')) {
      return;
    }
    if (hasCJK(node.nodeValue)) node.__i18nZh = node.nodeValue;
    if (node.__i18nZh == null) return;
    var out = tr(node.__i18nZh);
    if (out !== node.nodeValue) {
      applying = true;
      node.nodeValue = out;
      applying = false;
    }
  }

  function translateAttrs(el) {
    if (!el || el.nodeType !== 1 || el.closest('[data-no-i18n]')) return;
    if (!el.__i18nAttrs) el.__i18nAttrs = {};
    ATTRS.forEach(function (a) {
      var v = el.getAttribute(a);
      if (v == null) return;
      if (hasCJK(v)) el.__i18nAttrs[a] = v;
      if (el.__i18nAttrs[a] == null) return;
      var out = tr(el.__i18nAttrs[a]);
      if (out !== v) {
        applying = true;
        el.setAttribute(a, out);
        applying = false;
      }
    });
  }

  function walk(root, fnText, fnEl) {
    if (!root) return;
    if (root.nodeType === 3) { fnText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9) return;
    fnEl && fnEl(root.nodeType === 1 ? root : null);
    var tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var n;
    while ((n = tw.nextNode())) fnText(n);
    if (root.querySelectorAll) {
      root.querySelectorAll('*').forEach(function (el) { fnEl && fnEl(el); });
    }
  }

  function apply(root) {
    if (lang !== 'en') return;
    applying = true;
    walk(root || document.body, translateNode, translateAttrs);
    applying = false;
  }

  function restore(root) {
    applying = true;
    var tw = document.createTreeWalker(root || document.body,
      NodeFilter.SHOW_TEXT, null);
    var n;
    while ((n = tw.nextNode())) {
      if (n.__i18nZh != null) n.nodeValue = n.__i18nZh;
    }
    (root || document.body).querySelectorAll('*').forEach(function (el) {
      if (!el.__i18nAttrs) return;
      Object.keys(el.__i18nAttrs).forEach(function (a) {
        el.setAttribute(a, el.__i18nAttrs[a]);
      });
    });
    applying = false;
  }

  function setLang(next) {
    lang = next === 'en' ? 'en' : 'zh';
    try { localStorage.setItem(KEY, lang); } catch (e) {}
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.body.classList.toggle('lang-en', lang === 'en');
    if (document.__i18nTitleZh == null) document.__i18nTitleZh = document.title;
    document.title = lang === 'en' ? tr(document.__i18nTitleZh)
                                   : document.__i18nTitleZh;
    if (lang === 'en') apply(document.body); else restore(document.body);
    document.querySelectorAll('[data-lang-toggle]').forEach(function (b) {
      b.textContent = lang === 'en' ? '中文' : 'EN';
      b.title = lang === 'en' ? '切换到中文' : 'Switch to English';
      b.setAttribute('aria-label', b.title);
    });
    try {
      document.dispatchEvent(new CustomEvent('mg-lang', { detail: { lang: lang } }));
    } catch (e) {}
  }

  var observer = null;
  function startObserver() {
    if (observer || !window.MutationObserver) return;
    observer = new MutationObserver(function (muts) {
      if (applying || lang !== 'en') return;
      muts.forEach(function (m) {
        if (m.type === 'characterData') translateNode(m.target);
        else if (m.type === 'attributes') translateAttrs(m.target);
        else m.addedNodes.forEach(function (n) {
          if (n.nodeType === 3) translateNode(n);
          else if (n.nodeType === 1) apply(n);
        });
      });
    });
    observer.observe(document.body, {
      childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ATTRS
    });
  }

  function init() {
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.__i18nTitleZh = document.title;
    if (lang === 'en') document.title = tr(document.title);
    if (lang === 'en') document.body.classList.add('lang-en');
    document.querySelectorAll('[data-lang-toggle]').forEach(function (b) {
      b.textContent = lang === 'en' ? '中文' : 'EN';
      b.title = lang === 'en' ? '切换到中文' : 'Switch to English';
      b.addEventListener('click', function () {
        setLang(lang === 'en' ? 'zh' : 'en');
      });
    });
    if (lang === 'en') apply(document.body);
    startObserver();
  }

  window.MGI18N = {
    t: tr,
    apply: apply,
    setLang: setLang,
    getLang: function () { return lang; },
    isEnglish: function () { return lang === 'en'; }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
