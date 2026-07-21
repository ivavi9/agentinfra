import sys
import asyncio
from unittest.mock import MagicMock

# Mock vault_client to avoid loading vault credentials during local compilation check
sys.modules["vault_client"] = MagicMock()

from agent import LangGraphAgent  # noqa: E402


async def test_compile():
    print("Testing LangGraphAgent compilation...")
    try:
        agent = LangGraphAgent(api_key="mock_key")
        print("LangGraphAgent compiled successfully!")

        # Test state graph nodes
        print("Verifying state graph nodes...")
        nodes = list(agent.graph.nodes.keys())
        print("Nodes in compiled state graph:", nodes)
        assert "route" in nodes
        assert "infra" in nodes
        assert "code" in nodes
        assert "research" in nodes
        print("Graph structure is valid!")
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_compile())
