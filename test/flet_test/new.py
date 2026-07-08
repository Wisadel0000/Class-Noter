import flet as ft

def main(page:ft.Page):
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
            ft.context.page.navigate("/")
        elif selected_index == 1:
            ft.context.page.navigate("/page2")
        await page.close_drawer()

    drawer = ft.NavigationDrawer(
        on_dismiss=handle_dismissal,
        on_change=handle_change,
        controls=[
            ft.Container(height=12),
            ft.NavigationDrawerDestination(
                label="Item 1",
                icon=ft.Icons.DOOR_BACK_DOOR_OUTLINED,
                selected_icon=ft.Icons.DOOR_BACK_DOOR,
            ),
            ft.Divider(thickness=2),
            ft.NavigationDrawerDestination(
                label="Item 2",
                icon=ft.Icons.MAIL_OUTLINED,
                selected_icon=ft.Icons.MAIL,
            ),
            ft.NavigationDrawerDestination(
                label="Item 3",
                icon=ft.Icons.PHONE_OUTLINED,
                selected_icon=ft.Icons.PHONE,
            ),
        ],
    )

    @ft.component
    def Home():
        return ft.Container(
            ft.Column(
                [
                    ft.Text("这是首页的内容", size=30),
                    ft.FilledButton(
                        "展开侧边栏",
                        on_click=handle_show_drawer,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
        )

    @ft.component
    def About():
        return ft.Container(
            ft.Column(
                [
                    ft.Text("这是设置页面的内容", size=30),
                    ft.FilledButton(
                        "展开侧边栏",
                        on_click=handle_show_drawer,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
        )

    @ft.component
    def App():
        return ft.Router([
            ft.Route(index=True, path="page1", component=Home),
            ft.Route(path="page2", component=About),
        ])

    page.drawer =drawer
    page.render(App)


ft.run(main)
