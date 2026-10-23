"""Run slicer API calls on the Qt main thread and wait for the result.

The HTTP server and the agent loop live in worker threads, but the scene,
settings and backend may only be touched from the main Qt thread.
"""
import threading

from UM.Application import Application


class MainThreadTimeout(Exception):
    pass


def run_on_main(func, *args, timeout=60, **kwargs):
    app = Application.getInstance()
    if threading.current_thread() is app.getMainThread():
        return func(*args, **kwargs)

    done = threading.Event()
    box = {}

    def wrapper():
        try:
            box["result"] = func(*args, **kwargs)
        except Exception as e:  # re-raised in the calling thread
            box["error"] = e
        finally:
            done.set()

    app.callLater(wrapper)
    if not done.wait(timeout):
        raise MainThreadTimeout("Slicer main thread did not answer in %s s" % timeout)
    if "error" in box:
        raise box["error"]
    return box.get("result")
