from typing import Dict, Callable, Any, List

class EventDispatcher:
    """Quản lý và phát các sự kiện."""
    def __init__(self):
        self._listeners: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}

    def register(self, event_type: str, callback: Callable[[Dict[str, Any]], None]):
        """Đăng ký một callback cho một loại sự kiện."""
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)

    def unregister(self, event_type: str, callback: Callable[[Dict[str, Any]], None]):
        """Hủy đăng ký một callback cho một loại sự kiện."""
        if event_type in self._listeners:
            self._listeners[event_type].remove(callback)
            if not self._listeners[event_type]:
                del self._listeners[event_type]

    def dispatch(self, event_type: str, data: Dict[str, Any]):
        """Phát sự kiện tới tất cả các callback đã đăng ký."""
        if event_type in self._listeners:
            for callback in self._listeners[event_type]:
                callback(data)