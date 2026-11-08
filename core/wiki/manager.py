import threading
from concurrent.futures import ThreadPoolExecutor
from loguru import logger
from pydantic import BaseModel, Field

from event.event_core import Bus,Loop,Router
from event.events import WikiEditFinish,WikiUpdate,AppClose
from settings.setting_store import SettingStore
from core.tools.ToolsManager import ToolsManager
from settings.wiki_settings import WikiSetting
from wikiencoder import WikiStore,WikiPage,ops,parse
from wikiencoder.validate import lint_page
from wikiencoder.index import WikiIndex
from wikiencoder.export import export_site,export_page

#
# class Sections(TypedDict):
#     section_title: str = Field(description="字符串，板块标题，仅可填写“正文”或者自定义板块的名字")
#     content: str = Field(description="字符串，板块内容")
#
# class InfoInBox(TypedDict):
#     info_name: str = Field(description="字符串，本行信息的键名")
#     content: str = Field(description="字符串，本行信息的内容")
#


"""
wiki管理器要集中读取wiki文件实例创建对应page对象
并提供进行逻辑包装过的工具函数，比如自动完成保存、仓库合法性验证
提供基于store的仓库查找方式，并自动发送事件提醒页面源变化。
以及事件驱动的落盘管理
"""

class WikiManager:
    def __init__(self,core_bus_router:Router, core_loop:Loop, local_bus:Bus, local_loop:Loop,setting_store:SettingStore,tools_manager:ToolsManager):
        self._core_loop = core_loop
        self._local_bus = local_bus
        self._local_loop = local_loop
        self._tools_manager: ToolsManager = tools_manager
        self._setting: WikiSetting = setting_store.get("wiki_setting")

        self._store = WikiStore(self._setting.raw_path, author="Nairy")
        self._pages: dict[str,WikiPage] ={}
        self._changed: list[str] = []   # 发生了改变且没有渲染至导出文件夹的页面（的名字）
        self._rlock =  threading.RLock()
        self._thread_pool = ThreadPoolExecutor(max_workers=1)
        self._thread_pool_over = threading.Event()

        # ------ 设置更新订阅 ------
        setting_store.subscribe("wiki_setting",self._setting_reload)

        # ------ 关闭时阻塞事件 ------
        self._local_loop.register_stop_waiting_event(self._thread_pool_over)

        # ------ 注册回调 ------
        self._local_bus.subscribe(WikiEditFinish,self.export_local_site)

        # ------ 订阅总线事件 ------
        core_bus_router.subscribe(WikiEditFinish,self._local_loop)
        core_bus_router.subscribe(AppClose,self._local_loop)

        # ------ 工具注册 ------
        self._tools_manager.register("show_all_page",
                                     self.show_all_page,
                                     "列出库中所有已有词条的名称，每一个对应词条的页面都可以用这里返回的名称索引到。",
                                     log_func=self.show_all_page_log)
        self._tools_manager.register("edit_page_by_str",
                                     self.edit_page_by_str,
                                     "提供符合wiki语法的字符串，以创建对应词条的页面或者用新内容覆盖对应词条的页面，为了保护页面的编辑历史，请在覆盖旧页面时原样保留原本的“编辑记录”板块的内容，仅通过提供的commit_message参数来添加新的编辑记录。本方法会自动检查语法的合法性和健全性，并返回错误码，如果存在“error”和“warn”级别的错误将不会保存本次修改",
                                     args_schema=self.edit_page_by_str_args,
                                     log_func=self.edit_page_by_str_log)
        self._tools_manager.register("delete_page",
                                     self.delete_page,
                                     "删除一个词条对应的页面",
                                     args_schema=self.delete_page_args,
                                     log_func=self.delete_page_log)
        self._tools_manager.register("read_page",
                                     self.read_page,
                                     "阅读一个词条对应的页面",
                                     args_schema=self.read_page_args,
                                     log_func=self.read_page_log)
        self._tools_manager.register("amend_edit_record",
                                     self.amend_edit_record,
                                     "修改对应页面指定索引的编辑记录",
                                     args_schema=self.amend_edit_record_args,
                                     log_func=self.amend_edit_record_log)
        self._tools_manager.register("del_edit_record",
                                     self.del_edit_record,
                                     "删除对应页面指定索引的编辑记录",
                                     args_schema=self.del_edit_record_args,
                                     log_func=self.del_edit_record_log)
        # ------ 工具集注册 -----
        self._tools_manager.tool_set_register("wiki_tool_set",
                                              ["show_all_page",
                                               "edit_page_by_str",
                                               "read_page",
                                               "delete_page",
                                               "amend_edit_record",
                                               "del_edit_record"])

    """
    集中管理page，已经读过的page对象存起来，不手动读取
    要自动完成对项目的保存和其他应当随手完成的工作。    #完成
    要求每次修改页面前至少应该让ai看一遍原文   #提示词里写了
    我想我应该直接让ai读原文，让ai学一下wiki语法格式，改的时候一起改，也许可以减少阅读次数 #是这样做的
    留意如果语法介绍没说的话要给ai单独解释一下section的定义    #说过了
    记得让在ai的工具节点中捕捉error # finish
    关于合法校验：subagent工作时强行加一个校验节点，手动对库合法性进行检查然后如果有异常信息就把加入错误信息状态抛回agent节点
    """

    def _setting_reload(self,setting:WikiSetting):
        self._setting = setting

    # ------ 消息响应 ------

    def when_app_close(self):
        self._thread_pool.shutdown()
        self._thread_pool_over.set()

    def export_local_site(self,event: WikiEditFinish):
        self._thread_pool.submit(self._all_export)  # TODO现在每次保存全库效率有点低下了，记得更新下wiki工具添加新功能
        self._core_loop.post(WikiUpdate())

    # ------ 方法 ------

    def _all_export(self):
        """全库导出"""
        with self._rlock:
            export_site(self._store,
                        out_dir = self._setting.out_path,
                        site_name=self._setting.site_name
                        )

    def _single_export(self,slug: str):
        """单页导出，渲染导出某一个单独的页面，
        使用了Rlock所以外部允许不加锁，如果后续把Rlock改成了lock，则此函数外部必须加锁同时把本函数内部的锁删掉，防止死锁"""
        with self._rlock:
            export_page(self._store,
                        slug=slug,
                        out_dir=self._setting.out_path,
                        with_related=True,
                        )

    def _get_page(self, slug: str) -> WikiPage:
        if slug in self._pages:
            return self._pages[slug]
        else:
            try:
                page = self._store.load(slug)
                self._pages[slug] = page
                return page
            except FileNotFoundError as e:
                logger.info(f"在储存和内存中均未能找到页面:{slug}")
                raise e

    def get_wiki_path(self):
        """获取本地wiki文件所在的根目录"""
        return self._setting.out_path

    # ------ Agent工具 ------
    # 查看库中词条列表
    def show_all_page(self):
        """列出库中所有已有词条的名称，每一个对应词条的页面都可以用这里返回的名称索引到。"""
        with self._rlock:
            return str(self._store.slugs())
    def show_all_page_log(self):
        return "查看了所有已有词条的页面名"

    class edit_page_by_str_args(BaseModel):
        entry: str = Field(description="字符串，要创建/修改的词条名")
        content: str = Field(description="字符串，具体的页面内容，应当严格符合wiki语法，并尽量保证链接合法可以正确索引到具体页面，否则可能无法保存")
        commit_message: str = Field(description="提交信息，每轮次修改的提交信息都会新增在编辑记录的表格中，确保wiki的编辑历史清晰可追溯")
    def edit_page_by_str(self, entry: str, content: str, commit_message: str) -> str:
        """提供符合wiki语法的字符串，以创建对应词条的页面或者用新内容覆盖对应词条的页面，为了保护页面的编辑历史，请在覆盖旧页面时原样保留原本的“编辑记录”板块的内容，仅通过提供的commit_message参数来添加新的编辑记录。本方法会自动检查语法的合法性和健全性，并返回错误码，如果存在“error”级别的错误将不会保存本次修改"""
        # 构建对象
        page = parse(content, path=self._store.path_for(entry))  # 用str新建页面对象，从store中构建出一个基于store路径的文件路径，以确保保存时可以保存进库中
        page.slug = entry  # 显式赋值，防止文本里写了别的 slug
        # 页面合法性检查
        report = lint_page(page, WikiIndex(self._store), slug= entry).to_dict()
        if not report["ok"]:
            logger.info(f"本次页面{entry}保存失败，存在error")
            return f"页面存在error，本次未保存。诊断报告:{report["items"]}"
        else:
            with self._rlock:
                ops.add_edit_record(page, message=commit_message, date=page.created, author="Agent")
                self._pages[entry] = page   # 更新内存中的页面对象
                self._store.save(page)  # 不存在就新建，存在就整页覆盖
            return f"页面保存成功, 附诊断报告:{report["items"]}"
    def edit_page_by_str_log(self,  entry: str, content: str, commit_message: str):
        return f"创建/修改了{entry}页面：{commit_message}"

    # 删除词条
    class delete_page_args(BaseModel):
        entry: str = Field(description="字符串，要删除的词条名")
    def delete_page(self, entry: str):
        """删除一个词条对应的页面"""
        with self._rlock:
            if entry in self._pages:
                self._pages.pop(entry, None)
            self._store.delete(entry)
    def delete_page_log(self, entry: str):
        return f"删除了{entry}页面"

    # 阅读词条
    class read_page_args(BaseModel):
        entry: str = Field(description="字符串，要阅读的词条名")
    def read_page(self, entry: str) -> str:
        """阅读指定词条的页面"""
        with self._rlock:
            page = self._get_page(entry)
            return page.to_text()   #直接把原文发给ai
    def read_page_log(self, entry: str):
        return f"阅读了{entry}页面"

    class amend_edit_record_args(BaseModel):
        entry: str = Field(description="字符串，要修改编辑记录的词条名")
        index: int = Field(description="整数，要修改的编辑记录的索引编号")
        new_message: str = Field(description="字符串，新的提交信息")
    def amend_edit_record(self,entry:str,index:int,new_message:str):
        """修改对应页面指定索引的编辑记录"""
        with self._rlock:
            page = self._get_page(entry)
            ops.amend_edit_record(page=page,n=index,message=new_message)
            self._store.save(page)
    def amend_edit_record_log(self,entry:str,index:int,new_message:str):
        return f"修改了{entry}页面的第{index}条编辑记录为：{new_message}"

    class del_edit_record_args(BaseModel):
        entry: str = Field(description="字符串，要删除编辑记录的词条名")
        index: int = Field(description="整数，要删除的编辑记录的索引编号")
    def del_edit_record(self,entry:str,index:int):
        """删除对应页面指定索引的编辑记录"""
        with self._rlock:
            page = self._get_page(entry)
            ops.remove_edit_record(page=page,n=index)
            self._store.save(page)
    def del_edit_record_log(self, entry: str, index: int):
        return f"删除了{entry}页面的第{index}条编辑记录"

    # class create_new_page_args(BaseModel):
    #     title: str = Field(description= "字符串，新建的知识词条的名字，同时也是页面标题，最好相对简洁、概括，直接以该知识的名字命名最佳。")
    #     kind: str | None = Field(default= None, description= "字符串，该页面的知识属于的‘类型’，比如‘方法’、‘概念’、‘定理’等，每个页面只同时拥有一个对应的‘类型’值，这个值会在构建知识库的索引页时用来给每个页面进行分类，便于查找")
    #     tags: list[str] | None = Field(default= None, description= "字符串列表，是该知识点相关的“标签”列表，每个页面可以同时有多个不同的标签")
    #     preamble: str | None = Field(default= None, description="字符串，该知识词条的“序言”部分，可以在这里写页面的序言或者介绍知识点的定义，语法使用请参考语法说明")
    #     body: str | None = Field(default= None, description="字符串，该页面的“正文”部分，可以在这里对知识点进行展开和详细解释，语法使用请参考语法说明")
    #     extra: dict[str, str] | None = Field(default= None, description="格式为{板块1名称:正文内容1, 板块2名称:正文内容2, ...}，想要添加正文以外的自定义的板块可使用此参数，自定义板块会以和正文相同的形式渲染，基础语法与正文相同都是markdown，语法使用请参考语法说明")
    #     commit_message: str = Field(description="提交信息，所有的提交信息都会出现在编辑历史的表格中，确保wiki的编辑历史清晰可追溯")
    #
    # # 创建新词条
    # def create_new_page(self,
    #                     title: str,                     # 标题
    #                     kind: str | None = None,        # 知识点类型（概念/定理/方法 等更多自定义分类）
    #                     tags: list[str] | None = None,  # 标签（列表）
    #                     preamble: str | None = None,    # 序言/定义（正文语法）
    #                     body: str | None = None,        # 详细正文（正文语法）
    #                     extra: dict[str, str] | None = None,    # 自定义板块{板块名:内容}
    #                     commit_message: str = "新建了本词条",
    #                     ):
    #     """创建一个新的wiki知识词条页面的骨架部分，参数包含标题、分类、标签、序言、正文、自定义板块和提交信息。创建至少含有标题和提交信息。其他的参数如果为None则表示创建时不使用该参数。"""
    #     kwargs= {"title": title}
    #     if kind:
    #         kwargs["kind"] = kind
    #     if tags:
    #         kwargs["tags"] = tags
    #     if preamble:
    #         kwargs["preamble"] = preamble
    #     if body:
    #         kwargs["body"] = body
    #     if extra:
    #         kwargs["extra"] = extra
    #     result = self._store.create(**kwargs)
    #     ops.add_edit_record(result.page,message=commit_message,date=result.page.created,author="Nairy")


    # （修改）词条描述信息替换/追加 - 应附赠一个commit信息参数

    # class edit_page_args(BaseModel):
    #     entry: str = Field(description="字符串，要修改的词条名")
    #     set_title: str | None = Field(default= None, description="字符串，要改成的新标题")
    #     set_kind: str | None = Field(default= None, description="字符串，要改成的新分类")
    #     set_tags: list[str] | None = Field(default= None, description="字符串列表，要改成的新标签列表（会覆盖原本的所有标签）")
    #     set_preamble: str | None = Field(default= None, description="字符串，新的序言")
    #     set_sections: list[Sections] | None = Field(default= None, description="字典列表，用于修改正文和自定义板块，正文的板块名是“正文”，自定义板块名则是对应板块的标题，语法使用请参考语法说明")
    #     set_infobox: list[dict[str, str]] | None = Field(default= None, description="格式为[{信息框名称（字符串）:信息框内容（字符串）},...]，用于修改信息框，语法使用请参考语法说明")
    #
    # # 替换信息（给什么改什么）
    # def edit_page_by_set(self,
    #                        entry:str,
    #                        set_title: str|None = None,
    #                        set_kind: str|None = None,
    #                        set_tags: list[str]|None = None,
    #                        set_preamble: str|None = None,
    #                        set_sections: list[dict[str, str]]|None = None,
    #                        set_infobox: list[dict[str, str]]|None = None,
    #                        commit_message: str = "[默认信息]Agent没有上传提交信息",
    #                        ):
    #     """给指定的词条页面覆盖式设置信息，可以对标题、分类、标签、序言、板块和信息框进行修改，新内容会完全覆盖对应板块原本的信息"""
    #     #try:
    #     page = self._get_page(entry)
    #     ops.set_title(page, set_title)  # 改标题
    #     ops.set_kind(page, set_kind)    # 修改词条分类
    #     ops.set_tags(page,tags=set_tags)    #标签
    #     ops.set_preamble(page, set_preamble)    # 覆盖序言
    #     # 这玩意能不能加新东西？
    #     for section in set_sections:
    #         ops.set_section(page, name= section["section_title"], text= section["content"])
    #     for info in set_infobox:
    #         ops.set_infobox(page, key= info["info_name"], value= info["content"])
    #     ops.add_edit_record(page, message=commit_message, date=page.created, author="Nairy")
    #
    # # 仅追加信息（给什么改什么）
    # def edit_page_by_add(self,
    #                      entry:str,
    #                      add_aliases: list[str]|None,
    #                      add_tags: list[str]|None,
    #                      append_preamble: str|None,
    #                      append_sections: list[dict[str, str]]|None,
    #                      add_seealso: list[dict[str,str]]|None,
    #                      add_source_text: list[dict[str,str]]|None,
    #                      add_source_with_url: list[dict[str,str]]|None,
    #                      commit_message: str,
    #                      ):
    #     #try:
    #     page = self._get_page(entry)
    #     for alias in add_aliases:
    #         ops.add_alias(page, alias)  # 别名
    #     for tag in add_tags:
    #         ops.add_tag(page, tag)  # 标签
    #     ops.append_preamble(page, append_preamble)  # 追加
    #     for section in append_sections:
    #         ops.append_section(page, name= section["section_title"], text= section["content"])
    #     for seealso in add_seealso:
    #         ops.add_seealso(page, target= seealso["target"], note= seealso["note"])
    #     for source in add_source_text:
    #         ops.add_source(page, kind= source["source_kind"], text= source["describe"])
    #     for source in add_source_with_url:
    #         ops.add_source(page, kind= source["source_kind"], text= source["describe"] ,url= source["url"])
    #     ops.add_edit_record(page, message=commit_message, date=page.created, author="Nairy")
    #
    #
    # def edit_page_by_remove(self,
    #                         entry:str,
    #                         remove_tags: list[str]|None,
    #                         remove_sections: list[str]|None,
    #                         remove_infoboxs: list[str]|None,
    #                         remove_seealsos: list[str]|None,
    #                         commit_message: str,
    #                         ):
    #     # try:
    #     page = self._get_page(entry)
    #     for tag in remove_tags:
    #         ops.remove_tag(page, tag)
    #     for section in remove_sections:
    #         ops.remove_section(page, section)
    #     for info in remove_infoboxs:
    #         ops.remove_infobox(page, info)
    #     for seealso in remove_seealsos:
    #         ops.remove_seealso(page, seealso)
    #     ops.add_edit_record(page, message=commit_message, date=page.created, author="Nairy")

    # 修改，删除编辑历史
