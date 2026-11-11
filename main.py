"""LCIP Adjudicator: start the desktop window (default) or the localhost browser fallback."""
import argparse
import sys
import webbrowser

from lcip.api import Api
from lcip.paths import data_dir, resource_dir


def run_browser(api, port):
    from lcip.server import serve
    httpd = serve(api, port)
    url = f"http://127.0.0.1:{port}/"
    print(f"LCIP running at {url} (local only). Saves: {data_dir()}. Ctrl+C to stop.")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description="Littoral Commander supply, health and combat adjudicator")
    parser.add_argument("--browser", action="store_true", help="use your web browser instead of the app window")
    parser.add_argument("--port", type=int, default=8642, help="port for --browser mode (bound to 127.0.0.1)")
    args = parser.parse_args()

    api = Api()
    if args.browser:
        return run_browser(api, args.port)
    try:
        import webview
    except ImportError:
        print("pywebview is not installed; falling back to browser mode.", file=sys.stderr)
        return run_browser(api, args.port)
    index = resource_dir() / "web" / "index.html"
    webview.create_window("LCIP Adjudicator", str(index), js_api=api, width=1400, height=900, min_size=(1000, 650))
    webview.start()


if __name__ == "__main__":
    main()
