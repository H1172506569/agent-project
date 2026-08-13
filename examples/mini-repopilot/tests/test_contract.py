import subprocess
import sys
from pathlib import Path

import mini_repopilot


def test_mini_repopilot_module_and_public_exports():
    assert mini_repopilot.RepoPilot is not None
    assert mini_repopilot.FakeModelClient is not None
    assert not hasattr(mini_repopilot, "MiniAgent")
    result = subprocess.run([sys.executable, "-m", "mini_repopilot", "--help"], capture_output=True, text=True, check=True)
    assert "Teaching-sized RepoPilot agent harness" in result.stdout


def test_readme_main_mapping_points_to_existing_files():
    repo_root = Path(__file__).resolve().parents[3]
    main_files = [
        "repopilot/cli.py",
        "repopilot/runtime.py",
        "repopilot/agent_loop.py",
        "repopilot/context_manager.py",
        "repopilot/providers/clients.py",
        "repopilot/tool_executor.py",
        "repopilot/tools.py",
        "repopilot/task_state.py",
        "repopilot/run_store.py",
        "repopilot/workspace.py",
    ]
    for path in main_files:
        assert (repo_root / path).exists()
