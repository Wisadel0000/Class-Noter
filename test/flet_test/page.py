"""Flet 客户端 — FrontAgent 对话窗口"""
import config
import flet as ft
import eventbus as bus
from model_front_agent import FrontAgent


_agent = FrontAgent()
_chat_history: list[dict] = []


def main(page: ft.Page):
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
            ft.Route(path="/config", component=config_page),
        ])

    # ── 根目录 ──
    @ft.component
    def root_page():
        return ft.Text("这是占位根目录，请访问/talk")

    # ── 聊天页面 ──
    @ft.component
    def talk_page():
        messages, set_messages = ft.use_state(list(_chat_history))
        input_text, set_input_text = ft.use_state("")

        def send_message(e):
            text = input_text.strip()
            if not text:
                return
            reply = _agent.sent_message(text)
            new_msgs = [
                *messages,
                {"text": text, "is_user": True},
                {"text": reply, "is_user": False},
            ]
            _chat_history[:] = new_msgs
            set_messages(new_msgs)
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
                             ft.ElevatedButton("启动后台Agent", icon=ft.Icons.PLAY_ARROW,
                                               on_click=lambda _: bus.BUS.emit(bus.RunNoter))],
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

    # ── 配置页面 ──
    @ft.component
    def config_page():
        model_name, set_model_name = ft.use_state(config.get_value("LLM_MODEL"))
        api_key, set_api_key = ft.use_state(config.get_value("LLM_API_KEY"))
        base_url, set_base_url = ft.use_state(config.get_value("LLM_BASE_URL"))
        note_path, set_note_path = ft.use_state(config.get_value("NOTE_ROOT_PATH"))

        def save_config(e):
            config.save_model_config(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                note_path=note_path,
            )

        return ft.Container(
            content=ft.Column([
                ft.IconButton(icon=ft.Icons.MENU, on_click=handle_show_drawer),
                ft.Divider(),
                ft.Row([ft.Text("模型名："), ft.TextField(value=model_name, on_change=lambda e: set_model_name(e.control.value))]),
                ft.Row([ft.Text("API密钥："), ft.TextField(value=api_key, password=True, can_reveal_password=True, on_change=lambda e: set_api_key(e.control.value))]),
                ft.Row([ft.Text("BaseURL："), ft.TextField(value=base_url, on_change=lambda e: set_base_url(e.control.value))]),
                ft.Row([ft.Text("笔记保存根目录："), ft.TextField(value=note_path, on_change=lambda e: set_note_path(e.control.value))]),
                ft.Row([ft.FilledButton("保存更改", icon=ft.Icons.SAVE, on_click=save_config)]),
            ]),
            expand=True,
        )

    page.render(rootPage)
    page.navigate("/talk")


def app_start():
    ft.app(target=main)


if __name__ == "__main__":
    app_start()
