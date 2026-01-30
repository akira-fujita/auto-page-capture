# src/capture/window_manager.py
"""macOSのウィンドウ一覧取得と管理"""

from typing import TypedDict
import Quartz
from AppKit import NSWorkspace, NSApplicationActivateIgnoringOtherApps


class WindowBounds(TypedDict):
    x: int
    y: int
    width: int
    height: int


class WindowInfo(TypedDict):
    id: int
    name: str
    owner: str
    pid: int
    bounds: WindowBounds


class WindowManager:
    """macOSのウィンドウを管理するクラス"""

    TITLEBAR_HEIGHT = 28  # macOSの標準タイトルバー高さ

    def get_window_list(self) -> list[WindowInfo]:
        """表示中のウィンドウ一覧を取得"""
        windows = []
        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID
        )

        for window in window_list:
            # 通常のウィンドウのみ（メニューバーやドックを除外）
            layer = window.get(Quartz.kCGWindowLayer, 0)
            if layer != 0:
                continue

            name = window.get(Quartz.kCGWindowName, "")
            owner = window.get(Quartz.kCGWindowOwnerName, "")

            # 名前がないウィンドウはスキップ
            if not name and not owner:
                continue

            bounds = window.get(Quartz.kCGWindowBounds, {})
            windows.append(WindowInfo(
                id=window.get(Quartz.kCGWindowNumber, 0),
                name=name or "(無題)",
                owner=owner,
                pid=window.get(Quartz.kCGWindowOwnerPID, 0),
                bounds=WindowBounds(
                    x=int(bounds.get("X", 0)),
                    y=int(bounds.get("Y", 0)),
                    width=int(bounds.get("Width", 0)),
                    height=int(bounds.get("Height", 0)),
                ),
            ))

        return windows

    def get_content_bounds(self, bounds: WindowBounds) -> WindowBounds:
        """タイトルバーを除いたコンテンツ領域を計算"""
        return WindowBounds(
            x=bounds["x"],
            y=bounds["y"] + self.TITLEBAR_HEIGHT,
            width=bounds["width"],
            height=bounds["height"] - self.TITLEBAR_HEIGHT,
        )

    def bring_to_front(self, pid: int) -> bool:
        """指定PIDのアプリをフォアグラウンドに移動"""
        apps = NSWorkspace.sharedWorkspace().runningApplications()
        for app in apps:
            if app.processIdentifier() == pid:
                return app.activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps
                )
        return False
