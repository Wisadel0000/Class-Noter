"""Flet 客户端 — FrontAgent 对话窗口"""
import flet as ft
import threading
import asyncio
import json
from pathlib import Path
from typing import Callable
from loguru import logger
from flet_webview_all import FletWebviewAll

from core.wiki.manager import WikiManager
from event.event_core import Bus,Loop,Router
from event.events import MessageToUser, UserMessage, AppStart, NotingStart, NotingStop, NotingAlready, TaskLogUpdate


class GuiModule:
    def __init__(self, core_bus_router:Router,core_loop:Loop,local_bus:Bus,local_loop:Loop,wiki_manager:WikiManager):
        self._core_loop = core_loop
        self._local_bus = local_bus
        self._local_loop = local_loop
        self._wiki_manager = wiki_manager
        self._chat_history: list[dict] = []
        # 笔记是否正在进行的唯一真源，界面重新挂载时据此恢复按钮状态
        self._noting = False
        # 后台Agent是否已就绪：收到 NotingAlready 之前不允许开始/停止笔记
        self._agent_ready = False
        # 最新一条后台工作日志，收到 TaskLogUpdate 后更新
        self._task_log: dict = {"now_task": None, "content": ""}

        # 界面跑起来后由 main / talk_page 填上的引用
        self._page: ft.Page | None = None
        self._set_messages = None
        self._set_agent_ready = None
        self._set_task_log = None
        # 聊天记录会被 UI 线程和本地总线线程同时读写，加把锁
        self._chat_lock = threading.Lock()

        self._close_backend: Callable|None = None

        # ------ 注册回调函数 ------
        # self._local_bus.subscribe(AppStart,self.app_start)服了flet没法跑在副线程上
        # 助手什么时候说话由它自己决定，这里只负责把收到的消息显示出来
        self._local_bus.subscribe(MessageToUser,self.receive_message)
        self._local_bus.subscribe(NotingAlready,self.noting_already)
        self._local_bus.subscribe(TaskLogUpdate,self.task_log_update)

        # ------ 订阅总线事件 ------
        # core_bus_router.subscribe(AppStart,self._local_loop)
        core_bus_router.subscribe(MessageToUser,self._local_loop)
        core_bus_router.subscribe(NotingAlready,self._local_loop)
        core_bus_router.subscribe(TaskLogUpdate,self._local_loop)

    def main(self,page: ft.Page):
        self._page = page
        page.title = "课堂助手"
        page.window.title_bar_hidden = True
        page.theme_mode = ft.ThemeMode.LIGHT
        page.window.width = 500     #432 (360x1.2)
        page.window.height = 800    #768 (640x1.2)
        #最大最小窗口尺寸
        page.window.min_width = 360
        page.window.min_height = 640
        page.theme = ft.Theme(font_family="Microsoft YaHei")
        page.padding = 10

        # ── 侧边栏 ──
        async def handle_show_drawer(e):
            await page.show_drawer()

        async def handle_change(e):
            idx = e.control.selected_index
            drawer.open = False
            page.update()
            if idx == 0:
                ft.context.page.navigate("/talk")
            elif idx == 1:
                ft.context.page.navigate("/a")
            elif idx == 2:
                ft.context.page.navigate("/config")
            await page.close_drawer()

        async def handle_exit(e):
            # 先切到“正在退出”状态并禁用按钮，避免重复点击
            exit_button.disabled = True
            exit_button.icon = None
            exit_button.content = ft.Row(
                [
                    ft.ProgressRing(width=16, height=16, stroke_width=2),
                    ft.Text("正在退出"),
                ],
                spacing=8,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            page.update()

            page.window.prevent_close = True
            try:
                if self._close_backend:  # 如果传入了关闭后台总线线程的方法
                    logger.info("正在关闭后台线程...")
                    await asyncio.to_thread(self._close_backend)
            finally:
                page.window.prevent_close = False
                await page.window.close()

        exit_button = ft.TextButton(
            "退出程序",
            icon=ft.Icons.LOGOUT,
            on_click=handle_exit,
        )

        drawer = ft.NavigationDrawer(
            on_dismiss=lambda e: None,
            on_change=handle_change,
            controls=[
                ft.Container(height=12),
                ft.NavigationDrawerDestination(
                    label="助手",
                    icon=ft.Icons.CHAT_OUTLINED,
                    selected_icon=ft.Icons.CHAT,
                ),
                ft.NavigationDrawerDestination(
                    label="我的wiki",
                    icon=ft.Icons.ARTICLE_OUTLINED,
                    selected_icon=ft.Icons.ARTICLE,
                ),
                ft.Divider(thickness=2),
                ft.NavigationDrawerDestination(
                    label="选项",
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                ),
                ft.Container(
                    content=exit_button,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                ),
            ],
        )

        page.drawer = drawer

        # ── 路由 ──
        @ft.component
        def rootPage():
            return ft.Router([
                ft.Route(index=True, component=root_page),
                ft.Route(path="/talk", component=talk_page),
                ft.Route(path="/a", component=page_a),
                #TODO：ft.Route(path="/config", component=config_page),  #不许删除这一行
            ])

        # ── 根目录 ──
        @ft.component
        def root_page():
            return ft.Text("这是占位根目录，请访问/talk")

        # ── A 页面（内置浏览器：wiki 库首页） ──
        @ft.component
        def page_a():
            # 相对路径不能直接转 URI，先 resolve 成绝对路径
            index_path = (Path(self._wiki_manager.get_wiki_path()) / "index.html").resolve()
            webview = FletWebviewAll(
                url=index_path.as_uri(),
                allow_navigation=True,  # 允许点击页面内部的链接继续跳转
                expand=True,
            )

            async def go_home(e):
                # 改 url 属性只有在值变化时才会触发加载，页内跳转后 Python 侧 url 没变，
                # 所以直接用 JS 跳回首页
                await webview.run_javascript(
                    f"window.location.href = {json.dumps(index_path.as_uri())};"
                )

            async def reload_page(e):
                await webview.reload()

            async def go_back(e):
                if await webview.can_go_back():
                    await webview.go_back()

            return ft.Container(
                content=ft.Column(
                    [
                        # 窗口标题栏被隐藏了，这里同样保留菜单按钮和拖动区域
                        ft.WindowDragArea(
                            content=ft.Container(
                                content=ft.Row(
                                    [
                                        ft.Row(
                                            [
                                                ft.IconButton(icon=ft.Icons.MENU, on_click=handle_show_drawer),
                                                ft.IconButton(icon=ft.Icons.HOME, tooltip="回到首页", on_click=go_home),
                                                ft.IconButton(icon=ft.Icons.REFRESH, tooltip="刷新", on_click=reload_page),
                                            ],
                                            spacing=0,
                                        ),
                                        ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="返回", on_click=go_back),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                padding=5,
                            ),
                        ),
                        webview,
                    ],
                    spacing=0,
                ),
                expand=True,
            )

        # ── 聊天页面 ──
        @ft.component
        def talk_page():
            messages, set_messages = ft.use_state(self._snapshot_chat())
            # 让总线回调在任意线程都能拿到当前页面的状态更新函数
            self._set_messages = set_messages
            input_text, set_input_text = ft.use_state("")
            noting, set_noting = ft.use_state(self._noting)
            agent_ready, set_agent_ready = ft.use_state(self._agent_ready)
            self._set_agent_ready = set_agent_ready
            task_log, set_task_log = ft.use_state(self._task_log)
            self._set_task_log = set_task_log

            def toggle_noting(e):
                if noting:
                    self._core_loop.post(NotingStop())
                    self._noting = False
                else:
                    self._core_loop.post(NotingStart())
                    self._noting = True
                set_noting(self._noting)

            def send_message(e):
                text = input_text.strip()
                if not text:
                    return
                # 发送和接收已经解耦：用户这边只管把消息投到总线，
                # 助手的回复会在 MessageToUser 到达时由 receive_message 追加
                self._append_chat({"text": text, "is_user": True})
                self._core_loop.post(UserMessage(text))
                set_input_text("")

            def build_bubble(m: dict):
                bubble = ft.Column(
                    [
                        ft.Text("你" if m["is_user"] else "助手", size=14, weight=ft.FontWeight.W_400, color=ft.Colors.GREY_600),
                        ft.Container(
                            content=(
                                ft.Text(m["text"], size=16, weight=ft.FontWeight.W_400, selectable=True)
                                if m["is_user"]
                                else ft.Markdown(
                                    m["text"],
                                    selectable=True,
                                    extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
                                    code_theme=ft.MarkdownCodeTheme.GITHUB,
                                    md_style_sheet=ft.MarkdownStyleSheet(
                                        p_text_style=ft.TextStyle(size=16),
                                    ),
                                )
                            ),
                            padding=12,
                            bgcolor=ft.Colors.GREY_200 if m["is_user"] else ft.Colors.TRANSPARENT,
                            border_radius=10,
                        ),
                    ],
                    spacing=2,  #用户名字和消息气泡之间的间距
                    horizontal_alignment=ft.CrossAxisAlignment.END if m["is_user"] else ft.CrossAxisAlignment.START,
                )
                if m["is_user"]:
                    # 用户消息左侧始终与页面边缘留 50 的间隔（长消息最多只能铺到这儿）
                    return ft.Container(content=bubble, margin=ft.Margin.only(left=50))
                return bubble

            def build_log_line(log: dict):
                now_task = log["now_task"]
                idle = now_task is None
                return ft.Text(
                    spans=[
                        ft.TextSpan("后台任务: ",
                                    style=ft.TextStyle(size=15, color=ft.Colors.GREY_400)),
                        ft.TextSpan("空闲中" if idle else now_task,
                                    style=ft.TextStyle(size=15, color=ft.Colors.GREEN_400 if idle else ft.Colors.RED_400)),
                        ft.TextSpan(" | ",
                                    style=ft.TextStyle(size=15, color=ft.Colors.GREY_200)),
                        ft.TextSpan(log["content"],
                                    style=ft.TextStyle(size=15, color=ft.Colors.GREY_400)),
                    ],
                    max_lines=1,                    # 无论多长都只占一行，不换行撑高
                    overflow=ft.TextOverflow.ELLIPSIS,   # 超长时末尾省略号
                )

            chat_list = ft.ListView(
                controls=[build_bubble(m) for m in messages],
                spacing=20,     #每个消息气泡之间的间距
                expand=True,
                auto_scroll=True,
            )
            input_field = ft.TextField(
                hint_text="输入消息...",
                expand=True,
                border_radius=8,
                value=input_text,
                on_change=lambda e: set_input_text(e.control.value),
                on_submit=send_message,
            )

            return ft.Container(
                content=ft.Column(
                    [
                        # 标题栏被隐藏了，用顶部这一条作为拖动区域（双击可最大化）
                        ft.WindowDragArea(
                            content=ft.Container(
                                content=ft.Row(
                                    [ft.IconButton(icon=ft.Icons.MENU, on_click=handle_show_drawer),
                                     ft.Button(
                                         "停止笔记" if noting else "开始笔记",
                                         icon=ft.Icons.STOP_ROUNDED if noting else ft.Icons.PLAY_ARROW,
                                         bgcolor=(ft.Colors.GREY_200 if not agent_ready
                                                  else ft.Colors.RED_50 if noting
                                                  else ft.Colors.GREEN_500),
                                         color=(ft.Colors.GREY_500 if not agent_ready
                                                else ft.Colors.RED_ACCENT if noting
                                                else ft.Colors.WHITE),
                                         disabled=not agent_ready,
                                         tooltip="后台Agent尚未就绪" if not agent_ready else None,
                                         on_click=toggle_noting,
                                     )],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                padding=5,
                                bgcolor=ft.Colors.TRANSPARENT,

                            ),
                        ),
                        # ── 后台工作日志条 ──
                        ft.Container(
                            content=build_log_line(task_log),
                            alignment=ft.Alignment.CENTER_LEFT,
                            padding=ft.Padding.symmetric(horizontal=10, vertical=4),    #原horizontal=10, vertical=4
                            bgcolor=ft.Colors.TRANSPARENT,
                            border=ft.Border.only(
                                bottom=ft.border.BorderSide(1, ft.Colors.GREY_100)
                            ),
                        ),
                        ft.Container(content=chat_list,
                                     padding= ft.padding.Padding(left=10, top=0, right=10, bottom=10),  #顶部边距为0，其余为10
                                     expand=True),
                        ft.Container(
                            content=ft.Row(
                                [input_field, ft.IconButton(ft.Icons.SEND_ROUNDED, on_click=send_message)],
                                spacing=5,
                            ),
                            padding=10,
                            bgcolor=ft.Colors.TRANSPARENT,
                        ),
                    ],
                    spacing=0,
                ),
                expand=True,
            )

        # ── 配置页面 ──    #TODO配置页暂时先不做了，但是代码先留在这儿
        # @ft.component
        # def config_page():
        #     model_name, set_model_name = ft.use_state(config.get_value("LLM_MODEL"))
        #     api_key, set_api_key = ft.use_state(config.get_value("LLM_API_KEY"))
        #     base_url, set_base_url = ft.use_state(config.get_value("LLM_BASE_URL"))
        #     note_path, set_note_path = ft.use_state(config.get_value("NOTE_ROOT_PATH"))
        #
        #     def save_config(e):
        #         config.save_model_config(
        #             model=model_name,
        #             api_key=api_key,
        #             base_url=base_url,
        #             note_path=note_path,
        #         )
        #
        #     return ft.Container(
        #         content=ft.Column([
        #             ft.IconButton(icon=ft.Icons.MENU, on_click=handle_show_drawer),
        #             ft.Divider(),
        #             ft.Row([ft.Text("模型名："),
        #                     ft.TextField(value=model_name, on_change=lambda e: set_model_name(e.control.value))]),
        #             ft.Row([ft.Text("API密钥："), ft.TextField(value=api_key, password=True, can_reveal_password=True,
        #                                                       on_change=lambda e: set_api_key(e.control.value))]),
        #             ft.Row([ft.Text("BaseURL："),
        #                     ft.TextField(value=base_url, on_change=lambda e: set_base_url(e.control.value))]),
        #             ft.Row([ft.Text("笔记保存根目录："),
        #                     ft.TextField(value=note_path, on_change=lambda e: set_note_path(e.control.value))]),
        #             ft.Row([ft.FilledButton("保存更改", icon=ft.Icons.SAVE, on_click=save_config)]),
        #         ]),
        #         expand=True,
        #     )

        page.render(rootPage)
        page.navigate("/talk")

    # ------ 消息收发 ------
    def receive_message(self, event: MessageToUser):
        """收到助手主动发来的消息：只负责追加气泡，不关心它对应哪条用户消息"""
        self._append_chat({"text": event.content, "is_user": False})

    def noting_already(self, event: NotingAlready):
        """后台Agent就绪：解锁开始/停止笔记按钮"""
        self._agent_ready = True
        page, set_agent_ready = self._page, self._set_agent_ready
        if page is None or set_agent_ready is None:
            # 界面还没起来，状态已经记下，talk_page 初始化时会自己读
            return
        # 回调在本地总线线程里执行，切回 Flet 的事件循环再改状态
        page.run_task(self._apply_agent_ready, set_agent_ready)

    async def _apply_agent_ready(self, set_agent_ready):
        set_agent_ready(self._agent_ready)

    def task_log_update(self, event: TaskLogUpdate):
        """后台工作日志更新：刷新顶部日志条"""
        self._task_log = {"now_task": event.now_task, "content": event.content}
        page, set_task_log = self._page, self._set_task_log
        if page is None or set_task_log is None:
            # 界面还没起来，状态已经记下，talk_page 初始化时会自己读
            return
        # 回调在本地总线线程里执行，切回 Flet 的事件循环再改状态
        page.run_task(self._apply_task_log, set_task_log, self._task_log)

    async def _apply_task_log(self, set_task_log, log: dict):
        set_task_log(log)

    def _snapshot_chat(self) -> list[dict]:
        with self._chat_lock:
            return list(self._chat_history)

    def _append_chat(self, message: dict):
        """把消息写进聊天记录，并把最新快照交给 UI 线程刷新"""
        with self._chat_lock:
            self._chat_history.append(message)
            snapshot = list(self._chat_history)

        page, set_messages = self._page, self._set_messages
        if page is None or set_messages is None:
            # 界面还没准备好，历史已经存下，talk_page 初始化时会自己读
            return
        # 本回调通常在本地总线线程里执行，必须切回 Flet 的事件循环再改状态
        page.run_task(self._apply_chat, set_messages, snapshot)

    async def _apply_chat(self, set_messages, messages: list[dict]):
        set_messages(messages)

    def set_exit_func(self, func: Callable):
        """用于传入关闭后台BusLoop的命令"""
        # 真得这么写吗？
        self._close_backend = func

    def gui_start(self,):
        # 给主线程用的
        ft.run(self.main)


