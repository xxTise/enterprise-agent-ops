"""IT Agent: selects and prices hardware. Defined with the watsonx Orchestrate ADK."""

from ibm_watsonx_orchestrate.agent_builder.agents import Agent, AgentKind, AgentStyle

from agents.config import LLM
from tools.it_tools import order_hardware

it_agent = Agent(
    name="it_agent",
    kind=AgentKind.NATIVE,
    llm=LLM,
    style=AgentStyle.DEFAULT,
    description="IT procurement agent that selects laptops for new hires and prices the order.",
    instructions=(
        "You are the IT Agent for enterprise expansion. When a team needs laptops, choose the "
        "best-fit model from the hardware catalog: MacBook Pro 14 for engineering/design, "
        "ThinkPad X1 Carbon for general/sales, Dell Latitude 7450 for operations/support. "
        "Always call the order_hardware tool to calculate the invoice; never estimate prices yourself. "
        "You do not approve spend. Hand the invoice total to the Finance Agent for budget approval."
    ),
    tools=[order_hardware],
)
