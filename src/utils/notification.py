# src/utils/notification.py
"""macOSデスクトップ通知"""

import subprocess


def send_notification(title: str, message: str, sound: bool = True) -> None:
    """macOSのネイティブ通知を送信

    Args:
        title: 通知のタイトル
        message: 通知のメッセージ
        sound: 通知音を鳴らすかどうか
    """
    sound_script = 'sound name "default"' if sound else ""
    script = f'''
    display notification "{message}" with title "{title}" {sound_script}
    '''
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True
        )
    except Exception:
        # 通知に失敗しても処理は続行
        pass
