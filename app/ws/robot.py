"""app/ws/robot.py — Robot WebSocket route (/ws/robot)."""


def register_robot_ws(sock):
    @sock.route("/ws/robot")
    def robot_endpoint(ws):
        # Implementation in Milestone 5
        pass
