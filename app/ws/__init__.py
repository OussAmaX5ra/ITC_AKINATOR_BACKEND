"""app/ws — WebSocket handler package (flask-sock)."""
from app.ws.admin import register_admin_ws
from app.ws.player import register_player_ws
from app.ws.robot import register_robot_ws


def register_websockets(sock):
    """Register all WebSocket routes on the flask-sock instance."""
    register_robot_ws(sock)
    register_player_ws(sock)
    register_admin_ws(sock)
