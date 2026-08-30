"""股票智能搜索服务。

数据源优先级：
1. baostock query_all_stock（全市场，含实时名称）
2. 内置常用股票列表（约200只热门股，含名称）

搜索匹配维度：
- baostock代码（sh.600036）
- 纯数字代码（600036）
- 中文名称（招商银行）
- 拼音首字母简拼（zsyh）
"""
from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional

# 内置常用股票列表（baostock代码, 名称）
_FALLBACK_STOCKS: List[tuple[str, str]] = [
    # ---- 上证 ----
    ("sh.600000", "浦发银行"), ("sh.600009", "上海机场"), ("sh.600010", "京能电力"),
    ("sh.600011", "华能国际"), ("sh.600015", "华夏银行"), ("sh.600016", "民生银行"),
    ("sh.600018", "上港集团"), ("sh.600019", "宝钢股份"), ("sh.600023", "浙能电力"),
    ("sh.600025", "华能水电"), ("sh.600028", "中国石化"), ("sh.600029", "南方航空"),
    ("sh.600030", "中信证券"), ("sh.600031", "三一重工"), ("sh.600036", "招商银行"),
    ("sh.600048", "保利发展"), ("sh.600050", "中国联通"), ("sh.600061", "国投资本"),
    ("sh.600066", "宇通客车"), ("sh.600068", "葛洲坝"), ("sh.600085", "同仁堂"),
    ("sh.600089", "特变电工"), ("sh.600104", "上汽集团"), ("sh.600109", "国金证券"),
    ("sh.600111", "北方稀土"), ("sh.600115", "中国东航"), ("sh.600118", "中国卫星"),
    ("sh.600150", "中国船舶"), ("sh.600160", "巨化股份"), ("sh.600176", "中国巨石"),
    ("sh.600177", "雅戈尔"), ("sh.600183", "生益科技"), ("sh.600188", "兖矿能源"),
    ("sh.600196", "复星医药"), ("sh.600208", "新湖中宝"), ("sh.600219", "南山铝业"),
    ("sh.600221", "海南航空"), ("sh.600233", "圆通速递"), ("sh.600271", "航天信息"),
    ("sh.600276", "恒瑞医药"), ("sh.600282", "南钢股份"), ("sh.600298", "安琪酵母"),
    ("sh.600309", "万华化学"), ("sh.600325", "华发股份"), ("sh.600332", "白云山"),
    ("sh.600340", "华夏幸福"), ("sh.600346", "恒力石化"), ("sh.600352", "精达股份"),
    ("sh.600362", "江西铜业"), ("sh.600369", "西南证券"), ("sh.600372", "中航电子"),
    ("sh.600383", "金地集团"), ("sh.600390", "五矿资本"), ("sh.600406", "国电南瑞"),
    ("sh.600415", "小商品城"), ("sh.600426", "福耀玻璃"), ("sh.600433", "冠豪高新"),
    ("sh.600438", "通威股份"), ("sh.600446", "立讯精密"), ("sh.600460", "士兰微"),
    ("sh.600498", "烽火通信"), ("sh.600519", "贵州茅台"), ("sh.600521", "华海药业"),
    ("sh.600528", "中铁工业"), ("sh.600529", "山东药玻"), ("sh.600547", "山东黄金"),
    ("sh.600548", "深高速"), ("sh.600549", "厦门钨业"), ("sh.600588", "用友网络"),
    ("sh.600585", "海螺水泥"), ("sh.600598", "北大荒"), ("sh.600600", "青岛啤酒"),
    ("sh.600606", "绿地控股"), ("sh.600633", "浙数文化"), ("sh.600637", "东方明珠"),
    ("sh.600660", "福耀玻璃"), ("sh.600663", "陆家嘴"), ("sh.600690", "海尔智家"),
    ("sh.600703", "三安光电"), ("sh.600705", "中航产融"), ("sh.600745", "闻泰科技"),
    ("sh.600746", "中泰化学"), ("sh.600760", "中航沈飞"), ("sh.600776", "东方通信"),
    ("sh.600779", "水井坊"), ("sh.600782", "新钢股份"), ("sh.600808", "马钢股份"),
    ("sh.600837", "海通证券"), ("sh.600839", "四川长虹"), ("sh.600871", "中国能建"),
    ("sh.600886", "国投电力"), ("sh.600887", "伊利股份"), ("sh.600893", "航发动力"),
    ("sh.600900", "长江电力"), ("sh.600905", "三峡能源"), ("sh.600918", "中泰证券"),
    ("sh.600919", "江苏银行"), ("sh.600926", "杭州银行"), ("sh.600941", "中国移动"),
    ("sh.600958", "东方证券"), ("sh.600989", "宁德时代"), ("sh.600999", "招商证券"),
    # ---- 深证 ----
    ("sz.000001", "平安银行"), ("sz.000002", "万科A"), ("sz.000063", "中兴通讯"),
    ("sz.000066", "中国长城"), ("sz.000069", "华侨城A"), ("sz.000100", "TCL科技"),
    ("sz.000157", "中联重科"), ("sz.000333", "美的集团"), ("sz.000338", "潍柴动力"),
    ("sz.000402", "金融街"), ("sz.000408", "藏格矿业"), ("sz.000425", "徐工机械"),
    ("sz.000498", "华仁药业"), ("sz.000501", "鄂武商A"), ("sz.000538", "云南白药"),
    ("sz.000568", "泸州老窖"), ("sz.000596", "古井贡酒"), ("sz.000625", "长安汽车"),
    ("sz.000651", "格力电器"), ("sz.000661", "长春高新"), ("sz.000708", "中信特钢"),
    ("sz.000725", "京东方A"), ("sz.000768", "中航西飞"), ("sz.000776", "广发证券"),
    ("sz.000783", "长江证券"), ("sz.000786", "北新建材"), ("sz.000800", "一汽解放"),
    ("sz.000807", "云铝股份"), ("sz.000858", "五粮液"), ("sz.000876", "新希望"),
    ("sz.000895", "双汇发展"), ("sz.000938", "紫光股份"), ("sz.000963", "华东医药"),
    ("sz.000999", "华润三九"), ("sz.001979", "招商蛇口"), ("sz.002007", "华兰生物"),
    ("sz.002027", "分众传媒"), ("sz.002032", "苏泊尔"), ("sz.002049", "紫光国微"),
    ("sz.002050", "三花智控"), ("sz.002056", "横店东磁"), ("sz.002065", "东华软件"),
    ("sz.002074", "华数传媒"), ("sz.002081", "金螳螂"), ("sz.002120", "韵达股份"),
    ("sz.002142", "宁波银行"), ("sz.002146", "荣盛发展"), ("sz.002179", "中航光电"),
    ("sz.002230", "科大讯飞"), ("sz.002236", "大华股份"), ("sz.002241", "歌尔股份"),
    ("sz.002271", "东方雨虹"), ("sz.002304", "洋河股份"), ("sz.002311", "海大集团"),
    ("sz.002352", "顺丰控股"), ("sz.002415", "海康威视"), ("sz.002422", "科伦药业"),
    ("sz.002456", "欧菲光"), ("sz.002460", "赣锋锂业"), ("sz.002466", "天齐锂业"),
    ("sz.002475", "立讯精密"), ("sz.002493", "荣盛石化"), ("sz.002508", "老板电器"),
    ("sz.002555", "三七互娱"), ("sz.002594", "比亚迪"), ("sz.002600", "领益智造"),
    ("sz.002673", "西部证券"), ("sz.002690", "亿纬锂能"), ("sz.002709", "天赐材料"),
    ("sz.002736", "国信证券"), ("sz.002773", "康弘药业"), ("sz.002812", "恩捷股份"),
    ("sz.002821", "三六零"), ("sz.002841", "视源股份"), ("sz.002916", "深南电路"),
    # ---- 创业板 ----
    ("sz.300003", "乐普医疗"), ("sz.300015", "爱尔眼科"), ("sz.300033", "同花顺"),
    ("sz.300054", "梦网科技"), ("sz.300058", "蓝色光标"), ("sz.300059", "东方财富"),
    ("sz.300122", "智飞生物"), ("sz.300124", "汇川技术"), ("sz.300136", "尚品宅配"),
    ("sz.300142", "沃森生物"), ("sz.300144", "宋城演艺"), ("sz.300146", "汤臣倍健"),
    ("sz.300202", "九洲集团"), ("sz.300223", "北京君正"), ("sz.300274", "阳光电源"),
    ("sz.300308", "中际旭创"), ("sz.300316", "晶盛机电"), ("sz.300347", "泰格医药"),
    ("sz.300394", "天孚通信"), ("sz.300413", "芒果超媒"), ("sz.300433", "蓝思科技"),
    ("sz.300435", "中顺洁柔"), ("sz.300498", "温氏股份"), ("sz.300502", "新易盛"),
    ("sz.300529", "健帆生物"), ("sz.300601", "康泰生物"), ("sz.300661", "圣邦股份"),
    ("sz.300750", "宁德时代"), ("sz.300759", "康龙化成"), ("sz.300760", "迈瑞医疗"),
    ("sz.300782", "卓胜微"), ("sz.300832", "新产业"), ("sz.300896", "爱美客"),
    ("sz.300999", "金龙鱼"),
    # ---- 科创板 ----
    ("sh.688001", "中微公司"), ("sh.688005", "容百科技"), ("sh.688006", "杭州柯林"),
    ("sh.688012", "中微公司"), ("sh.688036", "传音控股"), ("sh.688065", "澜起科技"),
    ("sh.688088", "虹软科技"), ("sh.688091", "爱博医疗"), ("sh.688111", "金山办公"),
    ("sh.688126", "沪硅产业"), ("sh.688169", "石头科技"), ("sh.688180", "君实生物"),
    ("sh.688185", "康希诺"), ("sh.688200", "华峰测控"), ("sh.688202", "美迪西"),
    ("sh.688223", "晶合集成"), ("sh.688256", "寒武纪"), ("sh.688272", "富吉瑞"),
    ("sh.688303", "大全能源"), ("sh.688363", "华熙生物"), ("sh.688396", "华润微"),
]


