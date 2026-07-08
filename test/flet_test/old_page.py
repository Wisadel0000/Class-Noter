"""Flet 客户端 — FrontAgent 对话窗口"""
import config
import flet as ft
import eventbus as bus
from model_front_agent import FrontAgent



_agent = FrontAgent()

_now_page = 0


def main(page: ft.Page):
    page.title = "课堂助手"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window.width = 600
    page.window.height = 700
    page.theme = ft.Theme(font_family="Microsoft YaHei")

    # chat_page
    chat_list = ft.ListView(spacing=10, expand=True, auto_scroll=True)
    input_field = ft.TextField(hint_text="输入消息...", expand=True, border_radius=8)

    def add_bubble(text: str, is_user: bool):
        alignment = ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START
        bg = ft.Colors.BLUE_100 if is_user else ft.Colors.GREY_200
        name = "你" if is_user else "助手"
        chat_list.controls.append(
            ft.Column(
                [
                    ft.Text(name, size=12, weight=ft.FontWeight.BOLD),
                    ft.Container(
                        content=ft.Text(text, selectable=True),
                        padding=12,
                        bgcolor=bg,
                        border_radius=10,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.END if is_user else ft.CrossAxisAlignment.START,
            )
        )
        page.update()

    def send_message(e):
        text = input_field.value.strip()
        if not text:
            return
        input_field.value = ""
        page.update()

        add_bubble(text, is_user=True)

        reply = _agent.sent_message(text)
        add_bubble(reply, is_user=False)

    input_field.on_submit = send_message

    #config_page
    model_name_field= ft.TextField(label="MODEL_NAME", value=config.get_value("LLM_MODEL"),)
    api_key_field= ft.TextField(label="API_KEY", value= config.get_value("LLM_API_KEY"),
                                 password=True, can_reveal_password=True,)
    base_url_field= ft.TextField(label="BaseURL", value=config.get_value("LLM_BASE_URL"), )
    note_path_filed = ft.TextField(label = "note_path", value=config.get_value("NOTE_ROOT_PATH"))

    def save_config(e):
        config.save_model_config(
            model = model_name_field.value,
            api_key = api_key_field.value,
            base_url = base_url_field.value,
            note_path = note_path_filed.value
        )


    #根目录（占位&调试）
    @ft.component
    def root_page():
        return ft.Text("这是占位根目录，请访问/talk")
    #聊天界面
    @ft.component
    def talk_page():
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Row(
                            [ft.IconButton(icon= ft.Icons.MENU, on_click=handle_show_drawer),
                             ft.ElevatedButton("启动后台Agent", icon=ft.Icons.PLAY_ARROW,
                                               on_click=bus.BUS.emit(bus.RunNoter)
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

    #配置界面
    @ft.component
    def config_page():
        return ft.Container(
            content=ft.Column([
                ft.IconButton(icon=ft.Icons.MENU, on_click=handle_show_drawer),
                ft.Divider(),#"模型配置"
                ft.Row([
                    ft.Text("模型名："),model_name_field,],
                ),
                ft.Row([
                    ft.Text("API密钥："),api_key_field,],
                ),
                ft.Row([
                    ft.Text("BaseURL："),base_url_field],
                ),
                ft.Row([
                    ft.Text("笔记保存根目录："),note_path_filed,
                ]),
                ft.Row([
                    ft.FilledButton("保存更改", icon=ft.Icons.SAVE, on_click=save_config)
                    ],
                ),

            ]),
            expand=True,
        )

    # 路由管理
    @ft.component
    def rootPage():
        return ft.Router([
            ft.Route(index=True, component= root_page),
            ft.Route(path= "/talk", component= talk_page),
            ft.Route(path= "/config", component= config_page),
        ])

    # 侧边栏定义
    async def handle_show_drawer(e):
        await page.show_drawer()

    def handle_dismissal(e: ft.Event[ft.NavigationDrawer]):
        print("Drawer dismissed!")

    async def handle_change(e: ft.Event[ft.NavigationDrawer]):
        print(f"Selected Index changed: {e.control.selected_index}")
        selected_index = e.control.selected_index
        drawer.open = False
        page.update()
        if selected_index == 0:
            ft.context.page.navigate("/talk")
        elif selected_index == 1:
            ft.context.page.navigate("/config")
        await page.close_drawer()

    drawer = ft.NavigationDrawer(
        on_dismiss=handle_dismissal,
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
    page.render(rootPage)
    page.navigate("/talk")

def app_start():
    ft.app(target=main)


if __name__ == "__main__":
    app_start()