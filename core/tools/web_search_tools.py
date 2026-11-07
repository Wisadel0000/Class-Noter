import requests
from loguru import logger
from pydantic import BaseModel, Field

from core.tools.ToolsManager import ToolsManager
from settings.setting_store import SettingStore

class WebSearchTools:
    def __init__(self, tools_manager:ToolsManager, setting_store:SettingStore):
        self.setting = setting_store.get("provider_setting")
        self._page_cache: dict[str,dict] = {}   # web_search时拿到的页面会缓存在这里
        tools_manager.register(
            name="web_search",
            tool_func=self.web_search,
            description="""
用于联网搜索与query相关的网页。
返回一个网页列表，每个网页包含信息：
- 排序分数 - 0～3 分，综合考虑相关性、权威性、时效性等维度，大于等于 1.5 分为优质结果。
- 标题
- url
- 摘要 - 网页中与你的搜索目标相关的信息摘要
- 站点名称 - 缺失时为None
- 发布时间 - 统一为 UTC 的 RFC 3339 格式，未知时为 null
- 网页权威性 - 0～4（-1 表示未知权威性），大于等于 3 为极权威结果。
""",
            args_schema=self.web_search_args
        )
        tools_manager.register(
            name="web_fetch",
            tool_func=self.web_fetch,
            description="""
用于抓取指定url的网页内容
返回的结果包含：
标题 - 页面标题，缺失时为空字符串。
正文 - 抓取后的 Markdown 正文。
Fetch 的结果受目标站点的可用性和访问策略影响。
""",
            args_schema=self.web_fetch_args
        )
        tools_manager.tool_set_register("web_search_tools", [
            "web_search",
            "web_fetch",
        ])
        logger.debug("联网搜索工具已组装完成")

    class web_search_args(BaseModel):
        query:str = Field(description="""
query是你要搜索的内容，可以直接搜索字符串，也可以组合使用下面提供的搜索语法
## 搜索语法
query 中的搜索语法会原样传递给搜索服务。下表中的示例将操作符与搜索词组合使用；你可以在一个 query 中组合多个操作符。
| 操作符 | 示例 | 说明 |
| --- | --- | --- |
| `site:` | `DeepSeek site:github.com` | 将结果限制在指定站点，指定多个时用空格分隔并通过 OR 连接，例如 `DeepSeek site:github.com OR site:huggingface.co`。 |
| `-site:` | `DeepSeek -site:example.com` | 排除指定站点，指定多个时用空格分隔。 |
| `-` | `DeepSeek -广告` | 排除包含指定关键词的网页，指定多个时用空格分隔。 |
| `-"..."` | `DeepSeek -"release notes"` | 排除包含指定短语的网页，短语内可以包含空格，指定多个时用空格分隔。 |
| `"..."` | `DeepSeek "精确短语"` | 精确匹配指定短语，指定多个时用空格分隔。 |
| `lang:` | `DeepSeek lang:zh,en` | 将结果限制在指定语言，多种语言用逗号分隔，例如 `lang:zh,en`。 |
| `after:` | `DeepSeek after:2025` 或 `DeepSeek after:2025-01-01` | 将结果限制在指定日期之后发布的网页。 |
| `before:` | `DeepSeek before:2026` 或 `DeepSeek before:2026-06-01` | 将结果限制在指定日期之前发布的网页。 |
""")
    def web_search(self,query:str):
        """
        用于联网搜索与query相关的网页。
        返回一个网页列表，每个网页包含信息：
        - 排序分数 - 0～3 分，综合考虑相关性、权威性、时效性等维度，大于等于 1.5 分为优质结果。
        - 标题
        - url
        - 摘要 - 网页中与你的搜索目标相关的信息摘要
        - 站点名称 - 缺失时为None
        - 发布时间 - 统一为 UTC 的 RFC 3339 格式，未知时为 null
        - 网页权威性 - 0～4（-1 表示未知权威性），大于等于 3 为极权威结果。
        搜索正常结束但没有匹配结果时，返回空数组。
        """
        # if self.setting.seartch_api == "deepseek"
        result = self._deepseek_web_search(query,self.setting.deepseek_web_search_api)
        logger.debug(f"联网搜索:{query},\n搜索结果:{result}")
        return result

    class web_fetch_args(BaseModel):
        url:str = Field(description="你要抓取的页面的url")
    def web_fetch(self,url:str):
        """
        用于抓取指定url的网页内容
        返回的结果包含：
        标题 - 页面标题，缺失时为空字符串。
        正文 - 抓取后的 Markdown 正文。
        Fetch 的结果受目标站点的可用性和访问策略影响。
        """
        result = self._fetch_in_cache(url)
        if result is None:
            result = self._deepseek_web_fetch(url,self.setting.deepseek_web_search_api)
        logger.debug(f"抓取了网页:{url}\n抓取文本长度{len(result)}")
        #logger.debug(f"网页抓取结果：{result}")
        return result

    def _fetch_in_cache(self,url:str):
        result = self._page_cache.get(url,None)
        if result is None:
            return None    #缓存里没有就返回None了
        else:
            return f"""
标题：{result["title"]}
正文：{result["content"]}
"""

    def _deepseek_web_search(self, query, api_key):
        response = requests.post(
            "https://api.deepseek.com/v1/tools/search",
            headers={
                f"Authorization": f"Bearer {api_key}",
            },
            json={
                "query": f"{query}",
                "count": 10,  # 默认搜索10个网页
                "need_content": False,  # 不返回结果，等待ai主动Fetch抓取
            }
        )
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            return "网络请求时出现问题，搜索失败"
        build_result = []
        for result in response.json()["results"]:
            self._page_cache[result["url"]] = result    #缓存结果
            tmp = f"""
排序分数:{result["rerank_score"]}
标题:{result["title"]}
url:{result["url"]}
摘要:{result["summary"]}
站点名称:{result["site_name"]}
页面发布时间:{result["date"]}
网页权威性:{result["authority"]}
"""
            build_result.append(tmp)
        return str(build_result)

    def _deepseek_web_fetch(self, url, api_key):
        response = requests.post(
            "https://api.deepseek.com/v1/tools/fetch",
            headers={
                f"Authorization": f"Bearer {api_key}",
            },
            json={"url": f"{url}"},
        )
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            return "网络请求时出现问题，抓取失败"
        page = response.json()
        content_result = f"""
标题：{page["title"]}
正文：{page["content"]}
"""
        logger.debug(f"Fetch网页抓取：{content_result}")
        return content_result