class StockSearchService:
    """股票智能搜索，支持代码/名称/简拼匹配。"""

    _instance: Optional["StockSearchService"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._stocks: List[Dict[str, str]] = []  # [{code, name, pinyin, pure_code}]
        self._loaded = False

    @classmethod
    def instance(cls) -> "StockSearchService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = StockSearchService()
        return cls._instance

    def _ensure_loaded(self):
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            # 先立即加载内置列表（秒级可用），不阻塞
            self._stocks = self._build_index(self._load_fallback())
            self._loaded = True
            # 后台异步尝试从 baostock 更新全市场列表
            threading.Thread(target=self._try_baostock_update, daemon=True).start()

    @staticmethod
    def _build_index(stocks):
        """为股票列表添加简拼和纯代码索引。"""
        try:
            from pypinyin import lazy_pinyin, Style
            for s in stocks:
                s["pinyin"] = "".join(
                    lazy_pinyin(s["name"], style=Style.FIRST_LETTER)
                ).lower()
        except ImportError:
            for s in stocks:
                s["pinyin"] = ""
        for s in stocks:
            s["pure_code"] = s["code"].split(".")[-1] if "." in s["code"] else s["code"]
        return stocks

    def _try_baostock_update(self):
        """后台尝试从 baostock 加载全市场列表，成功则替换内置列表。"""
        stocks = self._load_from_baostock()
        if stocks:
            with self._lock:
                self._stocks = self._build_index(stocks)

    @staticmethod
    def _load_from_baostock() -> List[Dict[str, str]]:
        """从 baostock query_all_stock 加载全市场股票列表（10秒超时）。"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        def _do_load():
            import baostock as bs
            from datetime import datetime, timedelta
            today = datetime.now()
            for back in range(0, 15):
                day = today - timedelta(days=back)
                day_str = day.strftime("%Y-%m-%d")
                lg = bs.login()
                if lg.error_code != "0":
                    continue
                rs = bs.query_all_stock(day=day_str)
                if rs.error_code != "0":
                    bs.logout()
                    continue
                stocks = []
                while rs.next():
                    code = rs.get_row_data()[0]
                    name = rs.get_row_data()[1] if len(rs.get_row_data()) > 1 else ""
                    if not (code.startswith("sh.") or code.startswith("sz.")):
                        continue
                    stocks.append({"code": code, "name": name})
                bs.logout()
                if stocks:
                    return stocks
                break
            return []

        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(_do_load).result(timeout=10)
        except (FuturesTimeout, Exception):
            return []

    @staticmethod
    def _load_fallback() -> List[Dict[str, str]]:
        """内置常用股票列表。"""
        return [{"code": c, "name": n} for c, n in _FALLBACK_STOCKS]

    def search(self, keyword: str, limit: int = 20) -> List[Dict[str, str]]:
        """搜索股票，支持代码/名称/简拼匹配。

        Args:
            keyword: 搜索关键词（代码、名称、简拼、关键词均可）
            limit: 返回条数上限

        Returns:
            [{code, name}] 列表，按匹配优先级排序
        """
        self._ensure_loaded()
        kw = keyword.strip().lower()
        if not kw:
            return []

        exact = []       # 代码精确匹配
        code_prefix = [] # 代码前缀匹配
        name_exact = []  # 名称精确匹配
        name_contains = [] # 名称包含
        pinyin_match = [] # 简拼匹配

        for s in self._stocks:
            pure = s["pure_code"]
            code = s["code"]
            name = s["name"]
            py = s["pinyin"]

            # 纯数字代码精确匹配
            if pure == kw or code.lower() == kw:
                exact.append(s)
            # 代码前缀匹配（600036 -> sh.600036 / 600036）
            elif pure.startswith(kw) or code.lower().startswith(kw):
                code_prefix.append(s)
            # 名称精确匹配
            elif name == keyword.strip():
                name_exact.append(s)
            # 简拼匹配（zsyh -> 招商银行）
            elif py and kw and py.startswith(kw):
                pinyin_match.append(s)
            # 名称包含
            elif kw in name.lower():
                name_contains.append(s)

        results = exact + code_prefix + name_exact + pinyin_match + name_contains
        return results[:limit]
