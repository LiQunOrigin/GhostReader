"""单实例 + 参数转发。

第一个进程监听本地套接字；后来的进程把「要打开的文件」发过去再退出，
这样双击第二本书不会毫无反应。
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

KEY = "ghostreader-ipc-v1"


class SingleInstance(QObject):
    messageReceived = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server: QLocalServer | None = None
        self._clients: list[QLocalSocket] = []

    def notify_running(self, payload: str, timeout: int = 300) -> bool:
        """已有实例则把 payload 发过去并返回 True。"""
        sock = QLocalSocket()
        sock.connectToServer(KEY)
        if not sock.waitForConnected(timeout):
            return False
        sock.write(payload.encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(timeout)
        sock.disconnectFromServer()
        return True

    def listen(self) -> bool:
        QLocalServer.removeServer(KEY)  # 清理上次崩溃残留的套接字文件
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(KEY):
            return False
        self.server.newConnection.connect(self._on_new_connection)
        return True

    def _on_new_connection(self):
        while self.server and self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            if conn is None:
                continue
            self._clients.append(conn)
            conn.readyRead.connect(lambda c=conn: self._read(c))
            conn.disconnected.connect(lambda c=conn: self._drop(c))
            if conn.bytesAvailable():
                self._read(conn)

    def _read(self, conn: QLocalSocket):
        data = bytes(conn.readAll()).decode("utf-8", "replace").strip()
        if data:
            self.messageReceived.emit(data)

    def _drop(self, conn: QLocalSocket):
        if conn in self._clients:
            self._clients.remove(conn)
        conn.deleteLater()

    def close(self):
        if self.server:
            self.server.close()
            QLocalServer.removeServer(KEY)
            self.server = None


def payload_from_argv(argv: list[str]) -> str:
    """取第一个看起来像 EPUB 的参数；没有则返回空串（表示“把窗口调出来”）。"""
    for a in argv:
        if a.startswith("-psn") or a.startswith("-"):
            continue
        if a.lower().endswith(".epub"):
            # 转发给另一个进程时必须用绝对路径，对方的 CWD 不一定相同
            return str(Path(a).expanduser().resolve())
    return ""
