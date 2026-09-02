"""In-process HTTP checks (core/checks/) vs subprocess tool wrappers
(core/tools/): this package holds the web-hygiene checks that are cheap
enough to do directly with aiohttp — no external binary needed — so the
webcheck pipeline (core/pipelines/webcheck.py) doesn't grow a dependency
for something a handful of GET/POST requests can already answer.
"""
