"""Flet 客户端 — FrontAgent 对话窗口"""
import flet as ft
import threading

from event.event_core import Bus,Loop,Router
from event.events import MessageToUser, UserMessage, AppStart, NotingStart, NotingStop




class GuiModule:

    def __init__(self, core_bus_router:Router,core_loop:Loop,local_bus:Bus,local_loop:Loop):
        self._core_loop = core_loop
        self._local_bus = local_bus
        self._local_loop = local_loop
        self._chat_history: list[dict] = []
        # 笔记是否正在进行的唯一真源，界面重新挂载时据此恢复按钮状态
        self._noting = False

        # 界面跑起来后由 main / talk_page 填上的引用
        self._page: ft.Page | None = None
        self._set_messages = None
        # 聊天记录会被 UI 线程和本地总线线程同时读写，加把锁
        self._chat_lock = threading.Lock()

        # ------ 注册回调函数 ------
        # self._local_bus.subscribe(AppStart,self.app_start)服了flet没法跑在副线程上
        # 助手什么时候说话由它自己决定，这里只负责把收到的消息显示出来
        self._local_bus.subscribe(MessageToUser,self.receive_message)

        # ------ 订阅总线事件 ------
        # core_bus_router.subscribe(AppStart,self._local_loop)
        core_bus_router.subscribe(MessageToUser,self._local_loop)

    def main(self,page: ft.Page):
        self._page = page
        page.title = "课堂助手"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.window.width = 600
        page.window.height = 700
        page.theme = ft.Theme(font_family="Microsoft YaHei")

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
                ft.context.page.navigate("/config")
            await page.close_drawer()

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
                ft.Divider(thickness=2),
                ft.NavigationDrawerDestination(
                    label="选项",
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
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
                #TODO：ft.Route(path="/config", component=config_page),  #不许删除这一行
            ])

        # ── 根目录 ──
        @ft.component
        def root_page():
            return ft.Text("这是占位根目录，请访问/talk")

        # ── 聊天页面 ──
        @ft.component
        def talk_page():
            messages, set_messages = ft.use_state(self._snapshot_chat())
            # 让总线回调在任意线程都能拿到当前页面的状态更新函数
            self._set_messages = set_messages
            input_text, set_input_text = ft.use_state("")
            noting, set_noting = ft.use_state(self._noting)

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
                return ft.Column(
                    [
                        ft.Text("你" if m["is_user"] else "助手", size=12, weight=ft.FontWeight.BOLD),
                        ft.Container(
                            content=ft.Text(m["text"], selectable=True),
                            padding=12,
                            bgcolor=ft.Colors.BLUE_100 if m["is_user"] else ft.Colors.GREY_200,
                            border_radius=10,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.END if m["is_user"] else ft.CrossAxisAlignment.START,
                )

            chat_list = ft.ListView(
                controls=[build_bubble(m) for m in messages],
                spacing=10,
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
                        ft.Container(
                            content=ft.Row(
                                [ft.IconButton(icon=ft.Icons.MENU, on_click=handle_show_drawer),
                                 ft.ElevatedButton(
                                     "停止笔记" if noting else "开始笔记",
                                     icon=ft.Icons.STOP_ROUNDED if noting else ft.Icons.PLAY_ARROW,
                                     bgcolor=ft.Colors.RED_400 if noting else None,
                                     color=ft.Colors.WHITE if noting else None,
                                     on_click=toggle_noting,
                                 )],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            padding=5,
                            bgcolor=ft.Colors.GREY_100,
                        ),
                        ft.Container(content=chat_list, padding=10, expand=True),
                        ft.Container(
                            content=ft.Row(
                                [input_field, ft.IconButton(ft.Icons.SEND_ROUNDED, on_click=send_message)],
                                spacing=5,
                            ),
                            padding=10,
                            bgcolor=ft.Colors.WHITE,
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

    def gui_start(self,):
        # 给主线程用的
        ft.app(self.main)
