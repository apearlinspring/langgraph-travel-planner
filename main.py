"""
Convenience entrypoint for local development.
"""
import runpy


if __name__ == "__main__":
    runpy.run_module("app.run", run_name="__main__")
