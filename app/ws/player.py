"""app/ws/player.py — Player WebSocket route (/ws/player)."""


def register_player_ws(sock):
    @sock.route("/ws/player")
    def player_endpoint(ws):
        # Implementation in Milestone 5
        pass
