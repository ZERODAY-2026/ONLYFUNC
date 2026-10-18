"""Web app ke liye free local port dhoondta hai. Chalao: python -m datamind.ports [start]"""
import socket
import sys


def free_port(start: int = 8501, tries: int = 20) -> int:
    for port in range(start, start + tries):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:  # wahan koi sun nahi raha
                return port
    raise RuntimeError(f"No free port found between {start} and {start + tries - 1}")


if __name__ == "__main__":
    print(free_port(int(sys.argv[1]) if len(sys.argv) > 1 else 8501))
