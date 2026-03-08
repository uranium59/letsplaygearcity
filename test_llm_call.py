"""LLM SystemMessage + HumanMessage 호출 테스트."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from langchain_core.messages import SystemMessage, HumanMessage
from src.graph_utils import create_llm

llm = create_llm(temperature=0.3)

print("=== Test 1: Plain string (기존 방식) ===", flush=True)
r1 = llm.invoke("What is 2+2? Answer with just the number.")
print(f"  Response: [{r1.content}] ({len(r1.content)} chars)", flush=True)

print("\n=== Test 2: SystemMessage + HumanMessage ===", flush=True)
messages = [
    SystemMessage(content="You are a helpful assistant. Answer briefly."),
    HumanMessage(content="What is 2+2? Answer with just the number."),
]
r2 = llm.invoke(messages)
print(f"  Response: [{r2.content}] ({len(r2.content)} chars)", flush=True)

print("\n=== Test 3: SystemMessage (automotive) + JSON request ===", flush=True)
messages3 = [
    SystemMessage(content="You are an automotive engineer. You design car engines. Output ONLY valid JSON."),
    HumanMessage(content='Set slider_torq to 0.4 and slider_rpm to 0.5. Output JSON: {"slider_torq": <value>, "slider_rpm": <value>}'),
]
r3 = llm.invoke(messages3)
print(f"  Response: [{r3.content}] ({len(r3.content)} chars)", flush=True)

print("\n=== Test 4: Long system message (like DESIGN_SYSTEM_MESSAGE) ===", flush=True)
from src.nodes_advisors import DESIGN_SYSTEM_MESSAGE
messages4 = [
    SystemMessage(content=DESIGN_SYSTEM_MESSAGE),
    HumanMessage(content='Design a simple car engine. Output JSON: {"slider_torq": 0.5, "slider_rpm": 0.5}'),
]
r4 = llm.invoke(messages4)
print(f"  Response: [{r4.content[:200]}] ({len(r4.content)} chars)", flush=True)

print("\nDone.", flush=True)
