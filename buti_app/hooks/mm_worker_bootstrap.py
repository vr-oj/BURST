"""Divert the isolated camera helper before PyInstaller's Qt runtime hooks."""
import sys

if len(sys.argv) == 3 and sys.argv[1] == "--burst-mm-worker":
    from cameras.micro_manager_process import worker_main
    worker_main(int(sys.argv[2]))
    sys.exit(0)
