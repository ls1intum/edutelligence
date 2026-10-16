"""``python -m logos_node_manager`` is the same as the ``node-manager`` command."""

from logos_node_manager.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
