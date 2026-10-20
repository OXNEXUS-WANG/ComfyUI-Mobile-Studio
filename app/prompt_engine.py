# -*- coding: utf-8 -*-
"""提示词翻译、中文角色/作品词典、Danbooru 标签优化。

这个模块只依赖标准库和 char_tags.json，不碰 ComfyUI / 网页服务，
方便单独改词表、调翻译质量。
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
CHAR_FILE = os.path.join(ROOT, "char_tags.json")


def has_chinese(text):
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


# --------------------------------------------------------------------- 翻译

def translate_text(text):
    """中->英 翻译（词表覆盖不到的残句才用）。失败返回空串。"""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        import argostranslate.translate as T
        langs = T.get_installed_languages()
        zh = next((l for l in langs if l.code == "zh"), None)
        en = next((l for l in langs if l.code == "en"), None)
        if zh and en:
            tr = zh.get_translation(en)
            if tr:
                return tr.translate(text)
    except Exception:
        pass
    return ""


# ------------------------------------------------------- 中文角色名 → 英文标签

CHAR_ALIASES = {}
CHAR_SERIES = {}
CHAR_KEYS = []


def load_char_tags():
    """读 char_tags.json（约 8000 个角色/作品别名）。缺文件就跳过。"""
    global CHAR_KEYS
    try:
        with open(CHAR_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh) or {}
        CHAR_ALIASES.update(d.get("aliases") or {})
        CHAR_SERIES.update(d.get("series") or {})
        CHAR_KEYS = sorted(set(CHAR_ALIASES) | set(CHAR_SERIES),
                           key=len, reverse=True)
    except Exception:
        pass


def extract_char_tags(text):
    """把提示词里的中文角色/作品名换成英文 danbooru 标签。

    返回 (去掉角色名的提示词, [标签...])。最长匹配优先，避免
    「初音」先吃掉「初音未来」；角色名从提示词里移除，Argos 就不会
    再把它翻成 "the first-sounding future"。
    """
    text = text or ""
    if not text or not CHAR_KEYS:
        return text, []
    char_hits, series_hits = [], []
    for key in CHAR_KEYS:
        pos = text.find(key)
        if pos < 0:
            continue
        tag = CHAR_ALIASES.get(key)
        if tag:
            if tag not in [t for _, t in char_hits]:
                char_hits.append((pos, tag))
        else:
            tag = CHAR_SERIES.get(key)
            if tag and tag not in [t for _, t in series_hits]:
                series_hits.append((pos, tag))
        text = text.replace(key, "，")
        if len(char_hits) + len(series_hits) >= 6:
            break
    # 去掉只剩「的 / 和 / 在」这类连接词的残句，别让 Argos 翻出废话
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"^[，,\s]*(?:的|和|与|及|在|是)[，,\s]*", "", text)
    text = re.sub(r"[，,\s]*(?:的|和|与|及|在|是)$", "", text)
    text = text.strip("，, ")
    if text in ("的", "和", "与", "及", "在", "是"):
        text = ""
    char_hits.sort(key=lambda x: x[0])
    series_hits.sort(key=lambda x: x[0])
    tags = [t for _, t in char_hits] + [t for _, t in series_hits]
    return text, tags


load_char_tags()


# --------------------------------------------------------------- 提示词优化

QUALITY_TAGS = "masterpiece, best quality, very aesthetic, absurdres"
_QUALITY_WORDS = ("masterpiece", "best quality", "very aesthetic", "absurdres")

# 中文 → danbooru 标签。右值是模型真正认识的英文标签，空串表示虚词直接丢掉。
# 匹配时按长度降序，所以「黑色长直发」会整体命中，不会被拆成「黑色」+「长」+「直发」。
TAG_DICT = {
    # ---------- 虚词 / 填充（直接丢掉，避免机翻成 one / the 这类垃圾） ----------
    "一个": "", "一位": "", "一只": "", "一群": "", "一对": "", "一名": "",
    "一杯": "", "一本": "", "一片": "", "一些": "", "一种": "",
    "画面中央": "", "画面": "", "中央": "", "表情": "", "神情": "",
    "正在": "", "她": "", "他": "", "它": "", "这": "", "那": "",
    "有点": "", "非常": "", "十分": "", "巨大": "", "旁边": "",
    "正": "", "手里": "", "手中": "", "身上": "", "脸上": "",
    "在": "", "下": "", "上": "", "里": "", "中": "", "内": "", "外": "",
    "有": "", "是": "", "就": "", "也": "", "都": "", "还": "", "又": "",
    "远处": "background", "斑驳": "dappled",
    "晚上": "night", "夜里": "night", "白天里": "day",

    # ---------- 颜色（单独出现时也用得上） ----------
    "深蓝色": "dark blue", "浅蓝色": "light blue", "浅色": "light color",
    "红色": "red", "蓝色": "blue", "绿色": "green", "黄色": "yellow",
    "紫色": "purple", "粉色": "pink", "白色": "white", "黑色": "black",
    "灰色": "grey", "橙色": "orange", "棕色": "brown", "银色": "silver",
    "金色": "gold", "彩色": "colorful",

    # ---------- 人数 / 主体 ----------
    "一个女孩": "1girl", "一个少女": "1girl", "一位少女": "1girl",
    "一个男孩": "1boy", "一个少年": "1boy", "一位少年": "1boy",
    "一位女仆": "1girl, maid", "一位骑士": "1girl, knight",
    "一位魔法师": "1girl, mage", "一位歌手": "1girl, idol",
    "一位旅行者": "1girl, traveler", "一位剑士": "1girl, sword",
    "一位舞者": "1girl, dancing", "一位画家": "1girl, painting",
    "一位上班族": "1girl, office lady", "一位厨师": "1girl, chef",
    "一个学生": "1girl, student", "图书馆管理员": "1girl, librarian",
    "咖啡店老板": "1girl, cafe", "机甲少女": "1girl, mecha",
    "机甲战士": "mecha, robot", "重型战斗机器人": "mecha, robot, heavy armor",
    "装甲战士": "1girl, armor", "悬浮战车": "hover vehicle",
    "无人机编队": "drone, flying", "魔法少女": "1girl, magical girl",
    "精灵弓箭手": "1girl, elf, archer", "龙骑士": "dragon, knight",
    "亡灵法师": "1girl, necromancer", "占星师": "1girl, astrology",
    "祭司": "1girl, priestess", "盗贼": "1girl, thief",
    "巫师": "1girl, witch", "少女": "1girl", "女孩": "1girl",
    "女生": "1girl", "女孩子": "1girl", "少年": "1boy", "男孩": "1boy",
    "男生": "1boy", "男人": "man", "女人": "woman",
    "两个人": "2girls", "两个女孩": "2girls", "一对姐妹": "2girls, sisters",
    "双人": "2girls", "单人": "solo", "独自": "solo", "一个人": "solo",
    "空无一人": "no humans", "无人": "no humans", "女仆": "maid",
    "骑士": "knight", "歌手": "idol", "剑士": "sword", "舞者": "dancing",
    "魔法师": "mage", "旅行者": "traveler", "旅人": "traveler",

    # ---------- 头发 ----------
    "黑色长直发": "black hair, long straight hair",
    "银色双马尾": "silver hair, twintails",
    "粉色短发": "pink hair, short hair",
    "金色波浪卷发": "blonde hair, wavy hair",
    "白色短发": "white hair, short hair",
    "棕色丸子头": "brown hair, hair bun",
    "深蓝色长卷发": "dark blue hair, long wavy hair",
    "亚麻色麻花辫": "light brown hair, braid",
    "银色长发": "silver hair, long hair", "金色长发": "blonde hair, long hair",
    "黑色长发": "black hair, long hair", "白色长发": "white hair, long hair",
    "粉色长发": "pink hair, long hair", "蓝色长发": "blue hair, long hair",
    "红色长发": "red hair, long hair", "银色短发": "silver hair, short hair",
    "黑色短发": "black hair, short hair", "金色短发": "blonde hair, short hair",
    "双丸子头": "double bun", "超长发": "very long hair",
    "中长发": "medium hair", "长直发": "long straight hair",
    "长卷发": "long wavy hair", "波浪卷发": "wavy hair",
    "双马尾": "twintails", "侧马尾": "side ponytail",
    "单马尾": "ponytail", "马尾": "ponytail", "丸子头": "hair bun",
    "麻花辫": "braid", "辫子": "braid", "卷发": "curly hair",
    "直发": "straight hair", "长发": "long hair", "短发": "short hair",
    "齐刘海": "blunt bangs", "刘海": "bangs", "呆毛": "ahoge",
    "渐变发": "gradient hair", "挑染": "streaked hair",
    "黑发": "black hair", "黑色头发": "black hair",
    "白发": "white hair", "白色头发": "white hair",
    "银发": "silver hair", "银色头发": "silver hair",
    "金发": "blonde hair", "金色头发": "blonde hair",
    "粉发": "pink hair", "粉色头发": "pink hair",
    "蓝发": "blue hair", "蓝色头发": "blue hair",
    "红发": "red hair", "红色头发": "red hair",
    "紫发": "purple hair", "紫色头发": "purple hair",
    "绿发": "green hair", "绿色头发": "green hair",
    "棕发": "brown hair", "褐色头发": "brown hair",
    "灰发": "grey hair", "灰色头发": "grey hair",

    # ---------- 眼睛 ----------
    "蓝色眼睛": "blue eyes", "红色眼睛": "red eyes",
    "绿色眼睛": "green eyes", "金色眼睛": "yellow eyes",
    "紫色眼睛": "purple eyes", "蓝眼": "blue eyes",
    "红眼": "red eyes", "绿眼": "green eyes", "金眼": "yellow eyes",
    "紫眼": "purple eyes", "灰眼": "grey eyes",
    "异色瞳": "heterochromia", "红瞳": "red eyes", "蓝瞳": "blue eyes",
    "金瞳": "yellow eyes", "闭眼": "closed eyes",

    # ---------- 体型 / 特征 ----------
    "兽耳": "animal ears", "猫耳": "cat ears", "兔耳": "rabbit ears",
    "狐狸耳": "fox ears", "精灵耳": "pointed ears", "翅膀": "wings",
    "羽翼": "feathered wings", "尾巴": "tail", "雀斑": "freckles",
    "泪痣": "mole under eye", "虎牙": "fang", "尖牙": "fangs",

    # ---------- 服装 ----------
    "黑色哥特连衣裙": "black gothic dress",
    "白衬衫制服": "white shirt, school uniform",
    "白色连衣裙": "white dress", "学院制服": "school uniform",
    "长款风衣": "long coat", "运动外套": "track jacket",
    "黑色长裙": "black long skirt",
    "白衬衫": "white shirt", "水手服": "serafuku",
    "百褶裙": "pleated skirt", "连衣裙": "dress", "长裙": "long skirt",
    "短裙": "skirt", "哥特裙": "gothic dress", "女仆装": "maid outfit",
    "和服": "kimono", "浴衣": "yukata", "汉服": "hanfu",
    "旗袍": "qipao", "泳装": "swimsuit", "比基尼": "bikini",
    "风衣": "trench coat", "外套": "jacket", "大衣": "coat",
    "毛衣": "sweater", "针织衫": "knitwear", "衬衫": "shirt",
    "卫衣": "hoodie", "斗篷": "cloak", "长袍": "robe",
    "铠甲": "armor", "盔甲": "armor", "校服": "school uniform",
    "制服": "uniform", "过膝袜": "thighhighs", "长筒袜": "thighhighs",
    "黑丝": "black pantyhose", "白丝": "white thighhighs",
    "连裤袜": "pantyhose", "短袜": "socks", "赤脚": "barefoot",
    "手套": "gloves", "围巾": "scarf", "领带": "necktie",
    "蝴蝶结": "bow", "发带": "hair ribbon", "发饰": "hair ornament",
    "贝雷帽": "beret", "草帽": "straw hat", "帽子": "hat",
    "眼镜": "glasses", "耳环": "earrings", "项链": "necklace",
    "项圈": "choker", "腰带": "belt",

    # ---------- 表情 ----------
    "惊讶地睁大眼": "surprised, wide eyes",
    "闭眼轻哼": "closed eyes, humming",
    "眼神坚定": "determined", "微微脸红": "light blush",
    "微笑": "smile", "笑容": "smile", "开心": "happy",
    "高兴": "happy", "脸红": "blush", "害羞": "embarrassed",
    "眼泪": "tears", "哭泣": "crying", "哭": "crying",
    "生气": "angry", "愤怒": "angry", "惊讶": "surprised",
    "悲伤": "sad", "忧郁": "melancholic", "沉思": "thinking",
    "面无表情": "expressionless", "冷静": "calm",
    "张嘴": "open mouth", "吐舌": "tongue out", "咬牙": "gritted teeth",
    "轻哼": "humming", "回眸": "looking back",

    # ---------- 动作 / 姿势 ----------
    "站在窗边": "standing, window",
    "回头看向镜头": "looking back, looking at viewer",
    "坐在台阶上": "sitting, stairs",
    "伸手触碰光线": "reaching out, light rays",
    "低头整理衣袖": "adjusting sleeves, looking down",
    "手捧花束": "holding bouquet", "撑着伞": "holding umbrella",
    "打伞": "holding umbrella", "倚靠墙壁": "leaning against wall",
    "靠在墙上": "leaning against wall", "低头阅读": "reading",
    "桌前工作": "working at desk", "冲泡咖啡": "making coffee",
    "专注作画": "painting", "整理书架": "shelving books",
    "切菜备料": "cooking", "向前走": "walking", "回头看": "looking back",
    "看着镜头": "looking at viewer", "看向观众": "looking at viewer",
    "看向远方": "looking away", "手背在身后": "arms behind back",
    "手叉腰": "hand on hip", "弹吉他": "playing guitar",
    "弹琴": "playing piano", "站立": "standing", "站着": "standing",
    "站在": "standing", "坐着": "sitting", "坐在": "sitting",
    "躺着": "lying", "躺在": "lying", "趴着": "lying on stomach",
    "跪着": "kneeling", "走着": "walking", "走在": "walking",
    "走路": "walking", "奔跑": "running", "跳跃": "jumping",
    "漂浮": "floating", "悬浮": "floating", "跳舞": "dancing",
    "抱胸": "crossed arms", "举手": "arms up", "伸手": "outstretched arm",
    "捧着": "holding", "抱着": "holding", "拿着": "holding",
    "看书": "reading book", "阅读": "reading", "睡觉": "sleeping",
    "祈祷": "praying", "挥手": "waving", "指向": "pointing",
    "唱歌": "singing", "吃东西": "eating", "坐": "sitting",
    "跑": "running", "跳": "jumping", "飞": "flying",

    # ---------- 场景 ----------
    "樱花树下": "under cherry blossoms", "雨夜街道": "rainy street, night, rain",
    "海边小镇": "seaside town", "古老图书馆": "old library",
    "废弃车站": "abandoned train station", "屋顶天台": "rooftop",
    "教室窗边": "classroom, window", "热闹的集市": "marketplace",
    "森林小屋": "cabin in forest", "未来都市": "futuristic city",
    "教堂内厅": "church interior", "沙漠绿洲": "desert oasis",
    "深夜便利店": "convenience store at night", "夏日祭典": "summer festival",
    "老式火车车厢": "train interior", "无边花田": "flower field",
    "废弃游乐园": "abandoned amusement park", "月面基地": "moon base",
    "宿舍卧室": "dormitory, bedroom", "雨后的巷子": "alley after rain",
    "山间公路": "mountain road", "图书馆书架间": "library, bookshelves",
    "雪山之巅": "snowy mountain peak", "连绵的雪山": "snowy mountain range",
    "蜿蜒的海岸线": "winding coastline", "幽深的森林": "deep forest",
    "无边的沙漠": "vast desert", "静谧的湖泊": "quiet lake",
    "壮阔的峡谷": "grand canyon", "辽阔的草原": "vast grassland",
    "层叠的梯田": "terraced fields", "雪原": "snowfield, snow",
    "溪流边": "riverside", "天台": "rooftop", "集市": "marketplace",
    "祭典": "festival", "花田": "flower field", "教室": "classroom",
    "学校": "school", "卧室": "bedroom", "图书馆": "library",
    "咖啡厅": "cafe", "咖啡店": "cafe", "街道": "street",
    "巷子": "alley", "城市": "city", "都市": "city", "森林": "forest",
    "海边": "beach", "沙滩": "beach", "海滩": "beach",
    "雪山": "snowy mountain", "湖泊": "lake", "湖畔": "lakeside",
    "河流": "river", "草原": "grassland", "沙漠": "desert",
    "峡谷": "canyon", "梯田": "rice terraces", "海岸线": "coastline",
    "城堡": "castle", "教堂": "church", "神社": "shrine",
    "寺庙": "temple", "宫殿": "palace", "废墟": "ruins",
    "老房子": "old house", "房子": "house", "房间": "room",
    "窗边": "window", "窗外": "window", "窗台": "windowsill", "台阶": "stairs",
    "楼梯": "staircase", "桥": "bridge", "公园": "park",
    "车站": "train station", "列车": "train", "电车": "train",
    "室内": "indoors", "室外": "outdoors", "门外": "outside",
    "天空": "sky", "云海": "sea of clouds", "云": "clouds",
    "夜空": "night sky", "星空": "starry sky", "银河": "milky way",
    "极光": "aurora", "星星": "stars", "月亮": "moon",
    "大海": "ocean", "海": "ocean", "水面": "water",
    "山": "mountain",

    # ---------- 天气 / 时间 ----------
    "下雨": "rain", "雨中": "rain", "雨夜": "rainy night",
    "暴雨": "heavy rain", "雨后": "after rain", "雨": "rain",
    "下雪": "snowing", "雪天": "snowy", "雪": "snow",
    "薄雾弥漫": "mist", "薄雾": "mist", "雾": "fog",
    "冷调阴天": "overcast, cold tone", "阴天": "overcast",
    "晴天": "clear sky", "深夜": "late night", "夜晚": "night",
    "夜景": "night, city lights", "黄昏": "sunset", "日落": "sunset",
    "日出": "sunrise", "清晨": "early morning", "早晨": "morning",
    "白天": "day", "正午": "noon", "傍晚": "evening",
    "春天": "spring", "夏天": "summer", "秋天": "autumn",
    "冬天": "winter", "秋风": "autumn wind", "落叶": "falling leaves",

    # ---------- 光线 / 特效 ----------
    "柔和的晨光": "soft morning light", "温暖的烛光": "candlelight",
    "黄昏逆光": "sunset, backlighting", "霓虹灯光": "neon lights",
    "皎洁月光": "moonlight", "斑驳的树影": "dappled sunlight",
    "舞台聚光灯": "spotlight", "窗外透进的光": "light from window",
    "雨后的反光": "wet, reflection", "漂浮的光尘": "floating dust",
    "逆光剪影": "backlighting, silhouette",
    "彩色玻璃的光斑": "stained glass, light rays",
    "屏幕的冷光": "computer screen light",
    "电影感光线": "cinematic lighting", "丁达尔效应": "light rays",
    "柔和光线": "soft lighting", "体积光": "volumetric lighting",
    "晨光": "morning light", "逆光": "backlighting", "霓虹": "neon lights",
    "月光": "moonlight", "烛光": "candlelight", "聚光灯": "spotlight",
    "光尘": "dust motes", "剪影": "silhouette", "阳光": "sunlight",
    "日光": "sunlight", "光斑": "bokeh", "散景": "bokeh",
    "光晕": "lens flare", "发光": "glowing", "光效": "light effects",

    # ---------- 画质 / 风格 ----------
    "杰作": "masterpiece", "最高画质": "best quality",
    "超精细细节": "ultra-detailed", "精细的背景": "detailed background",
    "精细背景": "detailed background", "超精细": "ultra-detailed",
    "高质量": "high quality", "高画质": "best quality",
    "官方艺术": "official art", "壁纸": "wallpaper",
    "水彩": "watercolor", "油画": "oil painting", "像素": "pixel art",
    "素描": "sketch", "线稿": "lineart", "水墨": "ink painting",
    "吉卜力": "studio ghibli", "赛博朋克": "cyberpunk",
    "蒸汽朋克": "steampunk", "复古": "retro", "写实": "realistic",
    "厚涂": "impasto", "平涂": "flat color", "漫画": "manga",
    "动画截图": "anime screenshot", "电影级构图": "cinematic composition",
    "电影感": "cinematic", "极简": "minimalist", "华丽": "ornate",
    "未来科技感": "futuristic", "硬核": "detailed mechanical",
    "冷金属质感": "metallic", "奇幻氛围": "fantasy",
    "生活气息": "slice of life",

    # ---------- 构图 / 视角 ----------
    "全身": "full body", "半身": "upper body", "特写": "close-up",
    "肖像": "portrait", "头像": "portrait", "俯视": "from above",
    "仰视": "from below", "背面": "from behind", "侧面": "from side",
    "正面": "front view", "广角视野": "wide shot", "广角": "wide shot",
    "空镜": "scenery", "远景": "wide shot", "近景": "close-up",
    "中景": "medium shot", "对称构图": "symmetry",
    "浅景深": "depth of field", "景深": "depth of field",
    "虚化背景": "blurry background",

    # ---------- 氛围 ----------
    "宁静": "peaceful", "安静": "quiet", "神秘": "mysterious",
    "温暖": "warm", "温馨": "cozy", "史诗感": "epic",
    "紧张": "tense", "梦幻": "dreamy", "治愈": "healing",
    "怀旧": "nostalgic", "空灵": "ethereal", "慵懒": "lazy",
    "凛冽": "cold", "可爱": "cute", "生动": "vivid",
    "浪漫": "romantic",

    # ---------- 动物 ----------
    "一只白猫": "cat, white cat", "一只柴犬": "dog, shiba inu",
    "一只红狐狸": "fox, red fox", "一只猫头鹰": "owl",
    "一只小鹿": "deer", "一只兔子": "rabbit", "一只水鸟": "water bird",
    "一群蝴蝶": "butterflies", "毛发柔软蓬松": "fluffy fur",
    "眼睛明亮有神": "bright eyes", "尾巴高高翘起": "raised tail",
    "警惕地抬头": "alert, looking up", "安静地趴着": "lying down",
    "振翅欲飞": "spread wings", "白猫": "cat, white cat",
    "黑猫": "black cat", "小猫": "kitten", "柴犬": "shiba inu",
    "小狗": "puppy", "猫头鹰": "owl", "小鹿": "deer",
    "兔子": "rabbit", "蝴蝶": "butterfly", "狐狸": "fox",
    "白马": "white horse", "猫": "cat", "狗": "dog",
    "狼": "wolf", "鸟": "bird", "龙": "dragon", "马": "horse",
    "蓬松": "fluffy",

    # ---------- 幻想角色 / 武器 ----------
    "修女": "nun", "圣女": "saint", "天使": "angel", "恶魔": "demon",
    "吸血鬼": "vampire", "女巫": "witch", "公主": "princess",
    "王子": "prince", "女王": "queen", "国王": "king",
    "精灵": "elf", "矮人": "dwarf", "兽人": "orc", "半兽人": "orc",
    "镰刀": "scythe", "双刃": "double-bladed", "长枪": "spear",
    "弓箭": "bow", "弓箭手": "archer", "匕首": "dagger",
    "盾牌": "shield", "魔杖": "wand", "大剑": "greatsword",
    "哥特式": "gothic", "大教堂": "cathedral", "彩窗": "stained glass window",
    "手持": "holding", "挥舞": "swinging", "战斗中": "fighting",
    "魔法光效": "magic aura", "咒语": "spell", "召唤": "summoning",
    "羽翼展开": "spread wings", "光环": "halo", "十字架": "cross",

    # ---------- 机甲 / 幻想细节 ----------
    "银白装甲": "silver armor, white armor",
    "蓝色发光纹路": "glowing blue lines",
    "机械关节细节": "mechanical joints", "核心能量光": "glowing core",
    "液压管线": "hydraulic pipes", "展开的推进器": "thrusters",
    "悬浮的符文": "floating runes", "环绕的魔法光效": "magic circle",
    "发光法杖": "glowing staff", "展开的羽翼": "spread wings",
    "飘浮的尘埃": "floating dust", "碎裂的水晶": "shattered crystal",
    "魔法阵": "magic circle", "法阵": "magic circle",
    "符文": "runes", "法杖": "staff", "水晶": "crystal",
    "魔法": "magic",

    # ---------- 日常物件 / 风景细节 ----------
    "水面倒影清晰": "water reflection", "岩壁纹理分明": "rock texture",
    "绿意盎然": "lush green", "波光粼粼": "sparkling water",
    "云海翻涌": "sea of clouds", "咖啡": "coffee", "茶杯": "teacup",
    "书本": "books", "书": "book", "花束": "bouquet",
    "烟花": "fireworks", "花": "flower", "伞": "umbrella",
    "剑": "sword", "吉他": "guitar", "钢琴": "piano",
    "灯笼": "lantern", "纸伞": "paper umbrella", "倒影": "reflection",

    # ---------- 常用动词 / 补充名词 ----------
    "穿着": "wearing", "戴着": "wearing", "穿着打扮": "outfit",
    "抬头": "looking up", "低头": "looking down", "望着": "looking at",
    "望向": "looking at", "困惑": "confused", "好奇": "curious",
    "红色外套": "red jacket", "热咖啡": "coffee", "咖啡杯": "coffee cup",
    "天桥": "overpass", "彩色玻璃窗": "stained glass window",
    "彩色玻璃": "stained glass", "玻璃窗": "window", "窗户": "window",
    "霓虹灯": "neon lights", "街灯": "street light", "路灯": "street light",
    "书桌": "desk", "课桌": "desk", "桌上": "table", "桌子": "table",
    "餐桌": "table", "桌": "table", "椅子": "chair", "床": "bed",
    "枕头": "pillow", "被子": "blanket", "窗帘": "curtain",
    "镜子": "mirror", "镜子前": "mirror", "墙壁": "wall", "地面": "floor",
    "草地": "grass", "树": "tree", "树林": "forest", "树枝": "branch",
    "花瓣": "petals", "落花": "falling petals", "水面": "water",

    # ---------- 负面词（写中文负面提示词时用） ----------
    "最差画质": "worst quality", "最差的画质": "worst quality",
    "低质量": "low quality", "画质差": "low quality",
    "低分辨率": "lowres", "分辨率低": "lowres",
    "模糊不清": "blurry", "模糊": "blurry", "失焦": "blurry",
    "多余的手指": "extra fingers", "多余手指": "extra fingers",
    "手指缺失": "missing fingers", "少手指": "fewer digits",
    "多余肢体": "extra limbs", "人体崩坏": "bad anatomy",
    "解剖错误": "bad anatomy", "比例失调": "bad proportions",
    "手崩了": "bad hands", "多头": "multiple heads",
    "重复": "duplicate", "崩坏": "deformed", "畸形": "deformed",
    "文字": "text", "水印": "watermark", "签名": "signature",
    "用户名": "username", "标志": "logo", "边框": "border",
    "裁剪": "cropped", "裁切": "cropped", "伪影": "jpeg artifacts",
    "噪点": "noise", "颗粒": "grain", "过曝": "overexposed",
    "欠曝": "underexposed", "丑": "ugly",
}

_TAG_KEYS_CACHE = None
_PUNCT_RE = re.compile(r"[，,。；;、\n\r\t]+")
_STOP_TOKENS = {"a", "an", "the", "of", "in", "on", "at", "to", "and",
                "with", "is", "are", "it", "this", "that", "very"}
_PARTICLES = "的了着吗呢啊吧"

# 正向提示词里绝不能出现的词：机翻残句可能把「模糊」翻成 blurry，
# 一通塞进去整张图就糊了。
_NEG_WORDS = {
    "blurry", "low quality", "worst quality", "lowres", "noise", "grain",
    "jpeg artifacts", "deformed", "ugly", "bad anatomy", "bad hands",
    "text", "watermark", "signature", "username", "cropped", "error",
    "extra digits", "fewer digits", "missing fingers", "extra limbs",
}
# 逐词检查用：片段里只要出现这些词就整个丢掉
_NEG_TOKENS = {"blurry", "blur", "ugly", "deformed", "noise", "noisy",
               "grain", "lowres", "cropped", "watermark", "signature",
               "jpeg", "artifacts"}


def _tag_keys():
    """按长度降序的键表，保证长词优先命中。"""
    global _TAG_KEYS_CACHE
    if _TAG_KEYS_CACHE is None:
        _TAG_KEYS_CACHE = sorted(TAG_DICT, key=len, reverse=True)
    return _TAG_KEYS_CACHE


def _split_tags(s):
    return [t.strip() for t in re.split(r"[,，]", s or "") if t.strip()]


def _en_fragments(tr, positive=True):
    """把机器翻译的残句拆成干净标签。

    只保留短名词短语——整句英语对 CLIP 几乎没用，还会稀释前面的好标签。
    """
    tr = (tr or "").strip()
    tr = re.sub(r"\.\s+", ", ", tr)          # 句号当分隔符，小数不受影响
    tr = re.sub(r"[.!?。！？]+$", "", tr)
    out = []
    for t in re.split(r"[,，;；]", tr):
        t = t.strip().lower()
        if not t or t in _STOP_TOKENS:
            continue
        words = t.split()
        if len(words) > 4:
            continue                          # 长句丢掉
        if positive and (t in _NEG_WORDS or _NEG_TOKENS.intersection(words)):
            continue                          # 别把「模糊」这类词塞进正向
        out.append(t)
    return out


def _dedupe(tags):
    seen, out = set(), []
    for t in tags:
        k = t.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(t.strip())
    return out


def optimize_prompt(text, quality=True):
    """中文提示词 → danbooru 英文标签。

    先按标点切段，每段做「长词优先」的查表替换，表里没有的残句再交给
    Argos 翻译。这样「双马尾」会变成 twintails，而不是机器翻译的
    Two ponytails —— 后者模型基本不认识，所以描述就「消失」了。

    纯英文输入原样返回，不做任何改动。quality=False 用于负面提示词，
    不会自动补质量词。
    """
    text = (text or "").strip()
    if not text:
        return ""
    if not has_chinese(text):
        return text

    tags = []
    for chunk in _PUNCT_RE.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue

        # 整段精确命中（覆盖「黑色长直发」这类固定搭配）
        if chunk in TAG_DICT:
            tags.extend(_split_tags(TAG_DICT[chunk]))
            continue

        # 长词优先的子串扫描
        rest = chunk
        for zh in _tag_keys():
            if zh in rest:
                val = TAG_DICT[zh]
                if val:
                    tags.extend(_split_tags(val))
                rest = rest.replace(zh, " ")
        for p in _PARTICLES:            # 虚词直接丢
            rest = rest.replace(p, " ")
        rest = rest.strip()
        if len(rest) <= 1:
            continue        # 单个字基本是「的/前」这类残渣，翻了只会添乱

        # 表里查不到的残句才用机器翻译兜底
        if has_chinese(rest):
            for c in _PUNCT_RE.split(rest):
                if c.strip():
                    tags.extend(_en_fragments(translate_text(c.strip()),
                                              positive=quality))
        elif rest:
            tags.extend(_en_fragments(rest, positive=quality))

    tags = _dedupe(tags)

    # 正向提示词里混进 blurry / low quality 这类词会直接毁图，
    # 不管它来自词表还是机翻，统一清掉。
    if quality:
        tags = [t for t in tags
                if t.lower() not in _NEG_WORDS
                and not _NEG_TOKENS.intersection(t.lower().split())]

    if not tags:
        return text

    if quality:
        low = " ".join(tags).lower()
        if not any(q in low for q in _QUALITY_WORDS):
            tags = _split_tags(QUALITY_TAGS) + tags

    return ", ".join(_dedupe(tags))[:1200]
