"""
agent.py — Entry point shim for the LangGraph multi-agent supervisor.

This module re-exports SupervisorAgent as LangGraphAgent so that main.py
requires no changes. The full specialist routing logic lives in app/agents/.
"""

from agents.supervisor import SupervisorAgent as LangGraphAgent

__all__ = ["LangGraphAgent"]
