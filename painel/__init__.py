"""pAInel — the second interface for CLI agents."""
from .server import serve, load_board, save_board, render

__version__ = "0.1.0"
__all__ = ["serve", "load_board", "save_board", "render", "__version__"]
