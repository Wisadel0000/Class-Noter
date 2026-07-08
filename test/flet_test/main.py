import flet as ft


def main(page: ft.Page):
    page.title = "侧边栏切换页面示例"
    page.theme_mode = ft.ThemeMode.LIGHT

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
            await page.push_route("/page1")
        elif selected_index == 1:
            await page.push_route("/page2")
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

    page.drawer = drawer

    def get_page_1():
        return ft.View(
            [
                ft.Text("这是首页的内容", size=30),
                ft.IconButton(icon=ft.Icons.ADD),
                ft.Button(content="11111", on_click=handle_show_drawer),
            ],
            route="/page1",
            drawer=drawer,
            vertical_alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def get_page_2():
        return ft.View(
            [
                ft.Text("这是设置页面的内容", size=30),
                ft.IconButton(icon=ft.Icons.SETTINGS),
                ft.Button(content="11111", on_click=handle_show_drawer),
            ],
            route="/page2",
            drawer=drawer,
            vertical_alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def on_route_change(e: ft.RouteChangeEvent):
        print("Route changed to:", page.route)
        page.views.clear()
        if page.route == "/page1" or page.route == "/":
            page.views.append(get_page_1())
        elif page.route == "/page2":
            page.views.append(get_page_2())
        page.update()

    def on_view_pop(e: ft.ViewPopEvent):
        page.views.pop()
        page.update()

    page.on_route_change = on_route_change
    page.on_view_pop = on_view_pop

    page.navigate("/page1")


ft.run(main)
