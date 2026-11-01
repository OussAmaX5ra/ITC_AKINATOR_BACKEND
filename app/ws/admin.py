"""app/ws/admin.py — Admin WebSocket route (/ws/admin)."""


def register_admin_ws(sock):
    @sock.route("/ws/admin")
    def admin_endpoint(ws):
        # Implementation in Milestone 5
        pass
