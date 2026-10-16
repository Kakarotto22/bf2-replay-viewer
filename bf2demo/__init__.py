"""Clean-room Refractor 2 / Battlefield 2 demo replay parser.

A standalone parser for ``.bf2demo`` replay files produced by the Refractor 2
engine (Battlefield 2). A demo is the server's network stream for a fake
client: :mod:`bf2demo.reader` unframes it, :mod:`bf2demo.packet` splits each
packet into game events (:mod:`bf2demo.events`) and ghost updates
(:mod:`bf2demo.networkables`), and :mod:`bf2demo.replay` builds the match
model. Every layout is taken from the shipped ``bf2_ia32`` server binary; the
only bundled game data is the template-id table (:mod:`bf2demo.templatedb`).
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
